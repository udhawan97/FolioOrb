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

from app.services.returns_math import (
    annualized,
    log_returns as _log_returns,
    weighted_daily_returns as _portfolio_daily_returns,
)
from app.services.stock_service import get_historical_prices

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "SPY"
LOOKBACK_PERIOD = "3y"

# Fallbacks for a history too short to measure: a long-run equity-like drift and
# volatility, so a new or thinly-priced book still projects a plausible cone
# instead of a flat line. The floor keeps `best`/`worst` from collapsing onto
# `avg`, since the scenario spread is one sigma either side of the drift.
_DEFAULT_MU = 0.08
_DEFAULT_SIGMA = 0.15
_MIN_SIGMA = 0.05

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


def _annualize_stats(daily_log_returns: np.ndarray) -> tuple[float, float]:
    """Annualised (drift, volatility) as decimals, with projection defaults."""
    stats = annualized(daily_log_returns)
    if stats is None:
        return _DEFAULT_MU, _DEFAULT_SIGMA
    mu, sigma = stats
    return mu, max(sigma, _MIN_SIGMA)


def _growth_path(  # pylint: disable=too-many-positional-arguments
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


def _build_scenario_why(
    mu: float, sigma: float, sp_mu: float, sp_sigma: float
) -> dict[str, str]:
    port_ret = mu * 100
    port_vol = sigma * 100
    sp_ret = sp_mu * 100

    best_rate = (mu + sigma) * 100
    worst_rate = (mu - sigma) * 100
    diff = abs(port_ret - sp_ret)
    leader = "Portfolio leads" if mu >= sp_mu else "Index leads"

    return {
        "avg": (
            f"Based on your 3-year annualised return of {port_ret:.1f}%. "
            f"No volatility adjustment — pure historical mean compounded forward."
        ),
        "best": (
            f"Applies +1 standard deviation to your return: "
            f"{port_ret:.1f}% + {port_vol:.1f}% vol = {best_rate:.1f}% annualised. "
            f"Occurs roughly 16% of the time."
        ),
        "worst": (
            f"Applies \u22121 standard deviation: "
            f"{port_ret:.1f}% \u2212 {port_vol:.1f}% vol = {worst_rate:.1f}% annualised. "
            f"Also ~16% probable \u2014 rough, but within normal range."
        ),
        "sp500": (
            f"SPY 3-year average: {sp_ret:.1f}% at {sp_sigma * 100:.1f}% volatility. "
            f"{leader} by {diff:.1f}% annually."
        ),
    }


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

    has_holdings = total_value > 0 and bool(active)
    base_value = total_value if has_holdings else 100.0

    horizons_out: dict[str, Any] = {}
    for key, cfg in HORIZONS.items():
        port_paths = (
            {
                sc: _growth_path(
                    base_value, port_mu, port_sigma, cfg["days"], cfg["step_days"], sc
                )
                for sc in ("avg", "best", "worst")
            }
            if has_holdings else
            {"avg": [], "best": [], "worst": []}
        )
        spy_paths = {
            sc: _growth_path(base_value, spy_mu, spy_sigma, cfg["days"], cfg["step_days"], sc)
            for sc in ("avg", "best", "worst")
        }
        label_path = port_paths["avg"] if has_holdings else spy_paths["avg"]
        labels = [p["date"] for p in label_path]

        horizons_out[key] = {
            "label": cfg["label"],
            "days": cfg["days"],
            "labels": labels,
            "portfolio": {
                "values": port_paths,
                "indexed": _index_paths(port_paths),
                "end": _end_summary(port_paths) if has_holdings else {},
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
        "scenario_why": _build_scenario_why(port_mu, port_sigma, spy_mu, spy_sigma),
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
