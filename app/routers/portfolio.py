from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Portfolio, Holding
from app.schemas import HoldingCreate, HoldingUpdate, HoldingResponse, PortfolioCreate
from app.config import settings

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ── Portfolio Endpoints ────────────────────────────────────────────────
# Endpoint to create a new portfolio with a name and description, returns the created portfolio's ID and name.
@router.post("/create")
async def create_portfolio(
    data: PortfolioCreate,
    db: Session = Depends(get_db),  # FastAPI injects the DB session automatically
):
    # Create a new portfolio with the provided name and description
    portfolio = Portfolio(name=data.name, description=data.description)
    db.add(portfolio)
    db.commit() 
    db.refresh(portfolio)  # Reload from DB to get the auto-assigned ID
    return {"id": portfolio.id, "name": portfolio.name, "message": "Portfolio created"}


# Get all portfolios (for simplicity, we return just the ID and name here)
@router.get("/", response_model=list[dict])
async def get_portfolios(db: Session = Depends(get_db)):
    """Get all portfolios."""
    portfolios = db.query(Portfolio).all()
    return [{"id": p.id, "name": p.name} for p in portfolios]


# ── Holdings Endpoints ─────────────────────────────────────────────────


@router.get("/holdings")
async def get_holdings(portfolio_id: int = 1, db: Session = Depends(get_db)):
    # Get all active holdings for a specific portfolio (default is portfolio_id=1). Returns a list of holdings with their ID, ticker, and shares, along with the total count.
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


# Endpoint to add a new holding to the portfolio, with required fields for ticker and shares, and optional fields for average cost and notes. The ticker is automatically converted to uppercase. Returns the ID and ticker of the created holding.
@router.post("/holdings")
async def add_holding(
    data: HoldingCreate, portfolio_id: int = 1, db: Session = Depends(get_db)
):
    # Add a new holding to the portfolio with the given ticker, shares, average cost, and notes. The ticker is automatically converted to uppercase. Returns the ID and ticker of the created holding.
    # Check if portfolio exists
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(
            status_code=404, detail=f"Portfolio {portfolio_id} not found"
        )

    # Check if the holding already exists in the portfolio (same ticker and active)
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


# Endpoint to update an existing holding's shares, average cost, notes, or active status. Only fields that are provided (not None) will be updated. Returns the ticker and a success message.
@router.put("/holdings/{holding_id}")
async def update_holding(
    holding_id: int, data: HoldingUpdate, db: Session = Depends(get_db)
):
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    # Only update fields that were provided (not None)
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
    """Soft-delete a holding (marks is_active=False, does not delete the row)."""
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    holding.is_active = False  # Soft delete — keep for historical reference
    db.commit()
    return {"ticker": holding.ticker, "message": "Holding removed from portfolio"}


# ── Seed Endpoint ──────────────────────────────────────────────────────


@router.post("/seed")
async def seed_portfolio(db: Session = Depends(get_db)):
    """
    One-time setup: create default portfolio and add all 10 holdings.
    Call this once after database initialization.
    """
    # Check if already seeded
    existing = db.query(Portfolio).filter(Portfolio.name == "My Portfolio").first()
    if existing:
        return {"message": "Already seeded", "portfolio_id": existing.id}

    # Create portfolio
    portfolio = Portfolio(
        name="My Portfolio", description="Personal stock and ETF portfolio"
    )
    db.add(portfolio)
    db.flush()  # Get the ID without committing

    # Add all default holdings
    for ticker in settings.DEFAULT_HOLDINGS:
        holding = Holding(
            portfolio_id=portfolio.id,
            ticker=ticker,
            shares=0.0,  # You can update these later
        )
        db.add(holding)

    db.commit()
    return {
        "message": "Portfolio seeded successfully",
        "portfolio_id": portfolio.id,
        "holdings_added": len(settings.DEFAULT_HOLDINGS),
    }
