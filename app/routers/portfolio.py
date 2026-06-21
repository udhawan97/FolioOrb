from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Portfolio, Holding, RealizedTrade, PortfolioSnapshot
from app.schemas import HoldingCreate, HoldingUpdate, PortfolioCreate
from app.config import settings
from app.services.stock_service import get_all_quotes, get_stock_data

# All routes in this file are grouped under the /api/portfolio prefix
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ── Shared helpers ─────────────────────────────────────────────────────


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

    quotes = get_all_quotes(list(shares_map.keys()))
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

        total_value += current_value
        total_daily_change += daily_value_change
        total_cost_basis += cost_basis

        result.append({
            "ticker": ticker,
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
            "day_change_pct": q["day_change_pct"],
            "daily_value_change": round(daily_value_change, 2),
            "allocation_pct": 0,
        })

    for item in result:
        if total_value > 0:
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
    unrealized = round(sum(i["unrealized_gain"] for i in _result), 2)
    realized = _cumulative_realized(portfolio_id, db)
    total_return = round(unrealized + realized, 2)

    today = date.today().isoformat()
    snap = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.snapshot_date == today,
        )
        .first()
    )
    if snap is None:
        snap = PortfolioSnapshot(portfolio_id=portfolio_id, snapshot_date=today)
        db.add(snap)

    snap.total_value = round(total_value, 2)
    snap.total_cost_basis = round(total_cost_basis, 2)
    snap.unrealized_gain = unrealized
    snap.realized_gain = realized
    snap.total_return = total_return
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
    portfolios = db.query(Portfolio).all()
    return [{"id": p.id, "name": p.name} for p in portfolios]


# ── Holdings Endpoints ─────────────────────────────────────────────────


@router.get("/holdings")
async def get_holdings(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Return all active holdings for a portfolio (defaults to portfolio 1)."""
    holdings = (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .all()
    )
    return {
        "portfolio_id": portfolio_id,
        "holdings": [
            {"id": h.id, "ticker": h.ticker, "shares": h.shares} for h in holdings
        ],
        "count": len(holdings),
    }


@router.post("/holdings")
async def add_holding(
    data: HoldingCreate, portfolio_id: int = 1, db: Session = Depends(get_db)
):
    """Add a new stock holding to the portfolio."""
    # Make sure the target portfolio actually exists
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(
            status_code=404, detail=f"Portfolio {portfolio_id} not found"
        )

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

    holding = Holding(
        portfolio_id=portfolio_id,
        ticker=data.ticker,
        shares=data.shares,
        avg_cost=data.avg_cost,
        notes=data.notes,
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

    db.commit()
    db.refresh(holding)
    return {"ticker": holding.ticker, "message": "Updated successfully"}


@router.delete("/holdings/{holding_id}")
async def remove_holding(holding_id: int, db: Session = Depends(get_db)):
    """
    Soft-delete a holding by setting is_active=False.
    The row is kept in the database for historical reference.
    """
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    # Removing a position realizes the gain/loss on the entire remaining stake.
    _record_reduction(holding, holding.shares, 0, db)

    holding.is_active = False
    db.commit()
    return {"ticker": holding.ticker, "message": "Holding removed from portfolio"}


# ── Seed Endpoint ──────────────────────────────────────────────────────


@router.post("/seed")
async def seed_portfolio(db: Session = Depends(get_db)):
    """
    One-time setup: create the default portfolio and populate it with all default holdings.
    Safe to call repeatedly — returns early if the portfolio already exists.
    """
    # Don't seed again if a portfolio with this name already exists
    existing = db.query(Portfolio).filter(Portfolio.name == "My Portfolio").first()
    if existing:
        return {"message": "Already seeded", "portfolio_id": existing.id}

    portfolio = Portfolio(
        name="My Portfolio", description="Personal stock and ETF portfolio"
    )
    db.add(portfolio)
    db.flush()  # Write to DB to get the generated ID, but don't commit yet

    for ticker in settings.DEFAULT_HOLDINGS:
        holding = Holding(
            portfolio_id=portfolio.id,
            ticker=ticker,
            shares=0.0,  # Update share counts via PUT /holdings/{id} after seeding
        )
        db.add(holding)

    db.commit()
    return {
        "message": "Portfolio seeded successfully",
        "portfolio_id": portfolio.id,
        "holdings_added": len(settings.DEFAULT_HOLDINGS),
    }


@router.get("/value")
async def get_portfolio_value(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Calculate total portfolio value using live prices × shares, plus cumulative
    profit/loss (realized + unrealized). Also refreshes today's snapshot so the
    performance history builds up passively as the dashboard is used.
    """
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
            max(result, key=lambda x: x["day_change_pct"]) if result else None
        ),
        "worst_performer": (
            min(result, key=lambda x: x["day_change_pct"]) if result else None
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
