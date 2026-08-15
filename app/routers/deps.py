"""Shared request-level helpers for the routers.

Small on purpose: this holds the translations from a domain seam to an HTTP
status that more than one router needs, so the same rule isn't written twice
with two different shapes.
"""
from __future__ import annotations

from fastapi import HTTPException, Path
from sqlalchemy.orm import Session

from app.models import Portfolio
from app.services import portfolio_lifecycle
from app.services.ticker import validated_ticker_shape


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


def safe_ticker(ticker: str = Path(...)) -> str:
    """Normalise a `{ticker}` path segment or raise HTTP 422.

    The shape rule already guarded request *bodies* through `app.schemas`; on
    the read side it was applied by hand in two of ten `/{ticker}` handlers, so
    the rest passed a raw path segment to the services and, through them, to a
    vendor URL and the logs. Declaring this dependency puts the rule on the
    seam every one of those routes shares, and hands the handler the normalised
    symbol so it does not repeat that step either.
    """
    try:
        return validated_ticker_shape(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
