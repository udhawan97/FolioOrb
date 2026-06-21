"""
ETF price-zone signal from current price and historical yfinance data.

This is intentionally price-history based rather than analyst-target based:
ETFs rarely have useful target prices, but yfinance reliably exposes quote
history and common moving-average/range fields for most funds.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


def _first_number(data: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _clean_numbers(values: Iterable[Any]) -> list[float]:
    cleaned: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            cleaned.append(number)
    return cleaned


def history_closes(history: Any) -> list[float]:
    """Extract valid close prices from a yfinance history DataFrame-like object."""
    if history is None:
        return []
    try:
        if bool(getattr(history, "empty", False)):
            return []
        close_series = history["Close"]
        if hasattr(close_series, "dropna"):
            close_series = close_series.dropna()
        values = close_series.tolist() if hasattr(close_series, "tolist") else list(close_series)
    except Exception:
        return []
    return _clean_numbers(values)


def _label_from_percentile(percentile: float | None) -> str:
    if percentile is None:
        return "Unavailable"
    if percentile <= 25:
        return "Bargain"
    if percentile <= 60:
        return "Fair"
    if percentile <= 80:
        return "Elevated"
    return "Rich"


def _pct(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 1)


def calculate_etf_price_signal(
    etf_data: Mapping[str, Any],
    closes: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """
    Return a compact price-zone signal for ETF table display.

    Primary signal: current price percentile against the last year of closes.
    Fallback signal: current position inside the 52-week range.
    """
    data = dict(etf_data)
    close_values = _clean_numbers(closes if closes is not None else [])
    current = _first_number(
        data, "current_price", "currentPrice", "regularMarketPrice", "navPrice", "previousClose"
    )
    if current is None and close_values:
        current = close_values[-1]

    low_52 = _first_number(data, "fiftyTwoWeekLow", "fifty_two_week_low")
    high_52 = _first_number(data, "fiftyTwoWeekHigh", "fifty_two_week_high")
    if (low_52 is None or high_52 is None) and close_values:
        low_52 = low_52 or min(close_values)
        high_52 = high_52 or max(close_values)

    percentile: float | None = None
    basis = "Unavailable"
    if current is not None and len(close_values) >= 20:
        percentile = round(
            sum(1 for close in close_values if close <= current) / len(close_values) * 100,
            1,
        )
        basis = "1Y percentile"
    elif current is not None and low_52 is not None and high_52 is not None and high_52 > low_52:
        percentile = round(max(0, min(100, (current - low_52) / (high_52 - low_52) * 100)), 1)
        basis = "52W range"

    range_position = None
    if current is not None and low_52 is not None and high_52 is not None and high_52 > low_52:
        range_position = round(max(0, min(100, (current - low_52) / (high_52 - low_52) * 100)), 1)

    ma_200 = _first_number(data, "twoHundredDayAverage", "two_hundred_day_average")
    if ma_200 is None and len(close_values) >= 200:
        ma_200 = sum(close_values[-200:]) / 200
    ma_50 = _first_number(data, "fiftyDayAverage", "fifty_day_average")
    if ma_50 is None and len(close_values) >= 50:
        ma_50 = sum(close_values[-50:]) / 50

    vs_200d = _pct((current - ma_200), ma_200) if current is not None and ma_200 else None
    vs_50d = _pct((current - ma_50), ma_50) if current is not None and ma_50 else None
    label = _label_from_percentile(percentile)

    missing_fields = []
    if current is None:
        missing_fields.append("currentPrice")
    if not close_values:
        missing_fields.append("history")
    if low_52 is None or high_52 is None:
        missing_fields.append("fiftyTwoWeekRange")
    if ma_200 is None:
        missing_fields.append("twoHundredDayAverage")

    return {
        "priceZoneLabel": label,
        "percentile": percentile,
        "rangePositionPct": range_position,
        "vs200dPct": vs_200d,
        "vs50dPct": vs_50d,
        "basis": basis,
        "source": "yfinance",
        "missingFields": missing_fields,
    }


def fetch_etf_price_signal(ticker: str, info: Mapping[str, Any], stock: Any) -> dict[str, Any]:
    """Fetch yfinance history defensively, then calculate the ETF price-zone signal."""
    closes: list[float] = []
    try:
        history = stock.history(period="1y", auto_adjust=True)
        closes = history_closes(history)
    except Exception:
        closes = []
    return calculate_etf_price_signal({"ticker": ticker, **dict(info)}, closes)
