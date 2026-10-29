"""Deterministic Portfolio valuation and performance-history module.

The interface returns one coherent financial view so callers cannot separate
cost-basis math from quote quality, realized return, watchlist rules, or snapshot
safety. Market data is the only external seam and is injectable for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Callable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PortfolioSnapshot, RealizedTrade
from app.services import financial_currency, holdings_repository
from app.services.stock_service import get_portfolio_quotes, usable_price

QuoteLoader = Callable[[list[str]], list[dict]]

# Every total this module produces is denominated in dollars. Yahoo prices a
# foreign listing in its home currency — and London quotes in *pence*, not
# pounds — so a quote that says anything else is not addable here.
REPORTING_CURRENCY = financial_currency.REPORTING_CURRENCY


class FinancialArithmeticError(ArithmeticError):
    """Financial facts cannot be represented by finite reporting arithmetic."""


def require_finite_amounts(*values: float) -> None:
    """Refuse overflow in derived facts and aggregates without imposing value caps."""
    if not all(value is not None and math.isfinite(value) for value in values):
        raise FinancialArithmeticError(
            "Financial totals exceed finite numeric arithmetic. "
            "Review the position or sale amounts."
        )


@dataclass
class PortfolioValuation:  # pylint: disable=too-many-instance-attributes
    """One traceable valuation result for callers and tests."""

    portfolio_id: int
    holdings: list[dict]
    total_value: float
    total_daily_change: float
    total_cost_basis: float
    total_return_cost_basis: float
    total_unrealized_gain: float
    realized_gain: float
    total_return: float
    total_return_pct: float
    data_quality: str
    missing_tickers: tuple[str, ...]
    foreign_currency_tickers: tuple[str, ...]
    excluded_realized_trade_count: int
    realized_data_quality: str
    expected_position_count: int
    priced_position_count: int
    snapshot_recorded: bool

    @property
    def degraded(self) -> bool:
        """Compatibility flag for the existing all-quotes-unavailable state."""
        return self.data_quality == "unavailable"

    @property
    def reporting_holdings(self) -> list[dict]:
        """Priced USD positions for dollar consumers; ``holdings`` retains identity."""
        return [row for row in self.holdings if financial_currency.eligible_valuation_row(row)]


@dataclass
class PortfolioPerformance:
    """Stored realized-trade ledger and daily valuation history."""

    realized_gain: float
    realized_by_ticker: dict[str, dict]
    trades: list[dict]
    history: list[dict]
    excluded_realized_trade_count: int
    realized_data_quality: str


def _realized_stats(db: Session, portfolio_id: int) -> dict[str, dict]:
    trades = (
        db.query(RealizedTrade)
        .filter(
            RealizedTrade.portfolio_id == portfolio_id,
            financial_currency.trusted_reporting_fact_clause(
                RealizedTrade.sale_currency,
                RealizedTrade.sale_price_source,
            ),
        )
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
        require_finite_amounts(*item.values())
        shares_sold = item["shares_sold"]
        cost_basis = item["cost_basis"]
        item["avg_sell_price"] = (
            item["sale_proceeds"] / shares_sold if shares_sold > 0 else None
        )
        item["avg_cost"] = cost_basis / shares_sold if shares_sold > 0 else None
        item["total_return_pct"] = (
            item["realized_gain"] / cost_basis * 100 if cost_basis > 0 else None
        )
        require_finite_amounts(*(value for value in item.values() if value is not None))
    return stats


def _realized_gain(db: Session, portfolio_id: int) -> float:
    count, total = (
        db.query(func.count(RealizedTrade.id), func.sum(RealizedTrade.realized_gain))
        .filter(
            RealizedTrade.portfolio_id == portfolio_id,
            financial_currency.trusted_reporting_fact_clause(
                RealizedTrade.sale_currency,
                RealizedTrade.sale_price_source,
            ),
        )
        .one()
    )
    # Empty input is zero; NULL from populated financial data can mean overflow
    # on SQLite and must not be mistaken for an empty ledger.
    if count == 0:
        return 0.0
    require_finite_amounts(total)
    return round(float(total), 2)


def validate_stored_financial_totals(db: Session, portfolio_id: int) -> None:
    """Validate pending stored facts before their transaction can commit."""
    costs = [
        float(holding.shares or 0.0) * float(holding.avg_cost or 0.0)
        for holding in holdings_repository.active(db, portfolio_id)
        if not holding.is_watchlist
    ]
    realized = _realized_stats(db, portfolio_id)
    require_finite_amounts(
        *costs, sum(costs) + sum(item["cost_basis"] for item in realized.values()),
        _realized_gain(db, portfolio_id),
    )


def _excluded_realized_trade_count(db: Session, portfolio_id: int) -> int:
    """Count sale facts that cannot truthfully enter dollar aggregates."""
    total = int(
        db.query(func.count(RealizedTrade.id))
        .filter(RealizedTrade.portfolio_id == portfolio_id)
        .scalar()
        or 0
    )
    included = int(
        db.query(func.count(RealizedTrade.id))
        .filter(
            RealizedTrade.portfolio_id == portfolio_id,
            financial_currency.trusted_reporting_fact_clause(
                RealizedTrade.sale_currency,
                RealizedTrade.sale_price_source,
            ),
        )
        .scalar()
        or 0
    )
    return total - included


def _current_price(quote: dict) -> float | None:
    """Coerce a usable positive quote price without leaking bad market data.

    What "usable" means belongs to `stock_service`, which owns quote semantics.
    """
    return usable_price(quote)


def _quote_currency(quote: dict) -> str:
    """The currency a quote is priced in, in the vendor's own spelling.

    A quote that omits the field is treated as dollars, which is what every
    domestic quote has always been assumed to be — so only an *explicitly*
    foreign currency changes anything.

    The casing is preserved rather than folded because it carries meaning:
    Yahoo writes London's pence "GBp" and pounds "GBP", a hundred-fold
    difference that a row displaying its own currency must not erase.
    """
    return financial_currency.quote_currency(quote.get("currency"))


def _is_reporting_currency(currency: str) -> bool:
    """True when a currency is the dollar the totals are denominated in.

    Only here is case folded — for deciding addability, "usd" is "USD", while
    "GBp" and "GBP" are both simply not it.
    """
    return financial_currency.is_reporting_currency(currency)


def _today_snapshot(db: Session, portfolio_id: int) -> PortfolioSnapshot | None:
    today = date.today().isoformat()
    return (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.snapshot_date == today,
        )
        .first()
    )


def _apply_snapshot(target: PortfolioSnapshot, valuation: PortfolioValuation) -> None:
    target.total_value = valuation.total_value
    target.total_cost_basis = valuation.total_cost_basis
    target.unrealized_gain = valuation.total_unrealized_gain
    target.realized_gain = valuation.realized_gain
    target.total_return = valuation.total_return


def stage_today_snapshot(db: Session, valuation: PortfolioValuation) -> PortfolioSnapshot:
    """Stage today's derived valuation without committing the caller's transaction."""
    require_finite_amounts(
        valuation.total_value, valuation.total_cost_basis, valuation.total_unrealized_gain,
        valuation.realized_gain, valuation.total_return,
    )
    snapshot = _today_snapshot(db, valuation.portfolio_id)
    if snapshot is None:
        snapshot = PortfolioSnapshot(
            portfolio_id=valuation.portfolio_id,
            snapshot_date=date.today().isoformat(),
        )
        db.add(snapshot)
    _apply_snapshot(snapshot, valuation)
    return snapshot


def discard_today_snapshot(db: Session, portfolio_id: int) -> None:
    """Stage removal of today's derived row when it cannot be made trustworthy."""
    snapshot = _today_snapshot(db, portfolio_id)
    if snapshot is not None:
        db.delete(snapshot)


def _upsert_snapshot(db: Session, valuation: PortfolioValuation) -> bool:
    stage_today_snapshot(db, valuation)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        snapshot = _today_snapshot(db, valuation.portfolio_id)
        if snapshot is None:
            return False
        _apply_snapshot(snapshot, valuation)
        db.commit()
    return True


# This orchestration intentionally keeps quote quality, financial totals, and
# snapshot eligibility in one auditable calculation path. Which currency a row is
# priced in belongs to that same path — it decides whether the row is addable at
# all — so it is counted here rather than split into a pass that could disagree.
# pylint: disable=too-many-statements,too-many-branches
def evaluate(
    db: Session,
    portfolio_id: int,
    *,
    quote_loader: QuoteLoader | None = None,
    record_snapshot: bool = False,
) -> PortfolioValuation:
    """Build one Portfolio valuation and optionally record safe daily history."""
    holdings = holdings_repository.active(db, portfolio_id)
    by_ticker = {str(holding.ticker): holding for holding in holdings}
    quotes = (quote_loader or get_portfolio_quotes)(list(by_ticker))
    quotes_by_ticker = {str(quote.get("ticker") or ""): quote for quote in quotes}
    realized_stats = _realized_stats(db, portfolio_id)
    excluded_realized_trade_count = _excluded_realized_trade_count(
        db, portfolio_id
    )
    realized_data_quality = (
        "partial" if excluded_realized_trade_count else "complete"
    )

    rows: list[dict] = []
    total_value = 0.0
    total_daily_change = 0.0
    total_cost_basis = 0.0
    priced_tickers: set[str] = set()
    foreign_tickers: set[str] = set()

    for ticker, holding in by_ticker.items():
        quote = quotes_by_ticker.get(ticker, {})
        current_price = None if quote.get("error") else _current_price(quote)
        shares = float(holding.shares or 0.0)
        avg_cost = float(holding.avg_cost or 0.0)
        is_watchlist = bool(holding.is_watchlist)
        currency = _quote_currency(quote) if current_price is not None else None
        # A price in another currency is not a dollar figure, so it cannot join
        # a dollar sum. The row is still built — the user owns the position and
        # should see it, priced as its own market prices it — but it stays out
        # of every total, exactly as an unpriceable quote does.
        addable = _is_reporting_currency(currency)
        current_value = shares * current_price if current_price is not None else None
        cost_basis = shares * avg_cost
        # Finite operands can still overflow; legacy rows and bad quotes must not
        # poison JSON or create a nonfinite daily snapshot.
        if not math.isfinite(cost_basis):
            cost_basis = None
        if current_value is not None and not math.isfinite(current_value):
            current_price = current_value = currency = None
            addable = False
        day_change = float(quote.get("day_change") or 0.0)
        day_change_pct = float(quote.get("day_change_pct") or 0.0)
        day_change = day_change if current_price is not None and math.isfinite(day_change) else None
        day_change_pct = (
            day_change_pct
            if current_price is not None and math.isfinite(day_change_pct) else None
        )
        daily_value_change = shares * day_change if day_change is not None else None
        if daily_value_change is not None and not math.isfinite(daily_value_change):
            daily_value_change = None
        addable = bool(addable and cost_basis is not None and daily_value_change is not None)
        unrealized_gain = (
            current_value - cost_basis if addable and cost_basis > 0 else
            0.0 if addable else None
        )
        unrealized_gain_pct = (
            unrealized_gain / cost_basis * 100 if addable and cost_basis > 0 else
            0.0 if addable else None
        )
        realized = realized_stats.get(ticker, {})
        combined_cost_basis = (cost_basis or 0.0) + float(realized.get("cost_basis") or 0.0)
        combined_gain = (unrealized_gain or 0.0) + float(realized.get("realized_gain") or 0.0)
        total_return_pct = (
            combined_gain / combined_cost_basis * 100
            if addable and combined_cost_basis > 0 else None
        )

        if any(value is not None and not math.isfinite(value) for value in (
            unrealized_gain, unrealized_gain_pct, combined_cost_basis,
            combined_gain, total_return_pct,
        )):
            addable = False
            unrealized_gain = unrealized_gain_pct = total_return_pct = None

        if not is_watchlist and addable:
            total_value += current_value
            total_daily_change += daily_value_change
            total_cost_basis += cost_basis
            if shares > 0:
                priced_tickers.add(ticker)
        elif not is_watchlist and shares > 0 and currency and not _is_reporting_currency(currency):
            foreign_tickers.add(ticker)

        rows.append(
            {
                "ticker": ticker,
                "id": holding.id,
                "name": quote.get("name") or ticker,
                "shares": shares if math.isfinite(shares) else None,
                "current_price": current_price,
                "avg_cost": round(avg_cost, 2) if math.isfinite(avg_cost) else None,
                "current_value": round(current_value, 2) if current_value is not None else None,
                "cost_basis": round(cost_basis, 2) if cost_basis is not None else None,
                "unrealized_gain": round(unrealized_gain, 2) if addable else None,
                "unrealized_gain_pct": round(unrealized_gain_pct, 2) if addable else None,
                "total_return_pct": (
                    round(total_return_pct, 2) if total_return_pct is not None else None
                ),
                "day_change": day_change,
                "day_change_pct": day_change_pct,
                "daily_value_change": (
                    round(daily_value_change, 2) if daily_value_change is not None else None
                ),
                "allocation_pct": 0 if addable else None,
                "currency": currency,
                "quote_available": current_price is not None,
                "reporting_eligible": addable and not is_watchlist,
                "is_watchlist": is_watchlist,
                "hold_class": str(holding.hold_class or "auto"),
                "notes": holding.notes,
                "thesis_reviewed_at": (
                    holding.thesis_reviewed_at.isoformat()
                    if holding.thesis_reviewed_at else None
                ),
                "thesis_review_interval_days": holding.thesis_review_interval_days,
            }
        )

    def counts_toward_totals(row: dict) -> bool:
        """A row is part of the dollar totals only if it is priced in dollars."""
        return financial_currency.eligible_valuation_row(row)

    require_finite_amounts(total_value, total_daily_change, total_cost_basis)

    for row in rows:
        if total_value > 0 and counts_toward_totals(row):
            row["allocation_pct"] = round(row["current_value"] / total_value * 100, 1)

    expected_tickers = {
        str(holding.ticker)
        for holding in holdings
        if not holding.is_watchlist and float(holding.shares or 0.0) > 0
    }
    foreign_currency_tickers = tuple(sorted(foreign_tickers & expected_tickers))
    # Both reasons leave a position out of the totals, so both bear on quality;
    # they are reported apart only so the UI can say which one applies.
    unpriced_tickers = expected_tickers - priced_tickers
    missing_tickers = tuple(sorted(unpriced_tickers - foreign_tickers))
    if not expected_tickers or not unpriced_tickers:
        data_quality = "complete"
    elif priced_tickers:
        data_quality = "partial"
    else:
        data_quality = "unavailable"
    if excluded_realized_trade_count and data_quality == "complete":
        data_quality = "partial"

    total_unrealized_gain = round(
        sum(row["unrealized_gain"] for row in rows if counts_toward_totals(row)),
        2,
    )
    realized_gain = _realized_gain(db, portfolio_id)
    realized_cost_basis = round(
        sum(float(item.get("cost_basis") or 0.0) for item in realized_stats.values()),
        2,
    )
    total_return_cost_basis = round(total_cost_basis + realized_cost_basis, 2)
    total_return = round(total_unrealized_gain + realized_gain, 2)
    total_return_pct = (
        total_return / total_return_cost_basis * 100 if total_return_cost_basis > 0 else 0.0
    )
    require_finite_amounts(
        total_unrealized_gain, realized_gain, realized_cost_basis,
        total_return_cost_basis, total_return, total_return_pct,
    )
    valuation = PortfolioValuation(
        portfolio_id=portfolio_id,
        holdings=rows,
        total_value=round(total_value, 2),
        total_daily_change=round(total_daily_change, 2),
        total_cost_basis=round(total_cost_basis, 2),
        total_return_cost_basis=total_return_cost_basis,
        total_unrealized_gain=total_unrealized_gain,
        realized_gain=realized_gain,
        total_return=total_return,
        total_return_pct=round(total_return_pct, 2),
        data_quality=data_quality,
        missing_tickers=missing_tickers,
        foreign_currency_tickers=foreign_currency_tickers,
        excluded_realized_trade_count=excluded_realized_trade_count,
        realized_data_quality=realized_data_quality,
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
    trade_limit: int | None = 100,
) -> PortfolioPerformance:
    """Load stored realized returns and daily history without fetching quotes."""
    realized_stats = _realized_stats(db, portfolio_id)
    excluded_realized_trade_count = _excluded_realized_trade_count(db, portfolio_id)
    realized_data_quality = (
        "partial" if excluded_realized_trade_count else "complete"
    )
    trades = (
        db.query(RealizedTrade)
        .filter(
            RealizedTrade.portfolio_id == portfolio_id,
            financial_currency.trusted_reporting_fact_clause(
                RealizedTrade.sale_currency,
                RealizedTrade.sale_price_source,
            ),
        )
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
    for snapshot in snapshots:
        require_finite_amounts(
            float(snapshot.total_value or 0.0), float(snapshot.total_cost_basis or 0.0),
            float(snapshot.unrealized_gain or 0.0), float(snapshot.realized_gain or 0.0),
            float(snapshot.total_return or 0.0),
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
                "sale_currency": str(trade.sale_currency),
                "sale_price_source": str(trade.sale_price_source),
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
        history=[] if excluded_realized_trade_count else [
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
        excluded_realized_trade_count=excluded_realized_trade_count,
        realized_data_quality=realized_data_quality,
    )


def snapshot_history(db: Session, portfolio_id: int) -> list[dict]:
    """Return stored daily values for analytics that do not need the trade ledger."""
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )
    require_finite_amounts(*(float(snapshot.total_value or 0.0) for snapshot in snapshots))
    return [
        {
            "date": snapshot.snapshot_date,
            "total_value": float(snapshot.total_value or 0.0),
        }
        for snapshot in snapshots
    ]
