"""
Timing signal helpers for Folio Sense verdicts.

The module is deterministic after price history is supplied. yfinance history
fetches are batched, de-duped, and cached by ticker for the current calendar day.
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Iterable, Mapping

import yfinance as yf

from app.services.etf_price_signal import history_closes

logger = logging.getLogger(__name__)

_HISTORY_CACHE: dict[tuple[str, str, str], list[float]] = {}


def _safe_log_value(value: Any) -> str:
    """Prevent log forging by removing line breaks from untrusted values."""
    return str(value).replace("\r", "").replace("\n", "")


def _num(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(number) and number > 0:
        return number
    return None


def _clean(values: Iterable[Any] | None) -> list[float]:
    cleaned: list[float] = []
    for value in values or []:
        number = _num(value)
        if number is not None:
            cleaned.append(number)
    return cleaned


def _pct(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _sma_at(values: list[float], window: int, end_index: int) -> float | None:
    if end_index + 1 < window:
        return None
    window_values = values[end_index - window + 1:end_index + 1]
    return sum(window_values) / window


def _latest_cross(values: list[float]) -> dict | None:
    if len(values) < 201:
        return None

    last_cross: dict | None = None
    prev_diff: float | None = None
    for idx in range(199, len(values)):
        ma50 = _sma_at(values, 50, idx)
        ma200 = _sma_at(values, 200, idx)
        if ma50 is None or ma200 is None:
            continue
        diff = ma50 - ma200
        if prev_diff is not None:
            cross_type = None
            if prev_diff <= 0 < diff:
                cross_type = "golden"
            elif prev_diff >= 0 > diff:
                cross_type = "death"
            if cross_type:
                last_cross = {
                    "type": cross_type,
                    "sessions_ago": len(values) - 1 - idx,
                    "recent": len(values) - 1 - idx <= 20,
                }
        prev_diff = diff
    return last_cross


def _slope(values: list[float], window: int = 50, lookback: int = 10) -> tuple[str, float | None]:
    if len(values) < window + lookback:
        return "unknown", None
    now = _sma_at(values, window, len(values) - 1)
    then = _sma_at(values, window, len(values) - 1 - lookback)
    if now is None or then is None or then <= 0:
        return "unknown", None
    slope_pct = round((now - then) / then * 100, 2)
    if slope_pct >= 0.5:
        return "rising", slope_pct
    if slope_pct <= -0.5:
        return "falling", slope_pct
    return "flattening", slope_pct


def _change(values: list[float], days: int, end_index: int) -> float | None:
    start = end_index - days
    if start < 0 or end_index >= len(values) or values[start] <= 0:
        return None
    return (values[end_index] - values[start]) / values[start] * 100


def _momentum_state(values: list[float], current: float, ma200: float | None) -> tuple[str, str]:
    slope_label, _slope_pct = _slope(values)
    recent = _change(values, 10, len(values) - 1)
    prior = _change(values, 10, len(values) - 11) if len(values) >= 21 else None
    decelerating = recent is not None and prior is not None and recent < prior - 2.0
    above_200 = ma200 is not None and current >= ma200

    if above_200 and slope_label in {"rising", "flattening"} and not decelerating:
        return "trend_intact", slope_label
    if above_200 and (slope_label == "falling" or decelerating):
        return "rolling_over", slope_label
    if not above_200 and slope_label == "rising":
        return "stabilizing", slope_label
    if not above_200 and slope_label == "falling":
        return "weakening", slope_label
    return "neutral", slope_label


def timing_bucket(timing: Mapping[str, Any] | None) -> str:
    """Coarse cache bucket for quips and portfolio signatures."""
    if not timing:
        return "none"
    cross = timing.get("cross") or {}
    if cross.get("recent") and cross.get("type") in {"golden", "death"}:
        return f"{cross['type']}-recent"
    state = timing.get("momentum_state") or "neutral"
    if state in {"trend_intact", "stabilizing", "rolling_over", "weakening"}:
        return state
    if timing.get("near_52w_low"):
        return "near-low"
    return "neutral"


def weakness_flags(timing: Mapping[str, Any] | None, zone: str | None = None) -> list[str]:
    """Return plain machine labels for anchor add-more opportunities."""
    if not timing:
        return []
    flags: list[str] = []
    if zone == "Bargain":
        flags.append("bargain_zone")
    if timing.get("near_52w_low"):
        flags.append("near_52w_low")
    drawdown = timing.get("drawdown_from_52w_high_pct")
    vs50 = timing.get("vs50d_pct")
    vs200 = timing.get("vs200d_pct")
    state = timing.get("momentum_state")
    if (
        drawdown is not None and 5 <= drawdown <= 22
        and vs200 is not None and vs200 >= 0
        and state in {"trend_intact", "stabilizing", "neutral"}
    ):
        flags.append("healthy_pullback")
    if (
        vs50 is not None and vs50 <= -3
        and vs200 is not None and vs200 >= 0
        and state in {"trend_intact", "stabilizing"}
    ):
        flags.append("oversold_uptrend_dip")
    return flags


def build_timing_signal(
    closes: Iterable[Any] | None,
    *,
    current_price: float | None = None,
    high_52w: float | None = None,
    low_52w: float | None = None,
    fallback_ma50: float | None = None,
    fallback_ma200: float | None = None,
) -> dict[str, Any]:
    """Compute moving-average, crossover, momentum, and drawdown timing data."""
    values = _clean(closes)
    current = _num(current_price) or (values[-1] if values else None)
    if current is None:
        return {"available": False, "source": "unavailable"}

    ma50 = _sma(values, 50) or _num(fallback_ma50)
    ma200 = _sma(values, 200) or _num(fallback_ma200)
    hist_high = max(values[-252:]) if values else None
    hist_low = min(values[-252:]) if values else None
    high = _num(high_52w) or hist_high
    low = _num(low_52w) or hist_low

    vs50 = _pct(current - ma50, ma50) if ma50 else None
    vs200 = _pct(current - ma200, ma200) if ma200 else None
    cross = _latest_cross(values)
    momentum_state, slope_label = _momentum_state(values, current, ma200)
    slope_label, slope_pct = _slope(values)

    drawdown = _pct((high or current) - current, high or current)
    near_low = False
    range_position = None
    if high is not None and low is not None and high > low:
        range_position = round(max(0, min(100, (current - low) / (high - low) * 100)), 1)
        near_low = range_position <= 18

    regime = "unknown"
    if ma50 and ma200:
        if current >= ma50 >= ma200:
            regime = "uptrend"
        elif current < ma50 < ma200:
            regime = "downtrend"
        elif current >= ma200:
            regime = "mixed_above_200d"
        else:
            regime = "mixed_below_200d"

    signal = {
        "available": bool(ma50 or ma200 or len(values) >= 20),
        "source": "history" if values else "info_ma_fallback",
        "current_price": round(current, 2),
        "sma50": round(ma50, 2) if ma50 else None,
        "sma200": round(ma200, 2) if ma200 else None,
        "vs50d_pct": vs50,
        "vs200d_pct": vs200,
        "trend_regime": regime,
        "cross": cross,
        "momentum_state": momentum_state,
        "slope50": slope_label,
        "slope50_pct_10d": slope_pct,
        "drawdown_from_52w_high_pct": drawdown,
        "near_52w_low": near_low,
        "range_position_pct": range_position,
        "watch_levels": {
            "fifty_day": round(ma50, 2) if ma50 else None,
            "two_hundred_day": round(ma200, 2) if ma200 else None,
            "fifty_two_week_low": round(low, 2) if low else None,
            "fifty_two_week_high": round(high, 2) if high else None,
        },
    }
    signal["bucket"] = timing_bucket(signal)
    if len(values) >= 2:
        slice_vals = values[-30:]
        base = slice_vals[0]
        if base > 0:
            signal["sparkline_30d"] = [
                round((v / base - 1) * 100, 2) for v in slice_vals
            ]
        else:
            signal["sparkline_30d"] = []
    else:
        signal["sparkline_30d"] = []
    return signal


def _fetch_history_closes(ticker: str, period: str) -> list[float]:
    try:
        stock = yf.Ticker(ticker)
        return history_closes(stock.history(period=period, auto_adjust=True))
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug(
            "Timing history fetch failed for %s; exception_type=%s",
            _safe_log_value(ticker),
            type(exc).__name__,
        )
        return []


def get_cached_history_closes(ticker: str, period: str = "1y") -> list[float]:
    """Return cached daily closes for ticker/period/current day."""
    symbol = ticker.upper()
    key = (symbol, period, date.today().isoformat())
    if key not in _HISTORY_CACHE:
        _HISTORY_CACHE[key] = _fetch_history_closes(symbol, period)
    return list(_HISTORY_CACHE[key])


def get_batched_history_closes(
    tickers: Iterable[str],
    period: str = "1y",
) -> dict[str, list[float]]:
    """Concurrent, de-duped, same-day cached history fetch for verdict scans."""
    symbols = sorted({str(t).upper() for t in tickers if t})
    if not symbols:
        return {}

    today = date.today().isoformat()
    results: dict[str, list[float]] = {}
    missing: list[str] = []
    for symbol in symbols:
        key = (symbol, period, today)
        if key in _HISTORY_CACHE:
            results[symbol] = list(_HISTORY_CACHE[key])
        else:
            missing.append(symbol)

    if missing:
        with ThreadPoolExecutor(max_workers=min(10, len(missing))) as pool:
            futures = {
                pool.submit(_fetch_history_closes, symbol, period): symbol
                for symbol in missing
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    closes = future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug(
                        "Timing history future failed for %s; exception_type=%s",
                        symbol,
                        type(exc).__name__,
                    )
                    closes = []
                _HISTORY_CACHE[(symbol, period, today)] = closes
                results[symbol] = list(closes)

    return results


def clear_history_cache() -> None:
    """Test helper."""
    _HISTORY_CACHE.clear()
