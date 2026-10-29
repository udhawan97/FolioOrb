"""
Fund fee drag — what the funds in a portfolio cost per year, and over time.

No network calls: reads the expense ratio already carried on each quote
(`stock_service.get_stock_data` → ``expense_ratio``). A fund whose ratio is
missing, zero, or implausible is reported as fee-unknown rather than free, and
individual stocks are excluded from coverage entirely — they have no ratio to
be missing.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from app.services import financial_currency
from app.services.security_type import SecurityType, classify_security

# Expense ratios are decimals here (0.0003 = 3bps), matching etf_quality's idiom.
# Above this, the number is a provider glitch (usually a percent that was never
# divided by 100), not a fund anyone sells — refuse to price a fee from it.
MAX_PLAUSIBLE_EXPENSE_RATIO = 0.05

# The long-horizon view needs *some* growth assumption to compound a fee against.
# This one is an assumption, not a forecast, and every payload says so.
DEFAULT_GROWTH_RATE = 0.07

_ASSUMPTION_NOTE = (
    "Long-horizon fees assume the balance grows at a constant {pct}% a year with "
    "no contributions, no rebalancing, and today's expense ratio held flat. The "
    "cost shown is the gap between growing at {pct}% and growing at {pct}% minus "
    "the fee — so it includes the returns the fee itself never earned. It is an "
    "illustration of drag, not a prediction of returns."
)


def _expense_ratio(data: Mapping[str, Any]) -> float | None:
    for key in ("expense_ratio", "expenseRatio", "annualReportExpenseRatio"):
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _horizon_fee(value: float, expense_ratio: float, years: int, growth_rate: float) -> float:
    """Fees paid over `years`, charged against a balance compounding at `growth_rate`.

    Gross growth minus growth net of the fee, so the answer also carries the
    compounding the paid fees never got to do. At years=1 it reduces to
    value × expense_ratio.
    """
    if years <= 0 or expense_ratio <= 0 or value <= 0:
        return 0.0
    gross = (1 + growth_rate) ** years
    net = (1 + growth_rate - expense_ratio) ** years
    return value * (gross - net)


def _fee_rows(holdings_with_data: list[dict]) -> tuple[list[dict], list[dict], dict[str, int]]:
    """Split holdings into priced fund rows, uncovered funds, and excluded counts."""
    priced: list[dict] = []
    uncovered: list[dict] = []
    counts = {"stock": 0, "other": 0}

    for item in holdings_with_data:
        if item.get("is_watchlist"):
            continue
        ticker = str(item.get("ticker") or "").upper()
        if not ticker:
            continue
        kind = classify_security(ticker, item)
        if kind is not SecurityType.ETF:
            counts["stock" if kind is SecurityType.STOCK else "other"] += 1
            continue

        if not financial_currency.eligible_valuation_row(item):
            uncovered.append({"ticker": ticker, "value": None, "reason": "price_or_currency"})
            continue
        value = float(item.get("current_value") or 0.0)
        expense_ratio = _expense_ratio(item)
        # None means the provider had nothing. A real 0.0 means a free fund, and
        # stock_service._normalized_expense_ratio preserves that distinction —
        # so zero is priced as zero rather than written off as unknown.
        if expense_ratio is None:
            uncovered.append({"ticker": ticker, "value": value, "reason": "no_data"})
        elif (
            # NaN is truthy and fails every comparison, so it must be caught by
            # name or it reaches the fee math and poisons the totals.
            not math.isfinite(expense_ratio)
            or expense_ratio < 0
            or expense_ratio > MAX_PLAUSIBLE_EXPENSE_RATIO
        ):
            uncovered.append({"ticker": ticker, "value": value, "reason": "implausible"})
        else:
            priced.append({
                "ticker": ticker,
                "value": round(value, 2),
                "expense_ratio": expense_ratio,
                "expense_ratio_bps": round(expense_ratio * 10000),
                "annual_fee": round(value * expense_ratio, 2),
            })

    priced.sort(key=lambda row: row["annual_fee"], reverse=True)
    uncovered.sort(key=lambda row: row["ticker"])
    return priced, uncovered, counts


def _flags(uncovered: list[dict]) -> list[str]:
    flags = [
        f"{row['ticker']} reported an implausible expense ratio — ignored as bad data"
        for row in uncovered
        if row["reason"] == "implausible"
    ]
    no_data = [row["ticker"] for row in uncovered if row["reason"] == "no_data"]
    if no_data:
        flags.append(
            f"Expense ratio unavailable for {', '.join(no_data)} — "
            "their fees are not counted here"
        )
    unpriced = [row["ticker"] for row in uncovered if row["reason"] == "price_or_currency"]
    if unpriced:
        flags.append(
            f"No usable USD valuation for {', '.join(unpriced)} — their fees are not counted here"
        )
    return flags


def compute_fee_drag(
    holdings_with_data: list[dict],
    *,
    horizon_years: int = 10,
    growth_rate: float = DEFAULT_GROWTH_RATE,
) -> dict[str, Any]:
    """Annual and long-horizon fee cost for the fund positions in a portfolio."""
    priced, uncovered, excluded = _fee_rows(holdings_with_data)
    years = max(0, int(horizon_years))

    for row in priced:
        row["horizon_fee"] = round(
            _horizon_fee(row["value"], row["expense_ratio"], years, growth_rate), 2
        )

    covered_value = sum(row["value"] for row in priced)
    annual_fee_cost = sum(row["annual_fee"] for row in priced)
    horizon_fee_cost = sum(row["horizon_fee"] for row in priced)
    uncovered_value = sum(row["value"] or 0.0 for row in uncovered)
    blended = annual_fee_cost / covered_value if covered_value > 0 else None
    fund_count = len(priced) + len(uncovered)

    if not uncovered:
        data_quality = "complete"
    elif priced:
        data_quality = "partial"
    else:
        data_quality = "unavailable"

    return {
        "has_data": bool(priced),
        "horizon_years": years,
        "annual_fee_cost": round(annual_fee_cost, 2),
        "horizon_fee_cost": round(horizon_fee_cost, 2),
        "blended_expense_ratio": round(blended, 6) if blended is not None else None,
        "blended_expense_ratio_bps": round(blended * 10000) if blended is not None else None,
        "covered_value": round(covered_value, 2),
        "holdings": priced,
        "assumptions": {
            "annual_growth_rate": growth_rate,
            "method": "gross_minus_net_compounding",
            "note": _ASSUMPTION_NOTE.format(pct=round(growth_rate * 100, 2)),
        },
        "coverage": {
            "fund_count": fund_count,
            "covered_count": len(priced),
            "uncovered_count": len(uncovered),
            "uncovered_tickers": [row["ticker"] for row in uncovered],
            "uncovered_value": round(uncovered_value, 2),
            "stock_count": excluded["stock"],
            "other_count": excluded["other"],
        },
        "flags": _flags(uncovered),
        "data_quality": data_quality,
    }
