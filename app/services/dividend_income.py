"""
Portfolio dividend income — what your holdings pay *you* back.

Reads the forward dividend rate ($/share) already normalized onto each quote by
``stock_service`` and turns it into annual cash at your position size. Non-payers
(most growth stocks) are named, never counted as $0 income dressed up as
coverage. A per-share dividend larger than the share price is rejected as bad
data rather than trusted.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# A dividend can't exceed the share price in a year; beyond this it's bad data.
_MAX_PLAUSIBLE_YIELD = 1.0  # 100%


def _rate(row: Mapping[str, Any]) -> float | None:
    value = row.get("dividend_rate")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number > 0 else None


def compute_portfolio_income(holdings_with_data: list[dict]) -> dict:
    """Annual dividend income and yield for a portfolio's paying holdings."""
    payers: list[dict] = []
    non_payers: list[str] = []
    total_value = 0.0

    for item in holdings_with_data:
        if item.get("is_watchlist"):
            continue
        ticker = str(item.get("ticker") or "").upper()
        if not ticker:
            continue

        value = float(item.get("current_value") or 0.0)
        total_value += value
        shares = float(item.get("shares") or 0.0)
        rate = _rate(item)
        price = value / shares if shares > 0 else None

        # No rate, no shares, or an implausible rate (> share price) → not a payer.
        if rate is None or shares <= 0 or (price is not None and rate > price):
            non_payers.append(ticker)
            continue

        income = round(shares * rate, 2)
        ex_date = item.get("ex_dividend_date")
        payers.append({
            "ticker": ticker,
            "value": round(value, 2),
            "shares": shares,
            "dividend_rate": rate,
            "yield": round(rate / price, 5) if price else None,
            "annual_income": income,
            "ex_dividend_date": ex_date if isinstance(ex_date, str) else None,
        })

    payers.sort(key=lambda p: p["annual_income"], reverse=True)
    total_income = round(sum(p["annual_income"] for p in payers), 2)
    portfolio_yield = (
        round(total_income / total_value, 5) if payers and total_value > 0 else None
    )

    return {
        "has_data": bool(payers),
        "total_annual_income": total_income,
        "portfolio_yield": portfolio_yield,
        "covered_value": round(sum(p["value"] for p in payers), 2),
        "payers": payers,
        "coverage": {
            "payer_count": len(payers),
            "non_payer_count": len(non_payers),
            "non_payers": non_payers,
        },
        "data_quality": "live",
    }
