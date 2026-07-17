"""Portfolio ownership and lifecycle module.

This module is the single place that knows which persisted records belong to a
Portfolio. HTTP adapters translate its domain errors; callers do not need to
know table order, cache-key encoding, or deletion guards.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AISummary,
    DcaContribution,
    DcaPlan,
    Holding,
    Portfolio,
    PortfolioSnapshot,
    RealizedTrade,
    VerdictSnapshot,
)
from app.services.narrative_cache import portfolio_scope


class PortfolioLifecycleError(Exception):
    """Base class for Portfolio lifecycle failures."""


class PortfolioNotFoundError(PortfolioLifecycleError):
    """Raised when a requested Portfolio does not exist."""


class PortfolioDeletionError(PortfolioLifecycleError):
    """Raised when a Portfolio is protected from deletion."""


def list_portfolios(db: Session) -> list[Portfolio]:
    """Return Portfolios in stable creation order."""
    return db.query(Portfolio).order_by(Portfolio.id).all()


def require_portfolio(db: Session, portfolio_id: int) -> Portfolio:
    """Return a Portfolio, creating only the default Portfolio on first use."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if portfolio is not None:
        return portfolio
    if portfolio_id != 1:
        raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")

    portfolio = Portfolio(id=1, name="My Portfolio", description="Local portfolio")
    db.add(portfolio)
    db.flush()
    for ticker in settings.DEFAULT_HOLDINGS:
        db.add(
            Holding(
                portfolio_id=portfolio.id,
                ticker=ticker,
                shares=0.0,
                hold_class="auto",
            )
        )
    db.commit()
    db.refresh(portfolio)
    return portfolio


def create_portfolio(db: Session, name: str, description: str | None = None) -> Portfolio:
    """Create and return a named Portfolio."""
    portfolio = Portfolio(name=name, description=description)
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


def rename_portfolio(
    db: Session,
    portfolio_id: int,
    name: str,
    description: str | None,
) -> Portfolio:
    """Rename a Portfolio while preserving its description when omitted."""
    portfolio = require_portfolio(db, portfolio_id)
    portfolio.name = name
    if description is not None:
        portfolio.description = description
    db.commit()
    db.refresh(portfolio)
    return portfolio


def delete_portfolio(db: Session, portfolio_id: int) -> str:
    """Delete one non-default Portfolio and every record it owns."""
    if portfolio_id == 1:
        raise PortfolioDeletionError("The default portfolio can't be deleted.")
    if db.query(Portfolio).count() <= 1:
        raise PortfolioDeletionError("You can't delete your only portfolio.")

    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if portfolio is None:
        raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")

    plan_ids = [
        row[0]
        for row in db.query(DcaPlan.id).filter(DcaPlan.portfolio_id == portfolio_id).all()
    ]
    if plan_ids:
        db.query(DcaContribution).filter(
            DcaContribution.plan_id.in_(plan_ids)
        ).delete(synchronize_session=False)
    db.query(DcaPlan).filter(DcaPlan.portfolio_id == portfolio_id).delete(
        synchronize_session=False
    )
    db.query(RealizedTrade).filter(RealizedTrade.portfolio_id == portfolio_id).delete(
        synchronize_session=False
    )
    db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == portfolio_id
    ).delete(synchronize_session=False)
    db.query(VerdictSnapshot).filter(
        VerdictSnapshot.portfolio_id == portfolio_id
    ).delete(synchronize_session=False)
    db.query(AISummary).filter(AISummary.ticker == portfolio_scope(portfolio_id)).delete(
        synchronize_session=False
    )

    name = str(portfolio.name)
    db.delete(portfolio)
    db.commit()
    return name
