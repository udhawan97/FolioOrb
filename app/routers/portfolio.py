from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Portfolio, Holding
from app.schemas import HoldingCreate, HoldingUpdate, HoldingResponse, PortfolioCreate
from app.config import settings
from app.services.stock_service import get_all_quotes

# All routes in this file are grouped under the /api/portfolio prefix
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


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
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active == True)
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
            Holding.is_active == True,
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
    Calculate total portfolio value using live prices × shares.
    Returns breakdown per holding and grand total.
    """
    # Get holdings from database
    holdings = (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active == True)
        .all()
    )

    tickers = [h.ticker for h in holdings]
    shares_map = {h.ticker: h.shares for h in holdings}

    # Fetch live prices
    from app.services.stock_service import get_all_quotes

    quotes = get_all_quotes(tickers)

    result = []
    total_value = 0.0
    total_daily_change = 0.0

    for q in quotes:
        if q.get("error"):
            continue
        ticker = q["ticker"]
        shares = shares_map.get(ticker, 0)
        current_value = shares * q["current_price"]
        daily_value_change = shares * q["day_change"]

        total_value += current_value
        total_daily_change += daily_value_change

        
        cost_basis = (shares * q.get("avg_cost", 0)) if q.get("avg_cost") else 0
        unrealized_gain = (current_value - cost_basis) if cost_basis > 0 else 0
        unrealized_gain_pct = (
            ((current_value - cost_basis) / cost_basis * 100) if cost_basis > 0 else 0
        )
        
        result.append({
            "ticker": ticker,
            "name": q["name"],
            "shares": shares,
            "current_price": q["current_price"],
            "avg_cost": q.get("avg_cost"),
            "current_value": round(current_value, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_gain": round(unrealized_gain, 2),
            "unrealized_gain_pct": round(unrealized_gain_pct, 2),
            "day_change_pct": q["day_change_pct"],
            "daily_value_change": round(daily_value_change, 2),
            "allocation_pct": 0,
        })


    # Calculate allocation percentages
    for item in result:
        if total_value > 0:
            item["allocation_pct"] = round(
                (item["current_value"] / total_value) * 100, 1
            )

    total_cost_basis = sum(item["cost_basis"] for item in result)

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
        "total_unrealized_gain": round(total_value - total_cost_basis, 2),
        "best_performer": (
            max(result, key=lambda x: x["day_change_pct"]) if result else None
        ),
        "worst_performer": (
            min(result, key=lambda x: x["day_change_pct"]) if result else None
        ),
        "holdings": result,
    }
