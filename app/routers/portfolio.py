# pylint: disable=too-many-lines
from datetime import date, datetime
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Holding, RealizedTrade
from app.schemas import HoldingCreate, HoldingUpdate, PortfolioCreate
from app.config import settings
from app.services.stock_service import (
    get_all_quotes,
    get_stock_data,
    normalize_ticker,
    ticker_shape_is_safe,
    validate_ticker_symbol,
)
from app.services import holdings_csv
from app.services import portfolio_lifecycle
from app.services import portfolio_valuation
from app.services.earnings_radar import get_earnings_events
from app.services.dividend_income import compute_portfolio_income
from app.services.etf_overlap import compute_etf_overlap
from app.services.fund_costs import compute_fee_drag
from app.services.realized_recap import build_realized_recap
from app.services.portfolio_projection import get_cached_projection
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


def _require_portfolio(portfolio_id, db):
    """Translate the Portfolio lifecycle seam to an HTTP 404."""
    try:
        return portfolio_lifecycle.require_portfolio(db, portfolio_id)
    except portfolio_lifecycle.PortfolioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


def _record_reduction(holding, old_shares, new_shares, db, *, sale_price=None, sale_date=None):
    """
    If a holding's share count dropped, log the realized gain/loss for the sold
    shares.

    ``sale_price`` / ``sale_date`` let the caller record the *actual* sale (e.g.
    a sale made last month at a different price). When omitted, the live market
    price and today's date are used, preserving the original behavior.
    """
    sold = round(old_shares - new_shares, 6)
    if sold <= 0:
        return

    basis = holding.avg_cost or 0.0
    if sale_price and sale_price > 0:
        price = sale_price
    else:
        quote = get_stock_data(holding.ticker)
        live = quote.get("current_price") or 0.0
        price = live if live > 0 else basis  # fall back to basis (gain 0) if no quote

    trade = RealizedTrade(
        portfolio_id=holding.portfolio_id,
        ticker=holding.ticker,
        shares_sold=sold,
        sale_price=round(price, 2),
        avg_cost=round(basis, 2),
        realized_gain=round((price - basis) * sold, 2),
    )
    if sale_date:
        # Stamp the trade on the real sale date (noon, to survive any tz shift in
        # display) so the year-end recap buckets it into the correct tax year.
        parsed = date.fromisoformat(sale_date)
        trade.created_at = datetime(parsed.year, parsed.month, parsed.day, 12, 0)
    db.add(trade)


# ── Portfolio Endpoints ────────────────────────────────────────────────


@router.post("/create")
async def create_portfolio(
    data: PortfolioCreate,
    db: Session = Depends(get_db),  # FastAPI injects a DB session automatically
):
    """Create a new named portfolio and return its ID."""
    portfolio = portfolio_lifecycle.create_portfolio(db, data.name, data.description)
    return {"id": portfolio.id, "name": portfolio.name, "message": "Portfolio created"}


@router.get("/", response_model=list[dict])
async def get_portfolios(db: Session = Depends(get_db)):
    """Return a list of all portfolios (id and name only)."""
    portfolio_lifecycle.require_portfolio(db, 1)
    portfolios = portfolio_lifecycle.list_portfolios(db)
    return [{"id": p.id, "name": p.name} for p in portfolios]


@router.patch("/{portfolio_id}")
async def rename_portfolio(
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
async def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
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
async def get_holdings(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Return all active holdings for a portfolio (defaults to portfolio 1)."""
    _require_portfolio(portfolio_id, db)
    holdings = (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .all()
    )
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
async def get_earnings_radar(
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
    holdings = (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .all()
    )
    watchlist_by_ticker = {
        normalize_ticker(h.ticker): bool(h.is_watchlist) for h in holdings
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
async def add_holding(
    data: HoldingCreate, portfolio_id: int = 1, db: Session = Depends(get_db)
):
    """Add a new stock holding to the portfolio."""
    _require_portfolio(portfolio_id, db)

    # Prevent adding the same ticker twice to the same portfolio
    existing = (
        db.query(Holding)
        .filter(
            Holding.portfolio_id == portfolio_id,
            Holding.ticker == data.ticker,
            Holding.is_active.is_(True),
        )
        .first()
    )
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
        is_watchlist=data.is_watchlist or False,
        hold_class=data.hold_class or "auto",
    )
    db.add(holding)
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
async def export_holdings(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Stream the portfolio's active holdings as a clean CSV.

    The output is exactly the strict-import template, so export → import round-trips.
    Every cell is neutralized against spreadsheet formula injection.
    """
    _require_portfolio(portfolio_id, db)
    holdings = (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .order_by(Holding.ticker.asc())
        .all()
    )
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
    _require_portfolio(portfolio_id, db)

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

    template_rows, mode, column_mapping = _resolve_import_mode(header, data_rows, force_local)

    existing_tickers = {
        normalize_ticker(t[0])
        for t in db.query(Holding.ticker)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .all()
    }

    # Warm the quote cache once so per-row validation reads cache, not the network.
    # Shape-check first: an unsafe symbol must never reach yfinance (it's rejected in
    # process_import_rows anyway), so only shape-safe candidates get a network warm.
    candidate_tickers = sorted(
        t for t in (
            {(r.get("ticker") or "").strip().upper() for r in template_rows}
            - existing_tickers - {""}
        )
        if ticker_shape_is_safe(t)
    )
    if candidate_tickers:
        get_all_quotes(candidate_tickers)

    report_rows, to_insert = holdings_csv.process_import_rows(
        template_rows, existing_tickers, validate_ticker_symbol
    )

    for create in to_insert:
        db.add(Holding(
            portfolio_id=portfolio_id,
            ticker=create.ticker,
            shares=create.shares or 0.0,
            avg_cost=create.avg_cost,
            notes=create.notes,
            is_watchlist=create.is_watchlist or False,
            hold_class=create.hold_class or "auto",
        ))
    if to_insert:
        db.commit()

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
        result["summary"] = holdings_csv.narrate_import_summary({
            **result, "unmapped_columns": [
                target for target, source in (column_mapping or {}).items()
                if source is None
            ],
        })
    return result


@router.put("/holdings/{holding_id}")
async def update_holding(
    holding_id: int, data: HoldingUpdate, db: Session = Depends(get_db)
):
    """Update shares, average cost, notes, or active status of an existing holding."""
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    # A drop in share count is a sale → record the realized gain/loss first,
    # while we still know the old share count and avg cost. Watchlist (research
    # mode) holdings can hold nonzero shares too, but they're promised to never
    # touch P&L — skip recording for them, matching remove_holding's guard below.
    if data.shares is not None and data.shares < holding.shares and not holding.is_watchlist:
        _record_reduction(
            holding, holding.shares, data.shares, db,
            sale_price=data.sale_price, sale_date=data.sale_date,
        )

    # Only update fields that were actually provided (not None)
    if data.shares is not None:
        holding.shares = data.shares
    if data.avg_cost is not None:
        holding.avg_cost = data.avg_cost
    if data.notes is not None:
        holding.notes = data.notes
    if data.is_active is not None:
        holding.is_active = data.is_active
    if data.is_watchlist is not None:
        holding.is_watchlist = data.is_watchlist
    if data.hold_class is not None:
        holding.hold_class = data.hold_class

    db.commit()
    db.refresh(holding)
    return {
        "ticker": holding.ticker,
        "hold_class": holding.hold_class or "auto",
        "message": "Updated successfully",
    }


@router.delete("/holdings/{holding_id}")
async def remove_holding(holding_id: int, db: Session = Depends(get_db)):
    """
    Soft-delete a holding by setting is_active=False.
    The row is kept in the database for historical reference.
    """
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    # Watchlist (research-mode) holdings are discarded silently — no realized gain recorded.
    if not holding.is_watchlist:
        _record_reduction(holding, holding.shares, 0, db)

    holding.is_active = False
    db.commit()
    return {
        "ticker": holding.ticker,
        "message": "Holding removed from portfolio",
        "was_watchlist": bool(holding.is_watchlist),
    }


@router.delete("/trades/{trade_id}")
async def remove_realized_trade(trade_id: int, db: Session = Depends(get_db)):
    """Delete one realized sale and refresh today's snapshot."""
    trade = db.query(RealizedTrade).filter(RealizedTrade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Realized trade not found")

    portfolio_id = trade.portfolio_id
    ticker = trade.ticker
    db.delete(trade)
    db.commit()

    # Past snapshots remain history; only today's snapshot is corrected — but not
    # while quotes are unavailable, which would stamp today at a misleading $0.
    portfolio_valuation.evaluate(db, portfolio_id, record_snapshot=True)
    return {"ticker": ticker, "message": f"Removed realized sale for {ticker}"}


# ── Seed Endpoint ──────────────────────────────────────────────────────


@router.post("/seed")
async def seed_portfolio(db: Session = Depends(get_db)):
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
async def get_pnl(portfolio_id: int = 1, db: Session = Depends(get_db)):
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
    }


@router.get("/realized-summary")
async def get_realized_summary(
    portfolio_id: int = 1,
    year: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Year-by-year recap of realized (closed-trade) P&L for a portfolio.

    Aggregates every stored `RealizedTrade` — not just the last 100 the P&L
    ledger shows — grouped by the calendar year of each sale. `year` selects
    which year to detail; it defaults to the most recent year with trades and
    falls back to that default for an unknown year. Stored data only, no live
    quotes.
    """
    _require_portfolio(portfolio_id, db)
    trades = (
        db.query(RealizedTrade)
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .order_by(RealizedTrade.created_at.asc())
        .all()
    )
    recap = build_realized_recap(trades, year=year)
    recap["portfolio_id"] = portfolio_id
    return recap


@router.get("/projection")
async def get_portfolio_projection(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Growth scenarios (avg / best / worst) for 30D–10Y horizons, benchmarked
    against S&P 500. Uses 3-year historical volatility; cached for 5 minutes.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return get_cached_projection(valuation.holdings, valuation.total_value)


@router.get("/risk-metrics")
async def get_portfolio_risk_metrics(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Annualized return/volatility per holding plus portfolio and S&P 500 points."""
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_risk_metrics(valuation.holdings, valuation.total_value)


@router.get("/correlation")
async def get_portfolio_correlation(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Daily-return correlation matrix for current holdings."""
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_correlation_matrix(valuation.holdings)


@router.get("/drawdown")
async def get_portfolio_drawdown(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Underwater chart series (% below running peak) from snapshot history."""
    _require_portfolio(portfolio_id, db)
    return compute_drawdown(portfolio_valuation.snapshot_history(db, portfolio_id))


@router.get("/contribution")
async def get_portfolio_contribution(
    period: str = "day",
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """Per-holding contribution to portfolio P&L (day, week, or month)."""
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_contribution(valuation.holdings, period=period)


@router.get("/range-performance")
async def get_portfolio_range_performance(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Per-holding change for every dashboard time range (1W … 1Y) in one payload.
    Computed from daily closes only — no live quotes — so switching ranges on
    the dashboard costs a single request that covers all ranges.
    """
    _require_portfolio(portfolio_id, db)
    holdings = (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .all()
    )
    rows = [
        {
            "ticker": h.ticker,
            "shares": h.shares,
            "is_watchlist": bool(h.is_watchlist),
        }
        for h in holdings
    ]
    return compute_range_performance(rows)


@router.get("/market-context")
async def get_portfolio_market_context(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """World indices enriched with portfolio correlation and geographic alignment."""
    from app.routers.stocks import get_world_markets  # lazy — avoid circular import at load

    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    world_payload = get_world_markets()
    return compute_market_context(result, world_payload.get("markets", []))


@router.get("/benchmark-comparison")
async def get_benchmark_comparison(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Portfolio vs S&P 500 cumulative return and alpha by range."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_benchmark_comparison(
        result,
        portfolio_valuation.snapshot_history(db, portfolio_id),
    )


@router.get("/return-calendar")
async def get_return_calendar(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Monthly return heatmap from portfolio snapshot history."""
    _require_portfolio(portfolio_id, db)
    return compute_return_calendar(portfolio_valuation.snapshot_history(db, portfolio_id))


@router.get("/beta")
async def get_portfolio_beta(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Portfolio beta vs S&P 500."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_portfolio_beta(result)


@router.get("/rolling-volatility")
async def get_rolling_volatility(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Trailing 30-day annualized volatility series."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_rolling_volatility(result)


@router.get("/sector-tilt")
async def get_sector_tilt(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Sector overweight / underweight vs S&P 500."""
    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    return compute_sector_tilt(result)


@router.get("/conviction-gaps")
async def get_conviction_gaps(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Verdict vs position-size mismatches."""
    from app.routers.ai import get_all_investment_signals

    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    sig_payload = await get_all_investment_signals(
        portfolio_id=portfolio_id, db=db, force_local=True
    )
    return compute_conviction_gaps(result, sig_payload.get("signals") or {})


@router.get("/confidence-spectrum")
async def get_confidence_spectrum(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Allocation-weighted confidence distribution."""
    from app.routers.ai import get_all_investment_signals

    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    sig_payload = await get_all_investment_signals(
        portfolio_id=portfolio_id, db=db, force_local=True
    )
    return compute_confidence_spectrum(result, sig_payload.get("signals") or {})


@router.get("/fee-drag")
async def get_portfolio_fee_drag(
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
async def get_portfolio_etf_overlap(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Pairwise overlap between held ETFs, from each fund's top-10 holdings.

    Top-10 only — the payload's `basis`/`caveat` say so. Funds without holdings
    data are excluded and reported in `uncovered_tickers`.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_etf_overlap(_holdings_with_quote_data(valuation.holdings))


@router.get("/income")
async def get_portfolio_income(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Annual dividend income the portfolio pays you, and its blended yield.

    Non-paying holdings are named, never counted as $0 income. A per-share
    dividend larger than the share price is rejected as bad data.
    """
    _require_portfolio(portfolio_id, db)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    return compute_portfolio_income(_holdings_with_quote_data(valuation.holdings))


@router.get("/macro-alignment")
async def get_macro_alignment(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Index correlation vs geographic exposure scatter data."""
    from app.routers.stocks import get_world_markets  # noqa: PLC0415

    _require_portfolio(portfolio_id, db)
    result = portfolio_valuation.evaluate(db, portfolio_id).holdings
    world_payload = get_world_markets()
    return compute_macro_alignment(result, world_payload.get("markets", []))
