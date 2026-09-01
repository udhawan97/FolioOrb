# pylint: disable=too-many-lines
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.database import get_db
from app.models import Holding, RealizedTrade
from app.routers.deps import require_portfolio
from app.schemas import (
    HoldingCreate,
    HoldingRemoval,
    HoldingUpdate,
    PortfolioCreate,
    RealizedTradeUpdate,
)
from app.config import settings
from app.services.stock_service import (
    get_all_quotes,
    get_stock_data,
    ticker_shape_is_safe,
    validate_ticker_symbol,
)
from app.services import dividend_calendar
from app.services import financial_currency
from app.services import holdings_csv
from app.services import holdings_repository
from app.services import portfolio_lifecycle
from app.services import portfolio_valuation
from app.services import realized_sales
from app.services import verdict_pipeline
from app.services import write_serialization
from app.services.earnings_radar import get_earnings_events
from app.services.dividend_income import compute_portfolio_income
from app.services.etf_overlap import compute_etf_overlap
from app.services.fund_costs import compute_fee_drag
from app.services.realized_recap import build_realized_recap
from app.services.portfolio_projection import get_cached_projection
from app.services.world_markets import get_world_markets_cached
from app.services.portfolio_analytics import (
    compute_risk_metrics,
    compute_correlation_matrix,
    compute_drawdown,
    compute_contribution,
    compute_range_performance,
    compute_market_context,
    compute_benchmark_comparison,
    compute_return_calendar,
    compute_portfolio_beta,
    compute_rolling_volatility,
    compute_sector_tilt,
    compute_conviction_gaps,
    compute_confidence_spectrum,
    compute_macro_alignment,
)

# All routes in this file are grouped under the /api/portfolio prefix
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ── Shared helpers ─────────────────────────────────────────────────────

# Shared with the review router, which used to keep its own divergent copy.
_require_portfolio = require_portfolio


def _holdings_with_quote_data(holdings: list[dict]) -> list[dict]:
    """Merge full quotes onto priced valuation rows.

    The valuation prices the book with fast quotes, which carry no fund
    metadata; expense ratio and quote type only exist on the full quote. Rows
    whose quote failed keep their valuation fields and simply arrive without
    fund metadata, which the fee/overlap services report as unknown.
    """
    tickers = [h["ticker"] for h in holdings]
    quotes = {
        str(quote.get("ticker") or ""): quote
        for quote in get_all_quotes(tickers)
        if not quote.get("error")
    }
    return [{**quotes.get(h["ticker"], {}), **h} for h in holdings]


# ── Portfolio Endpoints ────────────────────────────────────────────────


@router.post("/create")
def create_portfolio(
    data: PortfolioCreate,
    db: Session = Depends(get_db),  # FastAPI injects a DB session automatically
):
    """Create a new named portfolio and return its ID."""
    portfolio = portfolio_lifecycle.create_portfolio(db, data.name, data.description)
    return {"id": portfolio.id, "name": portfolio.name, "message": "Portfolio created"}


@router.get("/", response_model=list[dict])
def get_portfolios(db: Session = Depends(get_db)):
    """Return a list of all portfolios (id and name only)."""
    portfolio_lifecycle.require_portfolio(db, 1)
    portfolios = portfolio_lifecycle.list_portfolios(db)
    return [{"id": p.id, "name": p.name} for p in portfolios]


@router.patch("/{portfolio_id}")
def rename_portfolio(
    portfolio_id: int, data: PortfolioCreate, db: Session = Depends(get_db)
):
    """Rename a portfolio (and optionally update its description)."""
    try:
        portfolio = portfolio_lifecycle.rename_portfolio(
            db, portfolio_id, data.name, data.description
        )
    except portfolio_lifecycle.PortfolioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Portfolio not found") from exc
    return {"id": portfolio.id, "name": portfolio.name, "message": "Portfolio renamed"}


@router.delete("/{portfolio_id}")
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    """Delete a portfolio and everything scoped to it.

    Guards: the default portfolio (id 1, auto-recreated) and the last remaining
    portfolio can't be deleted. The models use plain foreign keys with no
    ``ON DELETE CASCADE``, so the lifecycle module clears every owned table.
    """
    try:
        name = portfolio_lifecycle.delete_portfolio(db, portfolio_id)
    except portfolio_lifecycle.PortfolioDeletionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except portfolio_lifecycle.PortfolioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Portfolio not found") from exc
    return {"message": f"Deleted portfolio '{name}'"}


# ── Holdings Endpoints ─────────────────────────────────────────────────


@router.get("/holdings")
def get_holdings(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Return all active holdings for a portfolio (defaults to portfolio 1)."""
    _require_portfolio(portfolio_id, db)
    holdings = holdings_repository.active(db, portfolio_id)
    return {
        "portfolio_id": portfolio_id,
        "holdings": [
            {
                "id": h.id,
                "ticker": h.ticker,
                "shares": h.shares,
                "avg_cost": h.avg_cost,
                "is_watchlist": bool(h.is_watchlist),
                "hold_class": h.hold_class or "auto",
                "notes": h.notes,
            }
            for h in holdings
        ],
        "count": len(holdings),
    }


@router.get("/earnings")
def get_earnings_radar(
    portfolio_id: int = 1,
    window: int = Query(30, ge=1, le=60),
    db: Session = Depends(get_db),
):
    """Upcoming-earnings events for a portfolio's holdings (stocks only).

    Watchlist tickers are included — a watched name's earnings matter too.
    Events come soonest-first; the list is empty when nothing reports within
    `window` days. ETFs, funds, and tickers without a known date are omitted.
    """
    _require_portfolio(portfolio_id, db)
    watchlist_by_ticker = {
        ticker: meta["is_watchlist"]
        for ticker, meta in holdings_repository.meta_map(db, portfolio_id).items()
    }
    events = get_earnings_events(list(watchlist_by_ticker.keys()), window_days=window)
    for event in events:
        event["is_watchlist"] = watchlist_by_ticker.get(event["ticker"], False)
    return {
        "portfolio_id": portfolio_id,
        "window_days": window,
        "events": events,
        "count": len(events),
    }


@router.post("/holdings")
def add_holding(
    data: HoldingCreate, portfolio_id: int = 1, db: Session = Depends(get_db)
):
    """Add a new stock holding to the portfolio."""
    _require_portfolio(portfolio_id, db)

    # Prevent adding the same ticker twice to the same portfolio
    existing = holdings_repository.active_by_ticker(db, portfolio_id, data.ticker)
    if existing:
        raise HTTPException(
            status_code=400, detail=f"{data.ticker} already in portfolio"
        )

    # Intentional network check: catch invalid symbols before storing the holding.
    validation = validate_ticker_symbol(data.ticker)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": validation["message"],
                "suggestions": validation["suggestions"],
            },
        )

    holding = Holding(
        portfolio_id=portfolio_id,
        ticker=data.ticker,
        shares=data.shares or 0.0,
        avg_cost=data.avg_cost,
        notes=data.notes,
        thesis_review_interval_days=data.thesis_review_interval_days,
        is_watchlist=data.is_watchlist or False,
        hold_class=data.hold_class or "auto",
    )
    if holdings_repository.add_active(db, holding) is None:
        raise HTTPException(
            status_code=400, detail=f"{data.ticker} already in portfolio"
        )
    db.commit()
    db.refresh(holding)
    return {
        "id": holding.id,
        "ticker": holding.ticker,
        "message": f"{data.ticker} added",
    }


# ── CSV import / export ────────────────────────────────────────────────
# Defined above the parameterized /holdings/{holding_id} routes so the static
# "export"/"import" paths are never shadowed by the {holding_id} matcher.

# Content types accepted outright, and those accepted only with a .csv filename
# (browsers/tools often send these — or nothing at all — for a genuine .csv).
_CSV_CONTENT_TYPES_DIRECT = {"text/csv", "application/vnd.ms-excel"}
_CSV_CONTENT_TYPES_WITH_EXT = {"application/octet-stream", "text/plain", ""}


@router.get("/holdings/export")
def export_holdings(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Stream the portfolio's active holdings as a clean CSV.

    The output is exactly the strict-import template, so export → import round-trips.
    Every cell is neutralized against spreadsheet formula injection.
    """
    _require_portfolio(portfolio_id, db)
    # Alphabetical is this endpoint's presentation choice, not part of what
    # "active" means, so the repository's oldest-first rows are sorted here.
    holdings = sorted(holdings_repository.active(db, portfolio_id), key=lambda h: h.ticker)
    filename = f"folioorb-holdings-p{portfolio_id}-{date.today().isoformat()}.csv"
    return StreamingResponse(
        holdings_csv.build_export_csv(holdings),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _claude_configured() -> bool:
    """Backend 'is Claude usable' check — mirrors ai_service.py's key idiom."""
    return bool(settings.ANTHROPIC_API_KEY.strip())


def _header_mismatch_detail(unrecognized: list[str], mode: str) -> dict:
    """Structured 400 body for a messy header that couldn't be mapped."""
    cols = ", ".join(unrecognized)
    return {
        "message": (
            f"Some columns weren't recognized: {cols}. Match the template "
            "(Export CSV shows it) or connect Claude in Settings and I'll map almost "
            "any brokerage export."
        ),
        "mode": mode,
        "unrecognized_columns": unrecognized,
        "expected_columns": list(holdings_csv.CSV_COLUMNS),
    }


def _resolve_import_mode(header, data_rows, force_local):
    """Decide the import path and return (template_rows, mode, column_mapping).

    Clean header → strict local (zero tokens). Messy header with a key and not
    force_local → Claude remap, falling back to strict on any RemapError. A messy
    header we can't map (no key / forced local / remap failed) raises a 400.
    """
    unrecognized = holdings_csv.unrecognized_columns(header)
    if not unrecognized:
        return data_rows, "local", None

    can_remap = (
        not force_local
        and _claude_configured()
        and len(header) <= holdings_csv.MAX_HEADER_COLUMNS
    )
    if not can_remap:
        raise HTTPException(
            status_code=400, detail=_header_mismatch_detail(unrecognized, "local")
        )

    try:
        mapping = holdings_csv.remap_columns_with_claude(header, data_rows)
        return holdings_csv.apply_mapping(mapping, data_rows), "claude", mapping
    except holdings_csv.RemapError:
        # Deterministic fallback: a genuinely messy header can't be salvaged locally.
        raise HTTPException(
            status_code=400,
            detail=_header_mismatch_detail(unrecognized, "claude_fallback"),
        ) from None


def _prepare_import_external(header, data_rows, force_local, existing_tickers):
    """Run the complete synchronous provider/Claude segment with no DB session."""
    template_rows, mode, column_mapping = _resolve_import_mode(
        header, data_rows, force_local
    )
    existing = {str(ticker).strip().upper() for ticker in existing_tickers}
    candidate_tickers = sorted(
        ticker
        for ticker in {
            (row.get("ticker") or "").strip().upper() for row in template_rows
        }
        if ticker and ticker not in existing and ticker_shape_is_safe(ticker)
    )
    if candidate_tickers:
        get_all_quotes(candidate_tickers)
    report_rows, to_insert = holdings_csv.process_import_rows(
        template_rows, existing, validate_ticker_symbol
    )
    return report_rows, to_insert, mode, column_mapping


@router.post("/holdings/import")
async def import_holdings(
    file: UploadFile = File(...),
    portfolio_id: int = 1,
    force_local: bool = False,
    db: Session = Depends(get_db),
):
    """Import holdings from a CSV upload.

    Local path (always available, no key): strict exact-schema parse. Claude path
    (key configured, messy header, not force_local): Claude remaps the columns, then
    the cleaned rows go through the SAME strict validation. Any Claude failure falls
    back to the strict local parse — the import never hard-fails because Claude did.

    Returns a per-row report (added/skipped/error). Bad rows never block good rows.
    """
    # Content-type allowlist; the ambiguous types only pass with a .csv filename.
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    filename = (file.filename or "").lower()
    csv_named = filename.endswith(".csv")
    if content_type not in _CSV_CONTENT_TYPES_DIRECT and not (
        content_type in _CSV_CONTENT_TYPES_WITH_EXT and csv_named
    ):
        raise HTTPException(status_code=415, detail="Please upload a .csv file.")

    raw = await file.read(holdings_csv.MAX_IMPORT_BYTES + 1)
    if len(raw) > holdings_csv.MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large (limit {holdings_csv.MAX_IMPORT_BYTES // 1024} KB).",
        )

    try:
        text = holdings_csv.decode_csv_bytes(raw)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    header, data_rows = holdings_csv.parse_csv_text(text)
    if not header or not data_rows:
        raise HTTPException(status_code=400, detail="The file has no data rows.")
    if len(data_rows) > holdings_csv.MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many rows (limit {holdings_csv.MAX_IMPORT_ROWS}).",
        )
    dupes = holdings_csv.duplicate_columns(header)
    if dupes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Duplicate column name(s): {', '.join(dupes)}. "
                "Give each column a unique header."
            ),
        )

    # Preserve the established import contract: reject a missing Portfolio and
    # skip symbols it already owns before doing provider or Claude work. Close
    # the short read transaction before awaiting the worker so no SQLAlchemy
    # session or database lock crosses the external-work boundary.
    _require_portfolio(portfolio_id, db)
    existing_before = set(holdings_repository.active_tickers(db, portfolio_id))
    db.rollback()

    report_rows, to_insert, mode, column_mapping = await run_in_threadpool(
        _prepare_import_external,
        header,
        data_rows,
        force_local,
        existing_before,
    )

    # Re-read after the await so another writer cannot slip between the initial
    # snapshot and mutation. The partial unique index remains the final arbiter
    # for a writer that races this fresh read.
    _require_portfolio(portfolio_id, db)
    existing_tickers = set(holdings_repository.active_tickers(db, portfolio_id))
    report_rows, to_insert = holdings_csv.reconcile_existing(
        report_rows, to_insert, existing_tickers
    )

    inserted = False
    for create in to_insert:
        holding = Holding(
            portfolio_id=portfolio_id,
            ticker=create.ticker,
            shares=create.shares or 0.0,
            avg_cost=create.avg_cost,
            notes=create.notes,
            thesis_review_interval_days=create.thesis_review_interval_days,
            is_watchlist=create.is_watchlist or False,
            hold_class=create.hold_class or "auto",
        )
        if holdings_repository.add_active(db, holding) is None:
            holdings_csv.mark_concurrent_duplicate(report_rows, create.ticker)
        else:
            inserted = True
    if inserted:
        db.commit()
    # The post-provider reconciliation reads open a transaction even when every
    # row is skipped. End it before Claude narration so no database transaction
    # spans another external await. rollback() is harmless after commit and is
    # intentional here because there are no uncommitted mutations left.
    db.rollback()

    counts = holdings_csv.summarize(report_rows)
    holdings_csv.log_import(portfolio_id, mode, counts)

    result = {
        "portfolio_id": portfolio_id,
        "mode": mode,
        **counts,
        "rows": report_rows,
        "summary": None,
        "column_mapping": column_mapping,
    }
    if mode == "claude":
        narration_input = {
            **result, "unmapped_columns": [
                target for target, source in (column_mapping or {}).items()
                if source is None
            ],
        }
        result["summary"] = await run_in_threadpool(
            holdings_csv.narrate_import_summary, narration_input
        )
    return result


def _ensure_reactivation_available(
    db: Session, portfolio_id: int, holding: Holding, requested_active: bool | None
) -> None:
    """Reject a soft-delete reactivation when its active ticker already exists."""
    if requested_active is not True or holding.is_active:
        return
    active_match = holdings_repository.active_by_ticker(
        db, portfolio_id, holding.ticker
    )
    if active_match is not None and active_match.id != holding.id:
        raise HTTPException(
            status_code=400, detail=f"{holding.ticker} already in portfolio"
        )


def _commit_holding_update(db: Session, holding: Holding) -> None:
    """Commit an edit and translate a concurrent reactivation race."""
    ticker = holding.ticker
    try:
        db.commit()
    except IntegrityError as exc:
        if holdings_repository.is_active_ticker_conflict(exc):
            db.rollback()
            raise HTTPException(
                status_code=400, detail=f"{ticker} already in portfolio"
            ) from exc
        raise


def _prefetch_reduction_quote(
    db: Session,
    portfolio_id: int,
    holding_id: int,
    *,
    new_shares: float | None,
    explicit_price: float | None,
    active_only: bool,
) -> dict:
    """Load a market quote before reserving SQLite's sole writer.

    The holding is deliberately read again after the reservation. This first
    read only discovers whether a quote may be needed; it never authorizes the
    mutation or supplies shares/cost basis to sale arithmetic.
    """
    if explicit_price is not None or new_shares is None:
        db.rollback()
        return {}
    preview = holdings_repository.in_portfolio(
        db, portfolio_id, holding_id, active_only=active_only
    )
    needs_quote = bool(
        preview
        and not preview.is_watchlist
        and new_shares < float(preview.shares or 0.0)
    )
    ticker = str(preview.ticker) if needs_quote else ""
    # End the discovery read before the external provider call and ensure the
    # authoritative query below cannot reuse an identity-map snapshot.
    db.rollback()
    if not needs_quote:
        return {}
    try:
        return get_stock_data(ticker) or {}
    except Exception:  # pylint: disable=broad-exception-caught
        # RealizedSaleLedger maps unavailable or invalid cached quotes to the
        # same actionable 409 as a live loader failure.
        return {}


def _require_editable_holding(
    db: Session, holding: Holding, data: HoldingUpdate
) -> None:
    """Keep owned-position archives on the realized-sale path.

    A removed watchlist row has no sale history, so it may be restored by one
    explicit state-only request. Active owned positions cannot be archived by a
    state-only update, and removed owned positions cannot be revived or edited.
    """
    state_only_watchlist_change = bool(
        holding.is_watchlist
        and data.model_fields_set == {"is_active"}
    )
    if state_only_watchlist_change:
        return
    if holding.is_active and data.is_active is not False:
        return
    removal_required = holding.is_active and data.is_active is False
    db.rollback()
    raise HTTPException(
        status_code=409,
        detail={
            "code": (
                "holding_removal_required"
                if removal_required
                else "holding_archived"
            ),
            "message": (
                "Owned holdings must be reduced or removed through the sale "
                "workflow so realized history stays complete. Archived owned "
                "positions cannot be edited or sold again; add a new holding "
                "for a new owned position."
            ),
        },
    )


@router.put("/holdings/{holding_id}")
def update_holding(
    holding_id: int,
    data: HoldingUpdate,
    db: Session = Depends(get_db),
    portfolio_id: int = 1,
):
    """Update shares, average cost, notes, or active status of an existing holding."""
    market_quote = _prefetch_reduction_quote(
        db,
        portfolio_id,
        holding_id,
        new_shares=data.shares,
        explicit_price=data.sale_price,
        active_only=False,
    )
    write_serialization.begin_financial_write(db)
    holding = holdings_repository.in_portfolio(db, portfolio_id, holding_id)
    if not holding:
        db.rollback()
        raise HTTPException(status_code=404, detail="Holding not found")

    _require_editable_holding(db, holding, data)
    _ensure_reactivation_available(db, portfolio_id, holding, data.is_active)

    # A drop in share count is a sale → record the realized gain/loss first,
    # while we still know the old share count and avg cost. Watchlist (research
    # mode) holdings can hold nonzero shares too, but they're promised to never
    # touch P&L — skip recording for them, matching remove_holding's guard below.
    if data.shares is not None and data.shares < holding.shares:
        try:
            realized_sales.RealizedSaleLedger(
                db,
                portfolio_id,
                # Never fall back to a provider while holding SQLite's writer.
                # If discovery did not need a quote but authoritative state now
                # does, the empty preview fails closed with sale_price_required.
                quote_loader=lambda _ticker: market_quote,
            ).stage_reduction(
                holding, data.shares,
                sale_price=data.sale_price, sale_date=data.sale_date,
            )
        except realized_sales.SalePriceUnavailable as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "sale_price_required",
                    "message": (
                        f"Could not verify a current USD sale price for {exc.ticker}. "
                        "The holding was kept unchanged; enter the actual USD sale "
                        "price to record the sale truthfully."
                    ),
                },
            ) from exc

    # Only update fields that were actually provided (not None)
    if data.shares is not None:
        holding.shares = data.shares
    if data.avg_cost is not None:
        holding.avg_cost = data.avg_cost
    if data.notes is not None:
        holding.notes = data.notes
    if "thesis_review_interval_days" in data.model_fields_set:
        holding.thesis_review_interval_days = data.thesis_review_interval_days
    if data.mark_thesis_reviewed:
        holding.thesis_reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if data.is_active is not None:
        holding.is_active = data.is_active
    if data.is_watchlist is not None:
        holding.is_watchlist = data.is_watchlist
    if data.hold_class is not None:
        holding.hold_class = data.hold_class

    _commit_holding_update(db, holding)
    db.refresh(holding)
    return {
        "ticker": holding.ticker,
        "hold_class": holding.hold_class or "auto",
        "thesis_reviewed_at": (
            holding.thesis_reviewed_at.isoformat()
            if holding.thesis_reviewed_at else None
        ),
        "thesis_review_interval_days": holding.thesis_review_interval_days,
        "message": "Updated successfully",
    }


@router.delete("/holdings/{holding_id}")
def remove_holding(
    holding_id: int,
    db: Session = Depends(get_db),
    portfolio_id: int = 1,
    data: HoldingRemoval | None = None,
):
    """
    Soft-delete a holding by setting is_active=False.
    The row is kept in the database for historical reference.
    """
    removal = data or HoldingRemoval()
    market_quote = _prefetch_reduction_quote(
        db,
        portfolio_id,
        holding_id,
        new_shares=0,
        explicit_price=removal.sale_price,
        active_only=True,
    )
    write_serialization.begin_financial_write(db)
    holding = holdings_repository.in_portfolio(
        db, portfolio_id, holding_id, active_only=True
    )
    if not holding:
        db.rollback()
        raise HTTPException(status_code=404, detail="Holding not found")

    # Watchlist (research-mode) holdings are discarded silently — no realized gain recorded.
    try:
        realized_sales.RealizedSaleLedger(
            db,
            portfolio_id,
            quote_loader=lambda _ticker: market_quote,
        ).stage_reduction(
            holding,
            0,
            sale_price=removal.sale_price,
            sale_date=removal.sale_date,
        )
    except realized_sales.SalePriceUnavailable as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sale_price_required",
                "message": (
                    f"Could not verify a current USD sale price for {exc.ticker}. "
                    "The holding was kept unchanged; enter the actual USD sale "
                    "price to record the sale truthfully."
                ),
            },
        ) from exc

    holding.is_active = False
    db.commit()
    return {
        "ticker": holding.ticker,
        "message": "Holding removed from portfolio",
        "was_watchlist": bool(holding.is_watchlist),
    }


@router.patch("/trades/{trade_id}")
def update_realized_trade(
    trade_id: int,
    data: RealizedTradeUpdate,
    db: Session = Depends(get_db),
    portfolio_id: int = 1,
):
    """Correct one recorded sale in place, re-deriving its realized gain.

    Deleting the trade and redoing the share reduction was the only way to fix a
    mistyped price, and it re-reads the cost basis from the holding as it stands
    now rather than as it stood at the sale — so the correction could move more
    than the typo did. Editing the row touches only what the caller named.

    ``realized_gain`` is never accepted from the caller. It is recomputed from
    whichever of the three inputs survive the edit, so the ledger cannot hold a
    gain that contradicts its own numbers.

    Scoped by ``portfolio_id`` for the same reason the delete path is: resolving
    a row by primary key alone lets a request scoped to one portfolio rewrite
    another portfolio's trade.
    """
    try:
        trade = realized_sales.RealizedSaleLedger(db, portfolio_id).correct(
            trade_id,
            realized_sales.SaleCorrection(
                shares_sold=data.shares_sold,
                sale_price=data.sale_price,
                avg_cost=data.avg_cost,
                sale_date=data.sale_date,
            ),
        )
    except realized_sales.RealizedSaleNotFound as exc:
        raise HTTPException(
            status_code=404, detail="Realized trade not found"
        ) from exc
    return {
        "ticker": trade.ticker,
        "realized_gain": trade.realized_gain,
        "message": f"Updated realized sale for {trade.ticker}",
    }


@router.delete("/trades/{trade_id}")
def remove_realized_trade(
    trade_id: int, db: Session = Depends(get_db), portfolio_id: int = 1
):
    """Delete one realized sale and refresh today's snapshot."""
    try:
        ticker = realized_sales.RealizedSaleLedger(db, portfolio_id).remove(trade_id)
    except realized_sales.RealizedSaleNotFound as exc:
        raise HTTPException(
            status_code=404, detail="Realized trade not found"
        ) from exc
    return {"ticker": ticker, "message": f"Removed realized sale for {ticker}"}


# ── Seed Endpoint ──────────────────────────────────────────────────────


@router.post("/seed")
def seed_portfolio(db: Session = Depends(get_db)):
    """
    Backward-compatible setup helper.
    The default portfolio is now created automatically on first use.
    """
    existing = next(
        (p for p in portfolio_lifecycle.list_portfolios(db) if p.id == 1),
        None,
    )
    portfolio = portfolio_lifecycle.require_portfolio(db, 1)
    return {
        "message": "Already seeded" if existing else "Portfolio seeded successfully",
        "portfolio_id": portfolio.id,
        "holdings_added": 0 if existing else len(settings.DEFAULT_HOLDINGS),
    }


@router.get("/value")
def get_portfolio_value(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Calculate total portfolio value using live prices × shares, plus cumulative
    profit/loss (realized + unrealized). Also refreshes today's snapshot so the
    performance history builds up passively as the dashboard is used.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id, record_snapshot=True)
    result = valuation.holdings

    return {
        "degraded": valuation.degraded,
        "data_quality": valuation.data_quality,
        "missing_tickers": list(valuation.missing_tickers),
        "foreign_currency_tickers": list(valuation.foreign_currency_tickers),
        "excluded_realized_trade_count": valuation.excluded_realized_trade_count,
        "realized_data_quality": valuation.realized_data_quality,
        "priced_position_count": valuation.priced_position_count,
        "expected_position_count": valuation.expected_position_count,
        "total_value": valuation.total_value,
        "total_daily_change": valuation.total_daily_change,
        "total_daily_change_pct": round(
            (
                (
                    valuation.total_daily_change
                    / (valuation.total_value - valuation.total_daily_change)
                )
                * 100
                if valuation.total_value > 0
                else 0
            ),
            2,
        ),
        "total_cost_basis": valuation.total_cost_basis,
        "total_return_cost_basis": valuation.total_return_cost_basis,
        "total_unrealized_gain": valuation.total_unrealized_gain,
        "realized_gain": valuation.realized_gain,
        "total_return": valuation.total_return,
        "total_return_pct": valuation.total_return_pct,
        "best_performer": (
            max(
                (h for h in result if not h.get("is_watchlist")),
                key=lambda x: x["day_change_pct"],
                default=None,
            )
        ),
        "worst_performer": (
            min(
                (h for h in result if not h.get("is_watchlist")),
                key=lambda x: x["day_change_pct"],
                default=None,
            )
        ),
        "holdings": result,
    }


@router.get("/pnl")
def get_pnl(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Profit/loss detail: cumulative totals, the realized-trade ledger, and the
    daily snapshot history (for the performance chart). Reads stored data only —
    no live quotes — so it's cheap to call after a holdings edit.
    """
    _require_portfolio(portfolio_id, db)
    performance = portfolio_valuation.load_performance(db, portfolio_id)
    return {
        "realized_gain": performance.realized_gain,
        "trades": performance.trades,
        "history": performance.history,
        "excluded_realized_trade_count": performance.excluded_realized_trade_count,
        "realized_data_quality": performance.realized_data_quality,
    }


@router.get("/realized-summary")
def get_realized_summary(
    portfolio_id: int = 1,
    year: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Year-by-year recap of realized (closed-trade) P&L for a portfolio.

    Aggregates every explicitly sourced USD `RealizedTrade` — not just the last
    100 the P&L ledger shows — grouped by the calendar year of each sale. Foreign
    and ambiguous legacy facts are counted but excluded from dollar totals.
    `year` selects which year to detail; it defaults to the most recent year
    with trades and falls back to that default for an unknown year. Stored data
    only, no live quotes.
    """
    _require_portfolio(portfolio_id, db)
    stored_trades = (
        db.query(RealizedTrade)
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .order_by(RealizedTrade.created_at.asc())
        .all()
    )
    trades = [
        trade
        for trade in stored_trades
        if financial_currency.is_trusted_reporting_fact(
            trade.sale_currency, trade.sale_price_source
        )
    ]
    recap = build_realized_recap(trades, year=year)
    recap["portfolio_id"] = portfolio_id
    recap["excluded_realized_trade_count"] = len(stored_trades) - len(trades)
    recap["realized_data_quality"] = (
        "partial" if len(stored_trades) != len(trades) else "complete"
    )
    return recap


@router.get("/projection")
def get_portfolio_projection(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Growth scenarios (avg / best / worst) for 30D–10Y horizons, benchmarked
    against S&P 500. Uses 3-year historical volatility; cached for 5 minutes.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return get_cached_projection(valuation.holdings, valuation.total_value)


@router.get("/risk-metrics")
def get_portfolio_risk_metrics(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Annualized return/volatility per holding plus portfolio and S&P 500 points."""
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_risk_metrics(valuation.holdings, valuation.total_value)


@router.get("/correlation")
def get_portfolio_correlation(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Daily-return correlation matrix for current holdings."""
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_correlation_matrix(valuation.holdings)


@router.get("/drawdown")
def get_portfolio_drawdown(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Underwater chart series (% below running peak) from snapshot history."""
    _require_portfolio(portfolio_id, db)
    return compute_drawdown(portfolio_valuation.snapshot_history(db, portfolio_id))


@router.get("/contribution")
def get_portfolio_contribution(
    period: str = "day",
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """Per-holding contribution to portfolio P&L (day, week, or month)."""
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_contribution(valuation.holdings, period=period)


@router.get("/range-performance")
def get_portfolio_range_performance(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Per-holding change for every dashboard time range (1W … 1Y) in one payload.
    Computed from daily closes only — no live quotes — so switching ranges on
    the dashboard costs a single request that covers all ranges.
    """
    _require_portfolio(portfolio_id, db)
    rows = [
        {"ticker": ticker, "shares": meta["shares"], "is_watchlist": meta["is_watchlist"]}
        for ticker, meta in holdings_repository.meta_map(db, portfolio_id).items()
    ]
    return compute_range_performance(rows)


@router.get("/market-context")
def get_portfolio_market_context(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """World indices enriched with portfolio correlation and geographic alignment."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_market_context(result, get_world_markets_cached())


@router.get("/benchmark-comparison")
def get_benchmark_comparison(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Portfolio vs S&P 500 cumulative return and alpha by range."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_benchmark_comparison(
        result,
        portfolio_valuation.snapshot_history(db, portfolio_id),
    )


@router.get("/return-calendar")
def get_return_calendar(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Monthly return heatmap from portfolio snapshot history."""
    _require_portfolio(portfolio_id, db)
    return compute_return_calendar(portfolio_valuation.snapshot_history(db, portfolio_id))


@router.get("/beta")
def get_portfolio_beta(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Portfolio beta vs S&P 500."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_portfolio_beta(result)


@router.get("/rolling-volatility")
def get_rolling_volatility(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Trailing 30-day annualized volatility series."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_rolling_volatility(result)


@router.get("/sector-tilt")
def get_sector_tilt(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Sector overweight / underweight vs S&P 500."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_sector_tilt(result)


@router.get("/conviction-gaps")
def get_conviction_gaps(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Verdict vs position-size mismatches."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    scan = verdict_pipeline.scan_portfolio(db, portfolio_id, force_local=True)
    return compute_conviction_gaps(result, scan.signals or {})


@router.get("/confidence-spectrum")
def get_confidence_spectrum(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Allocation-weighted confidence distribution."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    scan = verdict_pipeline.scan_portfolio(db, portfolio_id, force_local=True)
    return compute_confidence_spectrum(result, scan.signals or {})


@router.get("/fee-drag")
def get_portfolio_fee_drag(
    portfolio_id: int = 1,
    horizon_years: int = Query(10, ge=0, le=40),
    db: Session = Depends(get_db),
):
    """What the portfolio's funds cost in fees — per year and over `horizon_years`.

    Only ETFs/funds carry an expense ratio; stocks are excluded rather than
    counted as unknown. A fund whose ratio is missing or implausible is listed
    as fee-unknown, never charged $0. The long-horizon number assumes a constant
    growth rate, stated in the payload's `assumptions`.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_fee_drag(
        _holdings_with_quote_data(valuation.holdings),
        horizon_years=horizon_years,
    )


@router.get("/etf-overlap")
def get_portfolio_etf_overlap(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Pairwise overlap between held ETFs, from each fund's top-10 holdings.

    Top-10 only — the payload's `basis`/`caveat` say so. Funds without holdings
    data are excluded and reported in `uncovered_tickers`.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_etf_overlap(_holdings_with_quote_data(valuation.holdings))


@router.get("/income")
def get_portfolio_income(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Annual dividend income the portfolio pays you, and its blended yield.

    Non-paying holdings are named, never counted as $0 income. A per-share
    dividend larger than the share price is rejected as bad data.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_portfolio_income(_holdings_with_quote_data(valuation.holdings))


@router.get("/income-calendar")
def get_income_calendar(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Which months pay you — the income card's payers projected over the next
    twelve months from each one's real ex-date history.

    A payerless portfolio returns an honest empty without a single history
    fetch; a payer with unreadable history lands in ``unscheduled``, never
    smeared across invented months.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    income = compute_portfolio_income(_holdings_with_quote_data(valuation.holdings))
    if not income["has_data"]:
        return {"has_data": False, "months": [], "unscheduled": [],
                "total_next_12m": 0.0, "basis": "ex_date"}
    history = dividend_calendar.fetch_dividend_ex_dates(
        [p["ticker"] for p in income["payers"]]
    )
    return dividend_calendar.build_income_calendar(
        income["payers"], history, date.today()
    )


@router.get("/macro-alignment")
def get_macro_alignment(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Index correlation vs geographic exposure scatter data."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_macro_alignment(result, get_world_markets_cached())
