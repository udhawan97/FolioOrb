"""Single owner of the rule "an active holding in this portfolio".

That rule — `portfolio_id == X AND is_active IS TRUE` — used to be written out
verbatim at a dozen query sites, so redefining "active" meant hunting down every
one of them.  It now lives here once, behind a small read-only interface, and
callers ask for the shape they need instead of re-deriving the filter:

    active()                    → ORM rows
    active_by_ticker()          → one ORM row, or None
    in_portfolio()              → one ORM row by id, active or not
    active_tickers()            → normalised ticker strings
    active_tickers_or_default() → the same, falling back to DEFAULT_HOLDINGS
    meta_map()                  → ticker → position context

Depth comes from what the implementation absorbs behind those five names: the
filter itself, ticker normalisation, dedup, and one ordering every caller can
lean on.  Widening the rule later (an `archived_at` column, say) is a one-line
edit in this module rather than a twelve-file sweep — that is the locality
payoff.

Ordering guarantee
------------------
Every function returns rows in ascending `Holding.id` — insertion order, oldest
first.  The queries this module replaces carried no ORDER BY and leaned on
SQLite handing back rows in rowid order; stating it turns that accident into a
promise, so callers may depend on it.  Two active rows may share a ticker (the
add-holding endpoint forbids it, nothing in the schema does), and when they do
the oldest wins consistently: it is the row `active_by_ticker()` returns, the
one `active_tickers()` keeps, and the one `meta_map()` describes.

This module reads; it never writes.  It is also deliberately not a query
factory — handing back a `Query` would let callers bolt extra filters onto the
rule this module exists to own, which is exactly the shallowness it replaces.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Holding
from app.services.stock_service import DEFAULT_HOLDINGS, normalize_ticker


def active(db: Session, portfolio_id: int) -> list[Holding]:
    """Return the portfolio's active holdings as ORM rows, oldest first."""
    return (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .order_by(Holding.id.asc())
        .all()
    )


def active_by_ticker(db: Session, portfolio_id: int, ticker: str) -> Holding | None:
    """Return the portfolio's oldest active holding for `ticker`, else None.

    The supplied symbol is normalised before matching.  Stored tickers are
    already normalised on every write path, so this stays an exact-column
    comparison and keeps the (portfolio_id, is_active) index usable.
    """
    return (
        db.query(Holding)
        .filter(
            Holding.portfolio_id == portfolio_id,
            Holding.ticker == normalize_ticker(ticker),
            Holding.is_active.is_(True),
        )
        .order_by(Holding.id.asc())
        .first()
    )


def in_portfolio(
    db: Session,
    portfolio_id: int,
    holding_id: int,
    *,
    active_only: bool = False,
) -> Holding | None:
    """Return the holding with `holding_id` **if it belongs to this portfolio**.

    This owns the ownership half of the rule — the part the mutating endpoints
    were missing entirely when they looked a holding up by primary key alone,
    which let a request scoped to one portfolio edit another portfolio's row.

    `active_only` is the policy the two mutating callers genuinely disagree on,
    so it is named rather than assumed. The edit endpoint leaves it False
    because it can flip a soft-deleted row back to active and therefore has to
    be able to find one; thesis review passes True because reviewing a holding
    the user has already removed is meaningless.
    """
    query = db.query(Holding).filter(
        Holding.id == holding_id, Holding.portfolio_id == portfolio_id
    )
    if active_only:
        query = query.filter(Holding.is_active.is_(True))
    return query.first()


def active_tickers(db: Session, portfolio_id: int) -> list[str]:
    """Return the portfolio's active tickers: normalised, deduped, oldest first.

    Blank symbols are dropped.  An empty portfolio yields an empty list — there
    is no fallback here on purpose; see active_tickers_or_default().
    """
    rows = (
        db.query(Holding.ticker)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .order_by(Holding.id.asc())
        .all()
    )
    seen: set[str] = set()
    tickers: list[str] = []
    for row in rows:
        symbol = normalize_ticker(row[0])
        if symbol and symbol not in seen:
            seen.add(symbol)
            tickers.append(symbol)
    return tickers


def active_tickers_or_default(db: Session, portfolio_id: int) -> list[str]:
    """active_tickers(), falling back to the configured DEFAULT_HOLDINGS.

    Only the AI endpoints want this: they must always have something to talk
    about, so a brand-new empty portfolio still gets a briefing.  Every other
    caller — valuation, CSV-import dedup, the holdings listing — would silently
    invent positions the user does not own, so the fallback is opt-in by name
    instead of being baked into active_tickers().

    The result is always a fresh list; DEFAULT_HOLDINGS is shared module state
    and must never be handed out for a caller to mutate.
    """
    return active_tickers(db, portfolio_id) or list(DEFAULT_HOLDINGS)


def meta_map(db: Session, portfolio_id: int) -> dict[str, dict]:
    """Return ticker → position context for the portfolio's active holdings.

    Each value carries the fields callers reason about a position with —
    ``shares``, ``avg_cost``, ``is_watchlist``, ``hold_class`` — already coerced
    away from None so callers never guard.  Keys are normalised tickers in the
    same oldest-first order as active_tickers(), and the two always agree.
    """
    rows = (
        db.query(
            Holding.ticker,
            Holding.shares,
            Holding.avg_cost,
            Holding.is_watchlist,
            Holding.hold_class,
        )
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .order_by(Holding.id.asc())
        .all()
    )
    meta: dict[str, dict] = {}
    for ticker, shares, avg_cost, is_watchlist, hold_class in rows:
        symbol = normalize_ticker(ticker)
        if not symbol or symbol in meta:
            continue
        meta[symbol] = {
            "shares": float(shares or 0),
            "avg_cost": float(avg_cost or 0),
            "is_watchlist": bool(is_watchlist),
            "hold_class": str(hold_class or "auto"),
        }
    return meta
