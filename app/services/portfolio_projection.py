"""
Portfolio growth projection — avg / best / worst scenarios vs S&P 500.

Uses weighted historical log-returns (3-year lookback) to estimate annualized
return and volatility, then projects geometric growth paths for each horizon.
"""

from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

import numpy as np

from app.services.stock_service import get_historical_prices

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "SPY"
LOOKBACK_PERIOD = "3y"
TRADING_DAYS = 252

HORIZONS: dict[str, dict[str, Any]] = {
    "30d": {"label": "30D", "days": 30, "step_days": 1},
    "1y": {"label": "1Y", "days": 365, "step_days": 7},
    "3y": {"label": "3Y", "days": 365 * 3, "step_days": 30},
    "5y": {"label": "5Y", "days": 365 * 5, "step_days": 30},
    "10y": {"label": "10Y", "days": 365 * 10, "step_days": 30},
}

_cache: dict[str, Any] = {"payload": None, "key": None, "expires_at": 0.0}
_CACHE_TTL_SEC = 300


def _fetch_closes(ticker: str) -> list[tuple[str, float]]:
    rows = get_historical_prices(ticker, LOOKBACK_PERIOD)
    return [(r["date"], float(r["close"])) for r in rows if r.get("close", 0) > 0]


def _log_returns(closes: list[float]) -> np.ndarray:
    if len(closes) < 2:
        return np.array([], dtype=float)
    prices = np.asarray(closes, dtype=float)
    return np.diff(np.log(prices))


def _annualize_stats(daily_log_returns: np.ndarray) -> tuple[float, float]:
    if daily_log_returns.size < 5:
        return 0.08, 0.15
    mu = float(np.mean(daily_log_returns)) * TRADING_DAYS
    sigma = float(np.std(daily_log_returns, ddof=1)) * math.sqrt(TRADING_DAYS)
    return mu, max(sigma, 0.05)


def _portfolio_daily_returns(
    holdings: list[tuple[str, float, list[tuple[str, float]]]],
) -> np.ndarray:
    """
    holdings: [(ticker, weight, [(date, close), ...]), ...]
    Returns aligned weighted daily log-returns.
    """
    active = [(t, w, s) for t, w, s in holdings if w > 0 and len(s) >= 2]
    if not active:
        return np.array([], dtype=float)

    all_dates: set[str] = set()
    for _t, _w, series in active:
        for d, _c in series:
            all_dates.add(d)
    dates = sorted(all_dates)
    if len(dates) < 2:
        return np.array([], dtype=float)

    date_idx = {d: i for i, d in enumerate(dates)}
    n = len(dates)
    port_rets = np.zeros(n - 1, dtype=float)
    total_weight = sum(w for _t, w, _s in active)

    for _ticker, weight, series in active:
        closes = np.full(n, np.nan)
        for d, c in series:
            if d in date_idx:
                closes[date_idx[d]] = c
        for i in range(1, n):
            if np.isnan(closes[i]):
                closes[i] = closes[i - 1]
        if np.isnan(closes[0]):
            valid = np.where(~np.isnan(closes))[0]
            if valid.size:
                closes[: valid[0]] = closes[valid[0]]
        if np.any(np.isnan(closes)) or np.any(closes <= 0):
            continue
        port_rets += (weight / total_weight) * np.diff(np.log(closes))

    return port_rets


def _growth_path(
    start_value: float,
    mu: float,
    sigma: float,
    horizon_days: int,
    step_days: int,
    scenario: str,
) -> list[dict[str, Any]]:
    if start_value <= 0:
        return []

    drift_adj = {"avg": 0.0, "best": sigma, "worst": -sigma}.get(scenario, 0.0)
    adj_mu = mu + drift_adj

    offsets = list(range(0, horizon_days + 1, max(step_days, 1)))
    if offsets[-1] != horizon_days:
        offsets.append(horizon_days)

    start = date.today()
    return [
        {
            "offset_days": offset,
            "date": (start + timedelta(days=offset)).isoformat(),
            "value": round(start_value * math.exp(adj_mu * (offset / 365.0)), 2),
        }
        for offset in offsets
    ]


def _end_summary(paths: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    return {key: (pts[-1]["value"] if pts else 0.0) for key, pts in paths.items()}


def _index_paths(paths: dict[str, list[dict[str, Any]]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for sc, pts in paths.items():
        if not pts:
            out[sc] = []
            continue
        start = pts[0]["value"]
        out[sc] = [
            round((p["value"] / start) * 100, 2) if start else 100.0 for p in pts
        ]
    return out


def compute_portfolio_projection(
    holdings: list[dict[str, Any]],
    total_value: float,
) -> dict[str, Any]:
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and (h.get("current_value") or 0) > 0
    ]

    tickers = [h["ticker"] for h in active]
    fetch_list = list(dict.fromkeys(tickers + [BENCHMARK_TICKER]))

    with ThreadPoolExecutor(max_workers=min(8, max(len(fetch_list), 1))) as pool:
        history_map = dict(pool.map(lambda t: (t, _fetch_closes(t)), fetch_list))

    spy_closes = [c for _d, c in history_map.get(BENCHMARK_TICKER, [])]
    spy_mu, spy_sigma = _annualize_stats(_log_returns(spy_closes))

    weighted_rows = [
        (h["ticker"], h["current_value"], history_map.get(h["ticker"], []))
        for h in active
    ]
    port_mu, port_sigma = _annualize_stats(_portfolio_daily_returns(weighted_rows))

    base_value = total_value if total_value > 0 else 100_000.0
    has_holdings = total_value > 0 and bool(active)

    horizons_out: dict[str, Any] = {}
    for key, cfg in HORIZONS.items():
        port_paths = {
            sc: _growth_path(base_value, port_mu, port_sigma, cfg["days"], cfg["step_days"], sc)
            for sc in ("avg", "best", "worst")
        }
        spy_paths = {
            sc: _growth_path(base_value, spy_mu, spy_sigma, cfg["days"], cfg["step_days"], sc)
            for sc in ("avg", "best", "worst")
        }
        labels = [p["date"] for p in port_paths["avg"]] if port_paths["avg"] else []

        horizons_out[key] = {
            "label": cfg["label"],
            "days": cfg["days"],
            "labels": labels,
            "portfolio": {
                "values": port_paths,
                "indexed": _index_paths(port_paths),
                "end": _end_summary(port_paths),
            },
            "sp500": {
                "values": spy_paths,
                "indexed": _index_paths(spy_paths),
                "end": _end_summary(spy_paths),
            },
        }

    return {
        "current_value": round(total_value, 2),
        "has_holdings": has_holdings,
        "benchmark": "S&P 500 (SPY)",
        "lookback": LOOKBACK_PERIOD,
        "metrics": {
            "portfolio": {
                "annual_return_pct": round(port_mu * 100, 2),
                "annual_vol_pct": round(port_sigma * 100, 2),
            },
            "sp500": {
                "annual_return_pct": round(spy_mu * 100, 2),
                "annual_vol_pct": round(spy_sigma * 100, 2),
            },
        },
        "horizons": horizons_out,
        "disclaimer": (
            "Projections use 3-year historical returns and volatility. "
            "Not financial advice — actual results will differ."
        ),
    }


def get_cached_projection(
    holdings: list[dict[str, Any]],
    total_value: float,
) -> dict[str, Any]:
    now = time.time()
    cache_key = (
        f"{round(total_value, 2)}:"
        f"{','.join(sorted(h['ticker'] for h in holdings if not h.get('is_watchlist')))}"
    )
    cached = _cache.get("payload")
    if cached and _cache.get("key") == cache_key and now < _cache.get("expires_at", 0):
        return {**cached, "cached": True}

    payload = compute_portfolio_projection(holdings, total_value)
    payload["cached"] = False
    _cache.update({"payload": payload, "key": cache_key, "expires_at": now + _CACHE_TTL_SEC})
    return payload
