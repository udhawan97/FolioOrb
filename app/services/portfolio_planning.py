"""Read-only planning and portfolio-overview contracts.

Targets are persisted intent; actual allocation is always recomputed from the
same USD-only valuation contract as the dashboard. Rehearsals clone the current
facts in memory and never write a holding or a daily snapshot.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Callable

from sqlalchemy.orm import Session

from app.models import Holding
from app.services import portfolio_lifecycle, portfolio_valuation
from app.services.dca_service import apply_to_holding
from app.services.stock_service import get_portfolio_quotes

QuoteLoader = Callable[[list[str]], list[dict]]
TARGET_TOTAL_BPS = 10_000
MAX_REHEARSAL_CASH = Decimal("100000000.00")


def _eligible_holdings(db: Session, portfolio_id: int) -> list[Holding]:
    """Active owned positions eligible for targets, in stable insertion order."""
    return (
        db.query(Holding)
        .filter(
            Holding.portfolio_id == portfolio_id,
            Holding.is_active.is_(True),
            Holding.is_watchlist.is_(False),
            Holding.shares > 0,
        )
        .order_by(Holding.id.asc())
        .all()
    )


def _valid_target(value) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= TARGET_TOTAL_BPS
    )


def target_snapshot(db: Session, portfolio_id: int) -> dict:
    """Return persisted target state without loading market data."""
    holdings = _eligible_holdings(db, portfolio_id)
    targets = [holding.target_weight_bps for holding in holdings]
    values_valid = all(value is None or _valid_target(value) for value in targets)
    assigned = [value for value in targets if _valid_target(value)]
    total = sum(assigned)
    complete = bool(holdings) and values_valid and len(assigned) == len(holdings)
    complete = complete and total == TARGET_TOTAL_BPS
    return {
        "portfolio_id": portfolio_id,
        "complete": complete,
        "eligible_count": len(holdings),
        "assigned_count": len(assigned),
        "target_total_bps": total,
        "remaining_bps": TARGET_TOTAL_BPS - total,
        "items": [
            {
                "holding_id": holding.id,
                "ticker": str(holding.ticker),
                "target_weight_bps": (
                    holding.target_weight_bps
                    if _valid_target(holding.target_weight_bps)
                    else None
                ),
            }
            for holding in holdings
        ],
    }


def replace_targets(
    db: Session,
    portfolio_id: int,
    assignments: list[tuple[int, int | None]],
) -> dict:
    """Atomically replace every eligible position's target-weight draft."""
    ids = [holding_id for holding_id, _value in assignments]
    if len(ids) != len(set(ids)):
        raise ValueError("Each eligible holding may appear only once")

    eligible = _eligible_holdings(db, portfolio_id)
    by_id = {holding.id: holding for holding in eligible}
    if set(ids) != set(by_id):
        raise ValueError("Targets must include every eligible holding in this portfolio")

    for _holding_id, value in assignments:
        if value is not None and not _valid_target(value):
            raise ValueError("Target weights must be whole basis points from 0 to 10,000")
    assigned_total = sum(value for _holding_id, value in assignments if value is not None)
    if assigned_total > TARGET_TOTAL_BPS:
        raise ValueError("Target weights cannot total more than 10,000 basis points")

    try:
        for holding_id, value in assignments:
            by_id[holding_id].target_weight_bps = value
        db.commit()
    except Exception:
        db.rollback()
        raise
    return target_snapshot(db, portfolio_id)


def build_target_plan(
    db: Session,
    portfolio_id: int,
    *,
    quote_loader: QuoteLoader | None = None,
) -> dict:
    """Join saved targets to current USD allocation without recording history."""
    target = target_snapshot(db, portfolio_id)
    valuation = portfolio_valuation.evaluate(
        db,
        portfolio_id,
        quote_loader=quote_loader,
        record_snapshot=False,
    )
    rows_by_id = {int(row["id"]): row for row in valuation.holdings}
    usable = (
        target["complete"]
        and valuation.data_quality == "complete"
        and valuation.total_value > 0
    )
    items = []
    for item in target["items"]:
        row = rows_by_id.get(item["holding_id"])
        actual_bps = None
        if row and valuation.data_quality == "complete" and valuation.total_value > 0:
            actual_bps = round(
                float(row["current_value"]) / valuation.total_value * TARGET_TOTAL_BPS
            )
        target_bps = item["target_weight_bps"]
        drift_bps = actual_bps - target_bps if usable and target_bps is not None else None
        items.append({
            **item,
            "actual_weight_bps": actual_bps,
            "drift_bps": drift_bps,
            "drift_direction": (
                None if drift_bps is None else
                "above" if drift_bps > 0 else
                "below" if drift_bps < 0 else "on_target"
            ),
        })

    return {
        **target,
        "reporting_currency": portfolio_valuation.REPORTING_CURRENCY,
        "known_value": valuation.total_value,
        "valuation_quality": valuation.data_quality,
        "missing_tickers": list(valuation.missing_tickers),
        "foreign_currency_tickers": list(valuation.foreign_currency_tickers),
        "drift_available": usable,
        "items": items,
    }


def _cash_amount(value: Decimal) -> Decimal:
    amount = Decimal(value)
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Cash must be a positive finite USD amount")
    if amount.as_tuple().exponent < -2:
        raise ValueError("Cash may have at most two decimal places")
    if amount > MAX_REHEARSAL_CASH:
        raise ValueError("Cash exceeds the $100,000,000 rehearsal limit")
    return amount


def rehearse_buy(
    db: Session,
    portfolio_id: int,
    holding_id: int,
    cash: Decimal,
    *,
    quote_loader: QuoteLoader | None = None,
) -> dict:
    """Preview one fully-spent USD buy using current stored position facts."""
    amount = _cash_amount(cash)
    eligible = {holding.id: holding for holding in _eligible_holdings(db, portfolio_id)}
    holding = eligible.get(holding_id)
    if holding is None:
        raise ValueError("Buy rehearsals require an active held position in this portfolio")

    valuation = portfolio_valuation.evaluate(
        db,
        portfolio_id,
        quote_loader=quote_loader,
        record_snapshot=False,
    )
    row = next(
        (item for item in valuation.holdings if int(item["id"]) == holding_id),
        None,
    )
    if row is None or str(row.get("currency") or "").upper() != "USD":
        raise ValueError("An available USD quote is required for this rehearsal")
    price = float(row.get("current_price") or 0.0)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("An available USD quote is required for this rehearsal")

    cash_float = float(amount)
    buy_shares = cash_float / price
    new_shares, new_avg = apply_to_holding(
        float(holding.shares or 0.0),
        float(holding.avg_cost or 0.0),
        buy_shares,
        cash_float,
    )
    allocation_available = valuation.data_quality == "complete" and valuation.total_value > 0
    selected_allocation = None
    largest_allocation = None
    projected_known_value = None
    if allocation_available:
        projected_known_value = valuation.total_value + cash_float
        projected_values = [
            float(item["current_value"]) + (cash_float if int(item["id"]) == holding_id else 0.0)
            for item in valuation.holdings
            if not item["is_watchlist"] and str(item["currency"]).upper() == "USD"
        ]
        selected_value = float(row["current_value"]) + cash_float
        selected_allocation = round(selected_value / projected_known_value * 100, 2)
        largest_allocation = round(max(projected_values) / projected_known_value * 100, 2)

    return {
        "portfolio_id": portfolio_id,
        "holding_id": holding_id,
        "ticker": str(holding.ticker),
        "cash_usd": float(amount),
        "available_quote_usd": price,
        "quote_freshness": "unknown",
        "buy_shares": round(buy_shares, 8),
        "current_shares": round(float(holding.shares or 0.0), 8),
        "projected_shares": round(new_shares, 8),
        "current_avg_cost_usd": round(float(holding.avg_cost or 0.0), 4),
        "projected_avg_cost_usd": round(new_avg, 4),
        "projected_known_value_usd": (
            round(projected_known_value, 2) if projected_known_value is not None else None
        ),
        "projected_selected_allocation_pct": selected_allocation,
        "projected_largest_position_pct": largest_allocation,
        "allocation_available": allocation_available,
        "valuation_quality": valuation.data_quality,
        "missing_tickers": list(valuation.missing_tickers),
        "foreign_currency_tickers": list(valuation.foreign_currency_tickers),
        "assumptions": [
            "The entered external USD cash is fully spent at the available quote.",
            "Fractional shares are allowed.",
            "Fees and taxes are excluded.",
            "This rehearsal does not write holdings, snapshots, or orders.",
        ],
    }


def build_all_books_overview(
    db: Session,
    *,
    quote_loader: QuoteLoader | None = None,
) -> dict:
    """Value every saved portfolio independently and aggregate known USD only."""
    base_loader = quote_loader or get_portfolio_quotes
    cache: dict[str, dict] = {}

    def cached_quotes(tickers: list[str]) -> list[dict]:
        missing = [ticker for ticker in tickers if ticker not in cache]
        if missing:
            loaded = base_loader(missing)
            cache.update({str(row.get("ticker") or ""): row for row in loaded})
            for ticker in missing:
                cache.setdefault(ticker, {"ticker": ticker, "error": "unavailable"})
        return [cache[ticker] for ticker in tickers]

    items = []
    for portfolio in portfolio_lifecycle.list_portfolios(db):
        try:
            valuation = portfolio_valuation.evaluate(
                db,
                portfolio.id,
                quote_loader=cached_quotes,
                record_snapshot=False,
            )
            quality = (
                "empty" if valuation.expected_position_count == 0 else valuation.data_quality
            )
            items.append({
                "portfolio_id": portfolio.id,
                "name": str(portfolio.name),
                "known_value_usd": valuation.total_value,
                "data_quality": quality,
                "expected_position_count": valuation.expected_position_count,
                "priced_position_count": valuation.priced_position_count,
                "missing_tickers": list(valuation.missing_tickers),
                "foreign_currency_tickers": list(valuation.foreign_currency_tickers),
                "error": None,
            })
        except Exception as exc:  # pylint: disable=broad-except
            items.append({
                "portfolio_id": portfolio.id,
                "name": str(portfolio.name),
                "known_value_usd": None,
                "data_quality": "unavailable",
                "expected_position_count": None,
                "priced_position_count": None,
                "missing_tickers": [],
                "foreign_currency_tickers": [],
                "error": type(exc).__name__,
            })

    known_total = round(sum(item["known_value_usd"] or 0.0 for item in items), 2)
    successful = [item for item in items if item["error"] is None]
    all_complete = all(item["data_quality"] in {"complete", "empty"} for item in items)
    quality = "complete" if all_complete else "partial" if successful else "unavailable"
    return {
        "reporting_currency": "USD",
        "known_value_usd": known_total,
        "data_quality": quality,
        "portfolio_count": len(items),
        "items": items,
        "limitations": [
            "Known value includes only positions with available USD quotes.",
            "Foreign-priced positions are listed but not converted or added.",
            "No combined performance percentage is calculated.",
        ],
    }
