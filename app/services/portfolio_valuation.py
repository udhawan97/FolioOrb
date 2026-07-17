"""Deterministic Portfolio valuation and performance-history module.

The interface returns one coherent financial view so callers cannot separate
cost-basis math from quote quality, realized return, watchlist rules, or snapshot
safety. Market data is the only external seam and is injectable for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Holding, PortfolioSnapshot, RealizedTrade
from app.services.stock_service import get_portfolio_quotes

QuoteLoader = Callable[[list[str]], list[dict]]


@dataclass
class PortfolioValuation:  # pylint: disable=too-many-instance-attributes
    """One traceable valuation result for callers and tests."""

    portfolio_id: int
    holdings: list[dict]
    total_value: float
    total_daily_change: float
    total_cost_basis: float
    total_unrealized_gain: float
    realized_gain: float
    total_return: float
    total_return_pct: float
    data_quality: str
    missing_tickers: tuple[str, ...]
    expected_position_count: int
    priced_position_count: int
    snapshot_recorded: bool

    @property
    def degraded(self) -> bool:
        """Compatibility flag for the existing all-quotes-unavailable state."""
        return self.data_quality == "unavailable"


@dataclass
class PortfolioPerformance:
    """Stored realized-trade ledger and daily valuation history."""

    realized_gain: float
    realized_by_ticker: dict[str, dict]
    trades: list[dict]
    history: list[dict]


def _realized_stats(db: Session, portfolio_id: int) -> dict[str, dict]:
    trades = (
        db.query(RealizedTrade)
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .all()
    )
    stats: dict[str, dict] = {}
    for trade in trades:
        shares = float(trade.shares_sold or 0.0)
        item = stats.setdefault(
            str(trade.ticker),
            {
                "shares_sold": 0.0,
                "sale_proceeds": 0.0,
                "cost_basis": 0.0,
                "realized_gain": 0.0,
            },
        )
        item["shares_sold"] += shares
        item["sale_proceeds"] += shares * float(trade.sale_price or 0.0)
        item["cost_basis"] += shares * float(trade.avg_cost or 0.0)
        item["realized_gain"] += float(trade.realized_gain or 0.0)

    for item in stats.values():
        shares_sold = item["shares_sold"]
        cost_basis = item["cost_basis"]
        item["avg_sell_price"] = (
            item["sale_proceeds"] / shares_sold if shares_sold > 0 else None
        )
        item["avg_cost"] = cost_basis / shares_sold if shares_sold > 0 else None
        item["total_return_pct"] = (
            item["realized_gain"] / cost_basis * 100 if cost_basis > 0 else None
        )
    return stats


def _realized_gain(db: Session, portfolio_id: int) -> float:
    total = (
        db.query(func.coalesce(func.sum(RealizedTrade.realized_gain), 0.0))
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .scalar()
    )
    return round(float(total or 0.0), 2)


def _upsert_snapshot(db: Session, valuation: PortfolioValuation) -> bool:
    today = date.today().isoformat()

    def _today_snapshot():
        return (
            db.query(PortfolioSnapshot)
            .filter(
                PortfolioSnapshot.portfolio_id == valuation.portfolio_id,
                PortfolioSnapshot.snapshot_date == today,
            )
            .first()
        )

    def _apply(target: PortfolioSnapshot) -> None:
        target.total_value = valuation.total_value
        target.total_cost_basis = valuation.total_cost_basis
        target.unrealized_gain = valuation.total_unrealized_gain
        target.realized_gain = valuation.realized_gain
        target.total_return = valuation.total_return

    snapshot = _today_snapshot()
    if snapshot is None:
        snapshot = PortfolioSnapshot(
            portfolio_id=valuation.portfolio_id,
            snapshot_date=today,
        )
        db.add(snapshot)
    _apply(snapshot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        snapshot = _today_snapshot()
        if snapshot is None:
            return False
        _apply(snapshot)
        db.commit()
    return True


# This orchestration intentionally keeps quote quality, financial totals, and
# snapshot eligibility in one auditable calculation path.
# pylint: disable=too-many-statements
def evaluate(
    db: Session,
    portfolio_id: int,
    *,
    quote_loader: QuoteLoader | None = None,
    record_snapshot: bool = False,
) -> PortfolioValuation:
    """Build one Portfolio valuation and optionally record safe daily history."""
    holdings = (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .all()
    )
    by_ticker = {str(holding.ticker): holding for holding in holdings}
    quotes = (quote_loader or get_portfolio_quotes)(list(by_ticker))
    realized_stats = _realized_stats(db, portfolio_id)

    rows: list[dict] = []
    total_value = 0.0
    total_daily_change = 0.0
    total_cost_basis = 0.0
    priced_tickers: set[str] = set()

    for quote in quotes:
        if quote.get("error"):
            continue
        ticker = str(quote.get("ticker") or "")
        holding = by_ticker.get(ticker)
        if holding is None:
            continue
        current_price = float(quote.get("current_price") or 0.0)
        shares = float(holding.shares or 0.0)
        avg_cost = float(holding.avg_cost or 0.0)
        is_watchlist = bool(holding.is_watchlist)
        current_value = shares * current_price
        daily_value_change = shares * float(quote.get("day_change") or 0.0)
        cost_basis = shares * avg_cost
        unrealized_gain = current_value - cost_basis if cost_basis > 0 else 0.0
        unrealized_gain_pct = unrealized_gain / cost_basis * 100 if cost_basis > 0 else 0.0
        realized = realized_stats.get(ticker, {})
        combined_cost_basis = cost_basis + float(realized.get("cost_basis") or 0.0)
        combined_gain = unrealized_gain + float(realized.get("realized_gain") or 0.0)
        total_return_pct = (
            combined_gain / combined_cost_basis * 100 if combined_cost_basis > 0 else None
        )

        if not is_watchlist:
            total_value += current_value
            total_daily_change += daily_value_change
            total_cost_basis += cost_basis
            if shares > 0:
                priced_tickers.add(ticker)

        rows.append(
            {
                "ticker": ticker,
                "id": holding.id,
                "name": quote.get("name") or ticker,
                "shares": shares,
                "current_price": current_price,
                "avg_cost": round(avg_cost, 2),
                "current_value": round(current_value, 2),
                "cost_basis": round(cost_basis, 2),
                "unrealized_gain": round(unrealized_gain, 2),
                "unrealized_gain_pct": round(unrealized_gain_pct, 2),
                "total_return_pct": (
                    round(total_return_pct, 2) if total_return_pct is not None else None
                ),
                "day_change": float(quote.get("day_change") or 0.0),
                "day_change_pct": float(quote.get("day_change_pct") or 0.0),
                "daily_value_change": round(daily_value_change, 2),
                "allocation_pct": 0,
                "is_watchlist": is_watchlist,
                "hold_class": str(holding.hold_class or "auto"),
            }
        )

    for row in rows:
        if total_value > 0 and not row["is_watchlist"]:
            row["allocation_pct"] = round(row["current_value"] / total_value * 100, 1)

    expected_tickers = {
        str(holding.ticker)
        for holding in holdings
        if not holding.is_watchlist and float(holding.shares or 0.0) > 0
    }
    missing_tickers = tuple(sorted(expected_tickers - priced_tickers))
    if not expected_tickers or not missing_tickers:
        data_quality = "complete"
    elif priced_tickers:
        data_quality = "partial"
    else:
        data_quality = "unavailable"

    total_unrealized_gain = round(
        sum(row["unrealized_gain"] for row in rows if not row["is_watchlist"]),
        2,
    )
    realized_gain = _realized_gain(db, portfolio_id)
    total_return = round(total_unrealized_gain + realized_gain, 2)
    valuation = PortfolioValuation(
        portfolio_id=portfolio_id,
        holdings=rows,
        total_value=round(total_value, 2),
        total_daily_change=round(total_daily_change, 2),
        total_cost_basis=round(total_cost_basis, 2),
        total_unrealized_gain=total_unrealized_gain,
        realized_gain=realized_gain,
        total_return=total_return,
        total_return_pct=round(
            total_return / total_cost_basis * 100 if total_cost_basis > 0 else 0.0,
            2,
        ),
        data_quality=data_quality,
        missing_tickers=missing_tickers,
        expected_position_count=len(expected_tickers),
        priced_position_count=len(priced_tickers),
        snapshot_recorded=False,
    )
    if record_snapshot and data_quality == "complete":
        valuation.snapshot_recorded = _upsert_snapshot(db, valuation)
    return valuation


def load_performance(
    db: Session,
    portfolio_id: int,
    *,
    trade_limit: int = 100,
) -> PortfolioPerformance:
    """Load stored realized returns and daily history without fetching quotes."""
    realized_stats = _realized_stats(db, portfolio_id)
    trades = (
        db.query(RealizedTrade)
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .order_by(RealizedTrade.created_at.desc())
        .limit(trade_limit)
        .all()
    )
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )
    return PortfolioPerformance(
        realized_gain=_realized_gain(db, portfolio_id),
        realized_by_ticker=realized_stats,
        trades=[
            {
                "id": trade.id,
                "ticker": str(trade.ticker),
                "shares_sold": round(float(trade.shares_sold or 0.0), 4),
                "sale_price": float(trade.sale_price or 0.0),
                "avg_cost": float(trade.avg_cost or 0.0),
                "realized_gain": float(trade.realized_gain or 0.0),
                "total_return_pct": (
                    round(realized_stats[str(trade.ticker)]["total_return_pct"], 2)
                    if realized_stats.get(str(trade.ticker), {}).get("total_return_pct")
                    is not None
                    else None
                ),
                "date": trade.created_at.isoformat() if trade.created_at else None,
            }
            for trade in trades
        ],
        history=[
            {
                "date": snapshot.snapshot_date,
                "total_value": float(snapshot.total_value or 0.0),
                "total_cost_basis": float(snapshot.total_cost_basis or 0.0),
                "unrealized_gain": float(snapshot.unrealized_gain or 0.0),
                "realized_gain": float(snapshot.realized_gain or 0.0),
                "total_return": float(snapshot.total_return or 0.0),
            }
            for snapshot in snapshots
        ],
    )


def snapshot_history(db: Session, portfolio_id: int) -> list[dict]:
    """Return stored daily values for analytics that do not need the trade ledger."""
    return [
        {"date": row["date"], "total_value": row["total_value"]}
        for row in load_performance(db, portfolio_id, trade_limit=0).history
    ]
