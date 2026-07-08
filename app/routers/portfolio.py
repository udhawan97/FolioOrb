from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Portfolio, Holding, RealizedTrade, PortfolioSnapshot
from app.schemas import HoldingCreate, HoldingUpdate, PortfolioCreate
from app.config import settings
from app.services.stock_service import (
    get_portfolio_quotes,
    get_stock_data,
    validate_ticker_symbol,
)
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


def _ensure_default_portfolio(db):
    """
    Create portfolio 1 on first use so a fresh install can open the dashboard
    without a manual seed command.
    """
    portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()
    if portfolio:
        return portfolio

    portfolio = Portfolio(id=1, name="My Portfolio", description="Local portfolio")
    db.add(portfolio)
    db.flush()

    for ticker in settings.DEFAULT_HOLDINGS:
        db.add(Holding(
            portfolio_id=portfolio.id,
            ticker=ticker,
            shares=0.0,
            hold_class="auto",
        ))

    db.commit()
    db.refresh(portfolio)
    return portfolio


def _get_portfolio_or_404(portfolio_id, db):
    """Return the requested portfolio, auto-creating only the default one."""
    if portfolio_id == 1:
        return _ensure_default_portfolio(db)

    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(
            status_code=404, detail=f"Portfolio {portfolio_id} not found"
        )
    return portfolio


def _compute_portfolio(portfolio_id, db):
    """
    Value every active holding at live prices and return
    (per-holding rows, total_value, total_daily_change, total_cost_basis).

    Cost basis uses each holding's stored avg_cost (NOT the quote), which is
    what makes unrealized gain meaningful.
    """
    holdings = (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .all()
    )
    shares_map = {h.ticker: h.shares for h in holdings}
    cost_map = {h.ticker: (h.avg_cost or 0.0) for h in holdings}
    watchlist_map = {h.ticker: bool(h.is_watchlist) for h in holdings}
    hold_class_map = {h.ticker: (h.hold_class or "auto") for h in holdings}
    id_map = {h.ticker: h.id for h in holdings}

    quotes = get_portfolio_quotes(list(shares_map.keys()))
    realized_stats = _realized_stats_by_ticker(portfolio_id, db)

    result = []
    total_value = 0.0
    total_daily_change = 0.0
    total_cost_basis = 0.0

    for q in quotes:
        if q.get("error"):
            continue
        ticker = q["ticker"]
        shares = shares_map.get(ticker, 0)
        avg_cost = cost_map.get(ticker, 0.0)
        is_watchlist = watchlist_map.get(ticker, False)
        hold_class = hold_class_map.get(ticker, "auto")
        current_value = shares * q["current_price"]
        daily_value_change = shares * q["day_change"]
        cost_basis = shares * avg_cost
        unrealized_gain = (current_value - cost_basis) if cost_basis > 0 else 0.0
        unrealized_gain_pct = (
            (unrealized_gain / cost_basis * 100) if cost_basis > 0 else 0.0
        )
        realized = realized_stats.get(ticker, {})
        combined_cost_basis = cost_basis + realized.get("cost_basis", 0.0)
        combined_gain = unrealized_gain + realized.get("realized_gain", 0.0)
        total_return_pct = (
            (combined_gain / combined_cost_basis * 100)
            if combined_cost_basis > 0
            else None
        )

        # Watchlist (research-mode) holdings are excluded from portfolio totals and snapshots
        if not is_watchlist:
            total_value += current_value
            total_daily_change += daily_value_change
            total_cost_basis += cost_basis

        result.append({
            "ticker": ticker,
            "id": id_map.get(ticker),
            "name": q["name"],
            "shares": shares,
            "current_price": q["current_price"],
            "avg_cost": round(avg_cost, 2),
            "current_value": round(current_value, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_gain": round(unrealized_gain, 2),
            "unrealized_gain_pct": round(unrealized_gain_pct, 2),
            "total_return_pct": (
                round(total_return_pct, 2) if total_return_pct is not None else None
            ),
            "day_change": q["day_change"],
            "day_change_pct": q["day_change_pct"],
            "daily_value_change": round(daily_value_change, 2),
            "allocation_pct": 0,
            "is_watchlist": is_watchlist,
            "hold_class": hold_class,
        })

    for item in result:
        if total_value > 0 and not item.get("is_watchlist"):
            item["allocation_pct"] = round(
                (item["current_value"] / total_value) * 100, 1
            )

    return result, total_value, total_daily_change, total_cost_basis


def _cumulative_realized(portfolio_id, db):
    """Sum of all realized gains/losses recorded for a portfolio."""
    total = (
        db.query(func.coalesce(func.sum(RealizedTrade.realized_gain), 0.0))
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .scalar()
    )
    return round(total or 0.0, 2)


def _realized_stats_by_ticker(portfolio_id, db):
    """Quantity-weighted realized sale stats keyed by ticker."""
    trades = (
        db.query(RealizedTrade)
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .all()
    )

    stats = {}
    for trade in trades:
        ticker = trade.ticker
        shares = trade.shares_sold or 0.0
        item = stats.setdefault(
            ticker,
            {
                "shares_sold": 0.0,
                "sale_proceeds": 0.0,
                "cost_basis": 0.0,
                "realized_gain": 0.0,
            },
        )
        item["shares_sold"] += shares
        item["sale_proceeds"] += shares * (trade.sale_price or 0.0)
        item["cost_basis"] += shares * (trade.avg_cost or 0.0)
        item["realized_gain"] += trade.realized_gain or 0.0

    for item in stats.values():
        item["avg_sell_price"] = (
            item["sale_proceeds"] / item["shares_sold"]
            if item["shares_sold"] > 0
            else None
        )
        item["avg_cost"] = (
            item["cost_basis"] / item["shares_sold"]
            if item["shares_sold"] > 0
            else None
        )
        item["total_return_pct"] = (
            (item["realized_gain"] / item["cost_basis"]) * 100
            if item["cost_basis"] > 0
            else None
        )

    return stats


def _record_reduction(holding, old_shares, new_shares, db):
    """
    If a holding's share count dropped, log the realized gain/loss for the
    sold shares using the live market price as the sale price.
    """
    sold = round(old_shares - new_shares, 6)
    if sold <= 0:
        return

    quote = get_stock_data(holding.ticker)
    price = quote.get("current_price") or 0.0
    basis = holding.avg_cost or 0.0
    sale_price = price if price > 0 else basis  # fall back to basis (gain 0) if no quote

    db.add(RealizedTrade(
        portfolio_id=holding.portfolio_id,
        ticker=holding.ticker,
        shares_sold=sold,
        sale_price=round(sale_price, 2),
        avg_cost=round(basis, 2),
        realized_gain=round((sale_price - basis) * sold, 2),
    ))


def _upsert_daily_snapshot(portfolio_id, totals, db):
    """Create or refresh today's portfolio snapshot (one row per calendar day)."""
    _result, total_value, _daily, total_cost_basis = totals
    # Exclude research-mode (watchlist) holdings from the performance snapshot
    unrealized = round(sum(i["unrealized_gain"] for i in _result if not i.get("is_watchlist")), 2)
    realized = _cumulative_realized(portfolio_id, db)
    total_return = round(unrealized + realized, 2)

    today = date.today().isoformat()

    def _today_snapshot():
        return (
            db.query(PortfolioSnapshot)
            .filter(
                PortfolioSnapshot.portfolio_id == portfolio_id,
                PortfolioSnapshot.snapshot_date == today,
            )
            .first()
        )

    def _apply(target):
        target.total_value = round(total_value, 2)
        target.total_cost_basis = round(total_cost_basis, 2)
        target.unrealized_gain = unrealized
        target.realized_gain = realized
        target.total_return = total_return

    snap = _today_snapshot()
    if snap is None:
        snap = PortfolioSnapshot(portfolio_id=portfolio_id, snapshot_date=today)
        db.add(snap)
    _apply(snap)

    try:
        db.commit()
    except IntegrityError:
        # A concurrent refresh inserted today's row between our SELECT and INSERT.
        # The unique (portfolio_id, snapshot_date) index rejects the duplicate — roll
        # back, re-read the row that won, and refresh it instead of duplicating.
        db.rollback()
        snap = _today_snapshot()
        if snap is not None:
            _apply(snap)
            db.commit()

    return unrealized, realized, total_return


# ── Portfolio Endpoints ────────────────────────────────────────────────


@router.post("/create")
async def create_portfolio(
    data: PortfolioCreate,
    db: Session = Depends(get_db),  # FastAPI injects a DB session automatically
):
    """Create a new named portfolio and return its ID."""
    portfolio = Portfolio(name=data.name, description=data.description)
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)  # Reload from DB to get the auto-assigned ID
    return {"id": portfolio.id, "name": portfolio.name, "message": "Portfolio created"}


@router.get("/", response_model=list[dict])
async def get_portfolios(db: Session = Depends(get_db)):
    """Return a list of all portfolios (id and name only)."""
    _ensure_default_portfolio(db)
    portfolios = db.query(Portfolio).all()
    return [{"id": p.id, "name": p.name} for p in portfolios]


# ── Holdings Endpoints ─────────────────────────────────────────────────


@router.get("/holdings")
async def get_holdings(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Return all active holdings for a portfolio (defaults to portfolio 1)."""
    _get_portfolio_or_404(portfolio_id, db)
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
            }
            for h in holdings
        ],
        "count": len(holdings),
    }


@router.post("/holdings")
async def add_holding(
    data: HoldingCreate, portfolio_id: int = 1, db: Session = Depends(get_db)
):
    """Add a new stock holding to the portfolio."""
    _get_portfolio_or_404(portfolio_id, db)

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


@router.put("/holdings/{holding_id}")
async def update_holding(
    holding_id: int, data: HoldingUpdate, db: Session = Depends(get_db)
):
    """Update shares, average cost, notes, or active status of an existing holding."""
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    # A drop in share count is a sale → record the realized gain/loss first,
    # while we still know the old share count and avg cost.
    if data.shares is not None and data.shares < holding.shares:
        _record_reduction(holding, holding.shares, data.shares, db)

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

    # Past snapshots remain history; only today's snapshot is corrected.
    _upsert_daily_snapshot(portfolio_id, _compute_portfolio(portfolio_id, db), db)
    return {"ticker": ticker, "message": f"Removed realized sale for {ticker}"}


# ── Seed Endpoint ──────────────────────────────────────────────────────


@router.post("/seed")
async def seed_portfolio(db: Session = Depends(get_db)):
    """
    Backward-compatible setup helper.
    The default portfolio is now created automatically on first use.
    """
    existing = db.query(Portfolio).filter(Portfolio.id == 1).first()
    portfolio = _ensure_default_portfolio(db)
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
    _get_portfolio_or_404(portfolio_id, db)
    totals = _compute_portfolio(portfolio_id, db)
    result, total_value, total_daily_change, total_cost_basis = totals

    # Record/refresh today's snapshot and get cumulative P&L figures.
    unrealized, realized, total_return = _upsert_daily_snapshot(portfolio_id, totals, db)
    total_return_pct = round(
        (total_return / total_cost_basis * 100) if total_cost_basis > 0 else 0, 2
    )

    return {
        "total_value": round(total_value, 2),
        "total_daily_change": round(total_daily_change, 2),
        "total_daily_change_pct": round(
            (
                (total_daily_change / (total_value - total_daily_change)) * 100
                if total_value > 0
                else 0
            ),
            2,
        ),
        "total_cost_basis": round(total_cost_basis, 2),
        "total_unrealized_gain": unrealized,
        "realized_gain": realized,
        "total_return": total_return,
        "total_return_pct": total_return_pct,
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
    _get_portfolio_or_404(portfolio_id, db)
    realized = _cumulative_realized(portfolio_id, db)
    realized_stats = _realized_stats_by_ticker(portfolio_id, db)

    trades = (
        db.query(RealizedTrade)
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .order_by(RealizedTrade.created_at.desc())
        .limit(100)
        .all()
    )
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )

    return {
        "realized_gain": realized,
        "trades": [
            {
                "id": t.id,
                "ticker": t.ticker,
                "shares_sold": round(t.shares_sold, 4),
                "sale_price": t.sale_price,
                "avg_cost": t.avg_cost,
                "realized_gain": t.realized_gain,
                "total_return_pct": (
                    round(realized_stats[t.ticker]["total_return_pct"], 2)
                    if realized_stats.get(t.ticker, {}).get("total_return_pct") is not None
                    else None
                ),
                "date": t.created_at.isoformat() if t.created_at else None,
            }
            for t in trades
        ],
        "history": [
            {
                "date": s.snapshot_date,
                "total_value": s.total_value,
                "total_cost_basis": s.total_cost_basis,
                "unrealized_gain": s.unrealized_gain,
                "realized_gain": s.realized_gain,
                "total_return": s.total_return,
            }
            for s in snapshots
        ],
    }


@router.get("/projection")
async def get_portfolio_projection(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Growth scenarios (avg / best / worst) for 30D–10Y horizons, benchmarked
    against S&P 500. Uses 3-year historical volatility; cached for 5 minutes.
    """
    _get_portfolio_or_404(portfolio_id, db)
    result, total_value, _daily, _cost = _compute_portfolio(portfolio_id, db)
    return get_cached_projection(result, total_value)


@router.get("/risk-metrics")
async def get_portfolio_risk_metrics(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Annualized return/volatility per holding plus portfolio and S&P 500 points."""
    _get_portfolio_or_404(portfolio_id, db)
    result, total_value, _daily, _cost = _compute_portfolio(portfolio_id, db)
    return compute_risk_metrics(result, total_value)


@router.get("/correlation")
async def get_portfolio_correlation(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Daily-return correlation matrix for current holdings."""
    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    return compute_correlation_matrix(result)


@router.get("/drawdown")
async def get_portfolio_drawdown(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Underwater chart series (% below running peak) from snapshot history."""
    _get_portfolio_or_404(portfolio_id, db)
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )
    history = [
        {"date": s.snapshot_date, "total_value": s.total_value}
        for s in snapshots
    ]
    return compute_drawdown(history)


@router.get("/contribution")
async def get_portfolio_contribution(
    period: str = "day",
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """Per-holding contribution to portfolio P&L (day, week, or month)."""
    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    return compute_contribution(result, period=period)


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
    _get_portfolio_or_404(portfolio_id, db)
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

    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    world_payload = get_world_markets()
    return compute_market_context(result, world_payload.get("markets", []))


def _portfolio_snapshots(portfolio_id: int, db: Session) -> list[dict]:
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )
    return [{"date": s.snapshot_date, "total_value": s.total_value} for s in snapshots]


@router.get("/benchmark-comparison")
async def get_benchmark_comparison(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Portfolio vs S&P 500 cumulative return and alpha by range."""
    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    return compute_benchmark_comparison(result, _portfolio_snapshots(portfolio_id, db))


@router.get("/return-calendar")
async def get_return_calendar(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Monthly return heatmap from portfolio snapshot history."""
    _get_portfolio_or_404(portfolio_id, db)
    return compute_return_calendar(_portfolio_snapshots(portfolio_id, db))


@router.get("/beta")
async def get_portfolio_beta(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Portfolio beta vs S&P 500."""
    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    return compute_portfolio_beta(result)


@router.get("/rolling-volatility")
async def get_rolling_volatility(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Trailing 30-day annualized volatility series."""
    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    return compute_rolling_volatility(result)


@router.get("/sector-tilt")
async def get_sector_tilt(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Sector overweight / underweight vs S&P 500."""
    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    return compute_sector_tilt(result)


@router.get("/conviction-gaps")
async def get_conviction_gaps(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Verdict vs position-size mismatches."""
    from app.routers.ai import get_all_investment_signals

    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    sig_payload = await get_all_investment_signals(db=db, force_local=True)
    return compute_conviction_gaps(result, sig_payload.get("signals") or {})


@router.get("/confidence-spectrum")
async def get_confidence_spectrum(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Allocation-weighted confidence distribution."""
    from app.routers.ai import get_all_investment_signals

    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    sig_payload = await get_all_investment_signals(db=db, force_local=True)
    return compute_confidence_spectrum(result, sig_payload.get("signals") or {})


@router.get("/macro-alignment")
async def get_macro_alignment(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Index correlation vs geographic exposure scatter data."""
    from app.routers.stocks import get_world_markets  # noqa: PLC0415

    _get_portfolio_or_404(portfolio_id, db)
    result, _total, _daily, _cost = _compute_portfolio(portfolio_id, db)
    world_payload = get_world_markets()
    return compute_macro_alignment(result, world_payload.get("markets", []))
