"""Shared request-level helpers for the routers.

Small on purpose: this holds the translations from a domain seam to an HTTP
status that more than one router needs, so the same rule isn't written twice
with two different shapes.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Portfolio
from app.services import portfolio_lifecycle


def require_portfolio(portfolio_id: int, db: Session) -> Portfolio:
    """Resolve a portfolio or raise HTTP 404.

    Both routers that scope by portfolio had their own copy of this, and the
    copies had drifted: one returned the Portfolio, the other returned None, so
    the two could not be swapped for each other. Returning the row is the more
    useful of the two — a caller that only wants the guard can ignore it.
    """
    try:
        return portfolio_lifecycle.require_portfolio(db, portfolio_id)
    except portfolio_lifecycle.PortfolioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
