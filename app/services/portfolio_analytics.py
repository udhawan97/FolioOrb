"""
Portfolio analytics — risk metrics, correlation, drawdown, and attribution.

Computes from cached/batched price history server-side (same cache as timing signals).
"""
# pylint: disable=too-many-lines

from __future__ import annotations

import hashlib
import math
import time
from datetime import date, timedelta
from typing import Any

import numpy as np

from app.services.portfolio_projection import (
    BENCHMARK_TICKER,
    TRADING_DAYS,
    _portfolio_daily_returns,
)
from app.services.portfolio_exposure import build_portfolio_exposure
from app.services.stock_service import get_all_quotes, get_historical_prices
from app.services.timing_signal import get_batched_history_closes

_CACHE_TTL_SEC = 300
_cache: dict[str, dict[str, Any]] = {}


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if not entry or entry["expires_at"] < time.time():
        return None
    return entry["payload"]


def _cache_set(key: str, payload: Any) -> Any:
    _cache[key] = {"payload": payload, "expires_at": time.time() + _CACHE_TTL_SEC}
    return payload


def _tickers_key(tickers: list[str], suffix: str = "") -> str:
    raw = ",".join(sorted(t.upper() for t in tickers if t)) + suffix
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()


def _log_returns(closes: list[float]) -> np.ndarray:
    if len(closes) < 2:
        return np.array([], dtype=float)
    prices = np.asarray(closes, dtype=float)
    return np.diff(np.log(prices))


def _annualize_stats(daily_log_returns: np.ndarray) -> tuple[float, float]:
    if daily_log_returns.size < 5:
        return 0.0, 0.0
    mu = float(np.mean(daily_log_returns)) * TRADING_DAYS
    sigma = float(np.std(daily_log_returns, ddof=1)) * math.sqrt(TRADING_DAYS)
    return round(mu * 100, 2), round(sigma * 100, 2)


def _aligned_daily_returns(
    series_map: dict[str, list[float]],
) -> tuple[list[str], np.ndarray]:
    """
    Build a matrix of daily log-returns with rows = tickers, cols = aligned days.
    Uses minimum overlapping length across series (tail-aligned).
    """
    tickers = [t for t, c in series_map.items() if len(c) >= 2]
    if not tickers:
        return [], np.array([])

    min_len = min(len(series_map[t]) for t in tickers)
    if min_len < 2:
        return [], np.array([])

    rows = []
    for t in tickers:
        closes = series_map[t][-min_len:]
        rows.append(_log_returns(closes))
    return tickers, np.vstack(rows)


def compute_risk_metrics(
    holdings: list[dict],
    total_value: float,
    *,
    signals: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """
    Per-holding annualized return & volatility for the risk/reward scatter.
    Includes portfolio-weighted aggregate and S&P 500 benchmark point.
    """
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("current_value") or 0) > 0
    ]
    tickers = [h["ticker"] for h in active]
    cache_key = f"risk:{_tickers_key(tickers)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    signals = signals or {}
    history = get_batched_history_closes(tickers + [BENCHMARK_TICKER], period="1y")

    points: list[dict] = []
    weights: list[float] = []
    port_rets: list[float] = []

    for h in active:
        ticker = h["ticker"]
        closes = history.get(ticker, [])
        rets = _log_returns(closes)
        ann_ret, ann_vol = _annualize_stats(rets)
        w = float(h.get("allocation_pct") or 0)
        action = (signals.get(ticker) or {}).get("action", "hold")
        points.append({
            "ticker": ticker,
            "annual_return_pct": ann_ret,
            "annual_vol_pct": ann_vol,
            "allocation_pct": w,
            "action": action,
        })
        if rets.size:
            weights.append(w)
            port_rets.append(float(np.mean(rets)) * TRADING_DAYS * 100)

    portfolio_point: dict[str, Any] | None = None
    if active and total_value > 0:
        wsum = sum(float(h.get("allocation_pct") or 0) for h in active)
        if wsum > 0 and port_rets:
            weighted_ret = sum(
                float(h.get("allocation_pct") or 0) * _annualize_stats(
                    _log_returns(history.get(h["ticker"], []))
                )[0]
                for h in active
            ) / wsum
            # Portfolio vol from weighted daily returns
            series_map = {h["ticker"]: history.get(h["ticker"], []) for h in active}
            tickers_aligned, mat = _aligned_daily_returns(series_map)
            port_vol = 0.0
            if mat.size:
                w_vec = np.array([
                    float(h.get("allocation_pct") or 0) / wsum
                    for h in active if h["ticker"] in tickers_aligned
                ])
                if w_vec.size == mat.shape[0]:
                    port_daily = w_vec @ mat
                    port_vol = float(np.std(port_daily, ddof=1)) * math.sqrt(TRADING_DAYS) * 100
            portfolio_point = {
                "label": "Your portfolio",
                "annual_return_pct": round(weighted_ret, 2),
                "annual_vol_pct": round(port_vol, 2),
            }

    spy_closes = history.get(BENCHMARK_TICKER, [])
    spy_ret, spy_vol = _annualize_stats(_log_returns(spy_closes))
    benchmark_point = {
        "label": "S&P 500",
        "ticker": BENCHMARK_TICKER,
        "annual_return_pct": spy_ret,
        "annual_vol_pct": spy_vol,
    }

    payload = {
        "holdings": points,
        "portfolio": portfolio_point,
        "benchmark": benchmark_point,
        "has_data": bool(points),
    }
    return _cache_set(cache_key, payload)


def compute_correlation_matrix(holdings: list[dict]) -> dict[str, Any]:
    """Pearson correlation of daily log-returns for current holdings."""
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("current_value") or 0) > 0
    ]
    tickers = [h["ticker"] for h in active]
    cache_key = f"corr:{_tickers_key(tickers)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if len(tickers) < 2:
        return _cache_set(cache_key, {"tickers": tickers, "matrix": [], "has_data": False})

    history = get_batched_history_closes(tickers, period="1y")
    aligned_tickers, mat = _aligned_daily_returns(history)

    if mat.size == 0 or mat.ndim < 2 or mat.shape[0] < 2 or mat.shape[1] < 5:
        n = len(aligned_tickers) or len(tickers)
        identity = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        return _cache_set(cache_key, {
            "tickers": aligned_tickers or tickers,
            "matrix": identity,
            "has_data": False,
        })

    corr = np.corrcoef(mat)
    corr = np.nan_to_num(corr, nan=0.0)
    matrix = [[round(float(corr[i, j]), 3) for j in range(corr.shape[1])]
              for i in range(corr.shape[0])]

    return _cache_set(cache_key, {
        "tickers": aligned_tickers,
        "matrix": matrix,
        "has_data": True,
    })


def compute_drawdown(history: list[dict]) -> dict[str, Any]:
    """Drawdown series (% below running peak) from portfolio snapshot history."""
    rows = [r for r in (history or []) if r.get("date") and r.get("total_value") is not None]
    if len(rows) < 2:
        return {"series": [], "max_drawdown_pct": 0.0, "max_drawdown_date": None, "has_data": False}

    series: list[dict] = []
    peak = 0.0
    max_dd = 0.0
    max_dd_date: str | None = None

    for row in rows:
        value = float(row["total_value"])
        peak = max(peak, value)
        dd = ((value - peak) / peak * 100) if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
            max_dd_date = row["date"]
        series.append({"date": row["date"], "drawdown_pct": round(dd, 2)})

    return {
        "series": series,
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_date": max_dd_date,
        "has_data": True,
    }


_CONTRIBUTION_TOP_EACH_SIDE = 5


def _contribution_row(
    h: dict,
    *,
    contrib: float,
    change_pct: float,
) -> dict[str, Any]:
    allocation = float(h.get("allocation_pct") or 0)
    return {
        "ticker": h["ticker"],
        "name": h.get("name") or h["ticker"],
        "contribution": contrib,
        "change_pct": round(change_pct, 2),
        "contribution_pp": round(allocation * change_pct / 100.0, 4),
        "allocation_pct": allocation,
        "current_value": round(float(h.get("current_value") or 0), 2),
    }


def _finalize_contribution_payload(
    contributions: list[dict[str, Any]],
    *,
    period: str,
    portfolio_value: float,
) -> dict[str, Any]:
    total = round(sum(c["contribution"] for c in contributions), 2)

    # Normalize contribution_pct by the *gross* (absolute) total so individual
    # values stay within [-100, +100].  Dividing by the net total causes values
    # to blow past 100 % whenever gainers and losers partially cancel out.
    abs_total = sum(abs(c["contribution"]) for c in contributions)
    if abs_total > 0:
        for c in contributions:
            c["contribution_pct"] = round(c["contribution"] / abs_total * 100, 1)
    else:
        for c in contributions:
            c["contribution_pct"] = 0.0

    gainers = sorted(
        [c for c in contributions if c["contribution"] > 0],
        key=lambda x: x["contribution"],
        reverse=True,
    )
    losers = sorted(
        [c for c in contributions if c["contribution"] < 0],
        key=lambda x: x["contribution"],
    )
    top_gainers = gainers[:_CONTRIBUTION_TOP_EACH_SIDE]
    top_losers = losers[:_CONTRIBUTION_TOP_EACH_SIDE]
    shown = {c["ticker"] for c in top_gainers + top_losers}
    rest = [c for c in contributions if c["ticker"] not in shown]
    others_contrib = round(sum(c["contribution"] for c in rest), 2)

    others: dict[str, Any] | None = None
    if rest and others_contrib != 0:
        others = {
            "ticker": "Other",
            "name": f"{len(rest)} other holding{'s' if len(rest) != 1 else ''}",
            "contribution": others_contrib,
            "contribution_pct": round(others_contrib / abs_total * 100, 1) if abs_total else 0.0,
            "change_pct": None,
            "contribution_pp": round(sum(c["contribution_pp"] for c in rest), 4),
            "allocation_pct": round(sum(c["allocation_pct"] for c in rest), 1),
            "current_value": round(sum(c["current_value"] for c in rest), 2),
            "count": len(rest),
        }

    portfolio_change_pct = (
        round(total / portfolio_value * 100, 2) if portfolio_value > 0 else 0.0
    )
    return {
        "period": period,
        "total_contribution": total,
        "portfolio_value": round(portfolio_value, 2),
        "portfolio_change_pct": portfolio_change_pct,
        "holdings_count": len(contributions),
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "others": others,
        "holdings": sorted(contributions, key=lambda x: abs(x["contribution"]), reverse=True),
        "has_data": bool(contributions),
    }


def compute_contribution(
    holdings: list[dict],
    period: str = "day",
) -> dict[str, Any]:
    """
    Per-holding contribution to portfolio P&L for day / week / month.
    Day uses live day_change × shares; longer periods use price history.
    """
    period = period if period in ("day", "week", "month") else "day"
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("shares") or 0) > 0
    ]
    portfolio_value = sum(float(h.get("current_value") or 0) for h in active)
    tickers = [h["ticker"] for h in active]

    if period == "day":
        contributions = []
        for h in active:
            shares = float(h.get("shares") or 0)
            day_chg = float(h.get("day_change") or 0)
            change_pct = float(h.get("day_change_pct") or 0)
            contrib = round(shares * day_chg, 2)
            contributions.append(_contribution_row(h, contrib=contrib, change_pct=change_pct))
        return _finalize_contribution_payload(
            contributions, period=period, portfolio_value=portfolio_value
        )

    lookback = {"week": 7, "month": 30}[period]
    history = get_batched_history_closes(tickers, period="1mo")
    contributions = []

    for h in active:
        ticker = h["ticker"]
        shares = float(h.get("shares") or 0)
        closes = history.get(ticker, [])
        contrib = 0.0
        change_pct = 0.0
        if len(closes) >= 2:
            tail = closes[-min(lookback + 1, len(closes)):]
            if len(tail) >= 2 and tail[0] > 0:
                contrib = round(shares * (tail[-1] - tail[0]), 2)
                change_pct = (tail[-1] - tail[0]) / tail[0] * 100.0
        contributions.append(_contribution_row(h, contrib=contrib, change_pct=change_pct))

    return _finalize_contribution_payload(
        contributions, period=period, portfolio_value=portfolio_value
    )


# Dashboard time ranges → trading-day lookbacks into daily closes.
# Keys match the frontend's shared selectedTimeRange values ("day" is computed
# from live quotes client-side and never hits this table).
RANGE_TRADING_DAYS: dict[str, int] = {
    "week": 5,
    "month": 21,
    "threeMonth": 63,
    "sixMonth": 126,
    "year": 252,
}


def _range_holding_rows(
    active: list[dict],
    history: dict[str, list[float]],
    lookback: int,
) -> dict[str, Any]:
    """Per-holding change over `lookback` trading days from batched closes."""
    rows: dict[str, dict[str, float]] = {}
    net = 0.0
    base = 0.0
    for h in active:
        ticker = h["ticker"]
        shares = float(h.get("shares") or 0)
        closes = history.get(ticker, [])
        if len(closes) < 2:
            continue
        tail = closes[-min(lookback + 1, len(closes)):]
        if len(tail) < 2 or tail[0] <= 0:
            continue
        value_change = shares * (tail[-1] - tail[0])
        rows[ticker] = {
            "change_pct": round((tail[-1] - tail[0]) / tail[0] * 100.0, 2),
            "value_change": round(value_change, 2),
        }
        net += value_change
        base += shares * tail[0]
    return {
        "holdings": rows,
        "net_change": round(net, 2),
        "net_change_pct": round(net / base * 100.0, 2) if base > 0 else None,
    }


def compute_range_rows(holdings: list[dict], range_key: str) -> dict[str, Any]:
    """Per-holding change for a single dashboard range (week … year)."""
    lookback = RANGE_TRADING_DAYS.get(range_key)
    if lookback is None:
        return {"holdings": {}, "net_change": 0.0, "net_change_pct": None}
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("shares") or 0) > 0
    ]
    history = get_batched_history_closes([h["ticker"] for h in active], period="1y")
    return _range_holding_rows(active, history, lookback)


def compute_range_performance(holdings: list[dict]) -> dict[str, Any]:
    """
    Per-holding price change for every dashboard time range in one payload,
    from a single batched 1y history fetch (same-day cached server-side).
    """
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("shares") or 0) > 0
    ]
    history = (
        get_batched_history_closes([h["ticker"] for h in active], period="1y")
        if active else {}
    )
    return {
        "as_of": date.today().isoformat(),
        "ranges": {
            key: _range_holding_rows(active, history, lookback)
            for key, lookback in RANGE_TRADING_DAYS.items()
        },
    }


_INDEX_GEO_KEYS: dict[str, list[str]] = {
    "^GSPC": ["united states"],
    "^IXIC": ["united states"],
    "^DJI": ["united states"],
    "^FTSE": ["united kingdom", "uk"],
    "^GDAXI": ["germany"],
    "^FCHI": ["france"],
    "^N225": ["japan"],
    "^HSI": ["hong kong", "china"],
    "^NSEI": ["india"],
    "^AXJO": ["australia"],
}


def _price_series(ticker: str) -> list[tuple[str, float]]:
    rows = get_historical_prices(ticker, "1y")
    return [(r["date"], float(r["close"])) for r in rows if r.get("close", 0) > 0]


def _geo_weight(country_exposure: list[dict], keywords: list[str]) -> float:
    for entry in country_exposure:
        name = str(entry.get("name") or "").lower()
        if any(kw in name for kw in keywords):
            return float(entry.get("weight_pct") or 0)
    return 0.0


def _correlation_label(value: float) -> str:
    if value >= 0.7:
        return "High"
    if value >= 0.4:
        return "Moderate"
    if value < 0:
        return "Inverse"
    if value < 0.15:
        return "Weak"
    return "Low"


def _market_insight(correlation: float, geo_weight: float, _name: str) -> str:
    if geo_weight >= 25 and correlation >= 0.45:
        return f"~{geo_weight:.0f}% look-through exposure — tends to move with your book"
    if correlation >= 0.65:
        return "Moves closely with your portfolio day to day"
    if correlation >= 0.35:
        return "Some overlap with your daily moves"
    if correlation < -0.1:
        return "Often offsets your book — diversification ballast"
    return "Limited day-to-day link to your holdings"


def _portfolio_index_correlations(
    holdings: list[dict],
    index_tickers: list[str],
) -> dict[str, float]:
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("current_value") or 0) > 0
    ]
    if not active:
        return {}

    weighted = [(h["ticker"], float(h["current_value"])) for h in active]
    series_map: dict[str, list[tuple[str, float]]] = {}
    for ticker, _ in weighted:
        series_map[ticker] = _price_series(ticker)
    for idx in index_tickers:
        if idx not in series_map:
            series_map[idx] = _price_series(idx)

    port_rets = _portfolio_daily_returns([
        (ticker, weight, series_map.get(ticker, []))
        for ticker, weight in weighted
    ])
    if port_rets.size < 5:
        return {}

    out: dict[str, float] = {}
    for idx in index_tickers:
        series = series_map.get(idx, [])
        if len(series) < 2:
            out[idx] = 0.0
            continue
        idx_rets = _log_returns([c for _d, c in series])
        n = min(port_rets.size, idx_rets.size)
        if n < 5:
            out[idx] = 0.0
            continue
        corr = float(np.corrcoef(port_rets[-n:], idx_rets[-n:])[0, 1])
        out[idx] = round(corr if np.isfinite(corr) else 0.0, 3)
    return out


def compute_market_context(
    holdings: list[dict],
    world_markets: list[dict],
) -> dict[str, Any]:
    """
    Enrich world indices with portfolio correlation and geographic alignment.
    """
    cache_key = (
        f"mktctx:{_tickers_key([h['ticker'] for h in holdings if not h.get('is_watchlist')])}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        quote_map = {m["ticker"]: m for m in world_markets}
        markets = []
        for row in cached.get("markets", []):
            live = quote_map.get(row["ticker"], {})
            markets.append({
                **row,
                "price": live.get("price", row.get("price")),
                "day_change": live.get("day_change", row.get("day_change")),
                "day_change_pct": live.get("day_change_pct", row.get("day_change_pct")),
            })
        return {**cached, "markets": markets}

    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("allocation_pct") or 0) > 0
    ]
    if not active:
        return _cache_set(cache_key, {
            "has_data": False,
            "markets": world_markets,
            "summary": None,
            "best_match": None,
        })

    quotes = get_all_quotes([h["ticker"] for h in active])
    exposure = build_portfolio_exposure(
        [
            {
                "ticker": h["ticker"],
                "allocation_pct": h.get("allocation_pct"),
                "is_watchlist": h.get("is_watchlist"),
            }
            for h in active
        ],
        quotes={q["ticker"]: q for q in quotes},
    )
    country_exposure = exposure.get("country_exposure") or []

    index_tickers = [m["ticker"] for m in world_markets]
    correlations = _portfolio_index_correlations(holdings, index_tickers)

    enriched: list[dict] = []
    for market in world_markets:
        ticker = market["ticker"]
        corr = correlations.get(ticker, 0.0)
        geo = _geo_weight(country_exposure, _INDEX_GEO_KEYS.get(ticker, []))
        enriched.append({
            **market,
            "correlation": corr,
            "correlation_label": _correlation_label(corr),
            "geo_weight_pct": round(geo, 1),
            "insight": _market_insight(corr, geo, market.get("name", ticker)),
        })

    enriched.sort(key=lambda m: m.get("correlation", 0), reverse=True)
    best = enriched[0] if enriched else None

    us_weight = _geo_weight(country_exposure, ["united states"])
    summary_parts: list[str] = []
    if best and best.get("correlation", 0) > 0.2:
        summary_parts.append(
            f"Your portfolio is most in sync with {best.get('name', '')} "
            f"({best.get('correlation', 0) * 100:.0f}% correlated over the past year)."
        )
    if us_weight >= 30:
        summary_parts.append(
            f"~{us_weight:.0f}% of your look-through exposure is US-linked — "
            "watch the US row when global markets move."
        )
    if not summary_parts:
        summary_parts.append(
            "Compare how each global index moves relative to your holdings — "
            "higher correlation means a bigger ripple effect on your book."
        )

    payload = {
        "has_data": True,
        "markets": enriched,
        "summary": " ".join(summary_parts),
        "best_match": (
            {
                "ticker": best["ticker"],
                "name": best["name"],
                "correlation": best["correlation"],
            }
            if best
            else None
        ),
        "us_exposure_pct": round(us_weight, 1),
    }
    return _cache_set(cache_key, payload)


# ── Extended analytics: benchmark, calendar, beta, tilt, signals, markets ──


_SPY_SECTOR_BENCHMARK: list[dict[str, Any]] = [
    {"name": "Technology", "weight_pct": 31.5},
    {"name": "Financials", "weight_pct": 13.1},
    {"name": "Healthcare", "weight_pct": 11.6},
    {"name": "Consumer Disc.", "weight_pct": 10.2},
    {"name": "Industrials", "weight_pct": 8.5},
    {"name": "Other", "weight_pct": 25.1},
]

_BENCHMARK_RANGES: dict[str, int | None] = {
    "1m": 30,
    "3m": 90,
    "1y": 365,
    "max": None,
}


def _history_return_pct(rows: list[dict], lookback_days: int | None) -> float | None:
    if len(rows) < 2:
        return None
    if lookback_days is not None and len(rows) > lookback_days + 1:
        rows = rows[-(lookback_days + 1):]
    start = float(rows[0]["total_value"])
    end = float(rows[-1]["total_value"])
    if start <= 0:
        return None
    return round((end - start) / start * 100, 2)


def _spy_return_pct(lookback_days: int | None) -> float | None:
    period = "1y" if lookback_days and lookback_days <= 365 else "3y"
    rows = get_historical_prices(BENCHMARK_TICKER, period)
    closes = [float(r["close"]) for r in rows if r.get("close", 0) > 0]
    if len(closes) < 2:
        return None
    if lookback_days is not None and len(closes) > lookback_days + 1:
        closes = closes[-(lookback_days + 1):]
    start, end = closes[0], closes[-1]
    if start <= 0:
        return None
    return round((end - start) / start * 100, 2)


def compute_benchmark_comparison(
    holdings: list[dict],
    history: list[dict],
) -> dict[str, Any]:
    """Portfolio vs S&P 500 returns by range with aligned chart series."""
    rows = [r for r in (history or []) if r.get("date") and r.get("total_value") is not None]
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("current_value") or 0) > 0
    ]

    if len(rows) < 2 or not active:
        return {
            "has_data": False,
            "ranges": {},
            "series": [],
            "active_range": "1y",
        }

    spy_rows = get_historical_prices(BENCHMARK_TICKER, "3y")
    spy_by_date = {r["date"]: float(r["close"]) for r in spy_rows if r.get("close", 0) > 0}
    if not spy_by_date:
        return {"has_data": False, "ranges": {}, "series": [], "active_range": "1y"}

    port_start = float(rows[0]["total_value"])
    if port_start <= 0:
        return {"has_data": False, "ranges": {}, "series": [], "active_range": "1y"}

    series: list[dict] = []
    spy_anchor = spy_by_date.get(rows[0]["date"])
    if not spy_anchor:
        spy_anchor = next(iter(spy_by_date.values()), None)
    spy_anchor = float(spy_anchor or 1)

    for row in rows:
        d = row["date"]
        spy_close = spy_by_date.get(d)
        if not spy_close:
            continue
        port_val = float(row["total_value"])
        series.append({
            "date": d,
            "portfolio_pct": round((port_val - port_start) / port_start * 100, 2),
            "benchmark_pct": round((float(spy_close) - spy_anchor) / spy_anchor * 100, 2),
        })

    ranges: dict[str, dict] = {}
    for key, days in _BENCHMARK_RANGES.items():
        port_ret = _history_return_pct(rows, days)
        spy_ret = _spy_return_pct(days)
        if port_ret is None or spy_ret is None:
            continue
        ranges[key] = {
            "portfolio_pct": port_ret,
            "benchmark_pct": spy_ret,
            "alpha_pct": round(port_ret - spy_ret, 2),
        }

    return {
        "has_data": bool(series and ranges),
        "ranges": ranges,
        "series": series,
        "active_range": "1y" if "1y" in ranges else next(iter(ranges), "max"),
        "benchmark_label": "S&P 500",
    }


def compute_return_calendar(history: list[dict]) -> dict[str, Any]:
    """Monthly portfolio return tiles from snapshot history."""
    rows = [r for r in (history or []) if r.get("date") and r.get("total_value") is not None]
    if len(rows) < 2:
        return {"has_data": False, "months": []}

    by_month: dict[str, list[dict]] = {}
    for row in rows:
        d = str(row["date"])[:7]
        by_month.setdefault(d, []).append(row)

    months: list[dict] = []
    for ym in sorted(by_month):
        bucket = by_month[ym]
        if not bucket:
            continue
        start_val = float(bucket[0]["total_value"])
        end_val = float(bucket[-1]["total_value"])
        if start_val <= 0:
            continue
        ret = round((end_val - start_val) / start_val * 100, 2)
        year_s, month_s = ym.split("-")
        months.append({
            "year": int(year_s),
            "month": int(month_s),
            "label": ym,
            "return_pct": ret,
        })

    return {"has_data": len(months) >= 2, "months": months[-24:]}


def _portfolio_and_spy_daily_returns(holdings: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("current_value") or 0) > 0
    ]
    if not active:
        return np.array([]), np.array([])

    weighted = []
    for h in active:
        series = _price_series(h["ticker"])
        weighted.append((h["ticker"], float(h.get("current_value") or 0), series))

    port_rets = _portfolio_daily_returns(weighted)
    spy_series = _price_series(BENCHMARK_TICKER)
    spy_rets = _log_returns([c for _d, c in spy_series])
    n = min(port_rets.size, spy_rets.size)
    if n < 10:
        return np.array([]), np.array([])
    return port_rets[-n:], spy_rets[-n:]


def compute_portfolio_beta(holdings: list[dict]) -> dict[str, Any]:
    """Portfolio beta vs S&P 500 from aligned daily log-returns."""
    tickers = [h["ticker"] for h in holdings if not h.get("is_watchlist")]
    cache_key = f"beta:{_tickers_key(tickers)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    port_rets, spy_rets = _portfolio_and_spy_daily_returns(holdings)
    if port_rets.size < 10:
        payload = {"has_data": False, "beta": None, "label": None}
        return _cache_set(cache_key, payload)

    spy_var = float(np.var(spy_rets, ddof=1))
    if spy_var <= 0:
        payload = {"has_data": False, "beta": None, "label": None}
        return _cache_set(cache_key, payload)

    beta = float(np.cov(port_rets, spy_rets)[0, 1] / spy_var)
    beta = round(beta, 2)
    if beta < 0.75:
        label = "Defensive"
    elif beta < 1.1:
        label = "Market pace"
    else:
        label = "Aggressive"

    return _cache_set(cache_key, {
        "has_data": True,
        "beta": beta,
        "label": label,
        "benchmark_label": "S&P 500",
    })


def compute_rolling_volatility(holdings: list[dict], *, window: int = 30) -> dict[str, Any]:
    """Trailing annualized volatility series for the portfolio."""
    tickers = [h["ticker"] for h in holdings if not h.get("is_watchlist")]
    cache_key = f"rollvol:{_tickers_key(tickers)}:{window}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("current_value") or 0) > 0
    ]
    if not active:
        return _cache_set(cache_key, {"has_data": False, "series": [], "current_vol_pct": None})

    weighted = [
        (h["ticker"], float(h.get("current_value") or 0), _price_series(h["ticker"]))
        for h in active
    ]
    port_rets = _portfolio_daily_returns(weighted)
    if port_rets.size < window + 5:
        return _cache_set(cache_key, {"has_data": False, "series": [], "current_vol_pct": None})

    series: list[dict] = []
    today = date.today()
    for i in range(window, port_rets.size + 1):
        chunk = port_rets[i - window:i]
        vol = float(np.std(chunk, ddof=1)) * math.sqrt(TRADING_DAYS) * 100
        offset = port_rets.size - i
        pt_date = (today - timedelta(days=offset)).isoformat()
        series.append({"date": pt_date, "vol_pct": round(vol, 2)})

    current = series[-1]["vol_pct"] if series else None
    return _cache_set(cache_key, {
        "has_data": bool(series),
        "series": series[-120:],
        "current_vol_pct": current,
        "window_days": window,
    })


def compute_sector_tilt(holdings: list[dict]) -> dict[str, Any]:
    """Sector overweight / underweight vs S&P 500 look-through benchmark."""
    active = [
        h for h in holdings
        if not h.get("is_watchlist") and float(h.get("allocation_pct") or 0) > 0
    ]
    if not active:
        return {"has_data": False, "sectors": []}

    quotes = get_all_quotes([h["ticker"] for h in active])
    exposure = build_portfolio_exposure(
        [
            {
                "ticker": h["ticker"],
                "allocation_pct": h.get("allocation_pct"),
                "is_watchlist": False,
            }
            for h in active
        ],
        quotes={q["ticker"]: q for q in quotes},
    )
    port_sectors = {
        s["name"]: float(s["weight_pct"])
        for s in (exposure.get("sector_exposure") or [])
    }
    bench_map = {s["name"]: float(s["weight_pct"]) for s in _SPY_SECTOR_BENCHMARK}

    all_names = sorted(
        set(port_sectors) | set(bench_map),
        key=lambda n: port_sectors.get(n, 0),
        reverse=True,
    )
    sectors: list[dict] = []
    for name in all_names[:11]:
        port_w = port_sectors.get(name, 0.0)
        bench_w = bench_map.get(name, 0.0)
        tilt = round(port_w - bench_w, 1)
        sectors.append({
            "name": name,
            "portfolio_pct": round(port_w, 1),
            "benchmark_pct": round(bench_w, 1),
            "tilt_pct": tilt,
        })

    holding_contributions = exposure.get("holding_sector_contributions") or {}

    return {
        "has_data": bool(sectors),
        "sectors": sectors,
        "benchmark_label": "S&P 500",
        "holding_contributions": holding_contributions,
    }


def compute_conviction_gaps(
    holdings: list[dict],
    signals: dict[str, dict],
) -> dict[str, Any]:
    """Positions where verdict tone conflicts with position size."""
    gaps: list[dict] = []
    total_holdings = 0
    flagged_alloc = 0.0

    for h in holdings:
        if h.get("is_watchlist"):
            continue
        ticker = h["ticker"]
        alloc = float(h.get("allocation_pct") or 0)
        if alloc <= 0:
            continue
        total_holdings += 1
        sig = signals.get(ticker) or {}
        action = str(sig.get("action") or "hold").lower()
        conf = int(sig.get("confidence") or 50)

        gap_type = None
        severity = 0.0
        # Meaningful position being told to trim/sell
        if action in ("trim", "sell") and alloc >= 7:
            gap_type = "large_trim"
            severity = alloc * (conf / 100)
        # Buy/add signal but position is still small — room to act
        elif action in ("buy", "add") and alloc <= 8 and conf >= 60:
            gap_type = "small_add"
            severity = conf * (10 - alloc)
        # Sizable position sitting on a hold signal — no strong upside case
        elif action in ("hold", "wait") and alloc >= 12:
            gap_type = "heavy_hold"
            severity = alloc
        # Any meaningful position where AI confidence is low — uncertain signal
        elif alloc >= 5 and conf < 55:
            gap_type = "uncertain_hold"
            severity = alloc * ((55 - conf) / 55)

        if gap_type:
            gaps.append({
                "ticker": ticker,
                "allocation_pct": round(alloc, 1),
                "action": action,
                "confidence": conf,
                "gap_type": gap_type,
                "severity": round(severity, 1),
            })
            flagged_alloc += alloc

    gaps.sort(key=lambda g: g["severity"], reverse=True)
    top_gaps = gaps[:8]
    return {
        "has_data": bool(top_gaps),
        "gaps": top_gaps,
        "summary": {
            "flagged": len(top_gaps),
            "total": total_holdings,
            "flagged_alloc_pct": round(flagged_alloc, 1),
        },
    }


def compute_confidence_spectrum(
    holdings: list[dict],
    signals: dict[str, dict],
) -> dict[str, Any]:
    """Allocation-weighted confidence distribution across holdings."""
    buckets = {"low": 0.0, "mid": 0.0, "high": 0.0, "very_high": 0.0}
    details: list[dict] = []
    total = 0.0

    for h in holdings:
        if h.get("is_watchlist"):
            continue
        ticker = h["ticker"]
        alloc = float(h.get("allocation_pct") or 0)
        if alloc <= 0:
            continue
        sig = signals.get(ticker) or {}
        conf = int(sig.get("confidence") or 50)
        total += alloc
        if conf < 60:
            buckets["low"] += alloc
        elif conf < 70:
            buckets["mid"] += alloc
        elif conf < 85:
            buckets["high"] += alloc
        else:
            buckets["very_high"] += alloc
        details.append({"ticker": ticker, "confidence": conf, "allocation_pct": round(alloc, 1)})

    if total <= 0:
        return {"has_data": False, "buckets": [], "holdings": []}

    raw_rows = [
        {"band": "40–59%", "key": "low", "weight_pct": round(buckets["low"] / total * 100, 1)},
        {"band": "60–69%", "key": "mid", "weight_pct": round(buckets["mid"] / total * 100, 1)},
        {"band": "70–84%", "key": "high", "weight_pct": round(buckets["high"] / total * 100, 1)},
        {
            "band": "85%+",
            "key": "very_high",
            "weight_pct": round(buckets["very_high"] / total * 100, 1),
        },
    ]
    # Rounding each bucket independently can leave the sum at 99.9 or 100.1.
    # Adjust the largest bucket by the residual so all four always sum to 100.
    raw_sum = sum(r["weight_pct"] for r in raw_rows)
    residual = round(100.0 - raw_sum, 1)
    if residual and raw_rows:
        largest = max(raw_rows, key=lambda r: r["weight_pct"])
        largest["weight_pct"] = round(largest["weight_pct"] + residual, 1)
    bucket_rows = raw_rows
    dominant = max(bucket_rows, key=lambda b: b["weight_pct"])
    return {
        "has_data": True,
        "buckets": bucket_rows,
        "dominant_band": dominant["band"],
        "avg_confidence": round(
            sum(d["confidence"] * d["allocation_pct"] for d in details) / total
        ) if details else 0,
        "holdings": details,
    }


def compute_market_sensitivity(
    holdings: list[dict],
    world_markets: list[dict],
) -> dict[str, Any]:
    """Estimated portfolio move per 1% index shock."""
    ctx = compute_market_context(holdings, world_markets)
    if not ctx.get("has_data"):
        return {"has_data": False, "indices": []}

    port_rets, _spy_rets = _portfolio_and_spy_daily_returns(holdings)
    port_vol = (
        float(np.std(port_rets, ddof=1)) * math.sqrt(TRADING_DAYS) * 100
        if port_rets.size > 5 else 15.0
    )

    indices: list[dict] = []
    for m in ctx.get("markets") or []:
        corr = float(m.get("correlation") or 0)
        impact = round(corr * port_vol / 100, 2)
        indices.append({
            "ticker": m.get("ticker"),
            "name": m.get("name"),
            "flag": m.get("flag"),
            "correlation": corr,
            "impact_per_1pct": impact,
            "geo_weight_pct": m.get("geo_weight_pct"),
        })

    indices.sort(key=lambda x: abs(x["impact_per_1pct"]), reverse=True)
    return {
        "has_data": bool(indices),
        "indices": indices[:10],
        "portfolio_vol_pct": round(port_vol, 1),
    }


def compute_macro_alignment(
    holdings: list[dict],
    world_markets: list[dict],
) -> dict[str, Any]:
    """Scatter points: index correlation vs geographic look-through exposure."""
    ctx = compute_market_context(holdings, world_markets)
    if not ctx.get("has_data"):
        return {"has_data": False, "points": []}

    points = []
    for m in ctx.get("markets") or []:
        points.append({
            "ticker": m.get("ticker"),
            "name": m.get("name"),
            "flag": m.get("flag"),
            "correlation": float(m.get("correlation") or 0),
            "geo_weight_pct": float(m.get("geo_weight_pct") or 0),
            "day_change_pct": float(m.get("day_change_pct") or 0),
        })

    return {"has_data": bool(points), "points": points}
