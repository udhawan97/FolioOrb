"""Tests for portfolio growth projection service."""

from unittest.mock import patch

import numpy as np

from app.services import portfolio_projection as pp


def _synthetic_rows(start: float, daily_drift: float, days: int = 400):
    """Generate OHLCV-style rows with small noise."""
    rng = np.random.default_rng(42)
    out = []
    price = start
    for i in range(days):
        price *= np.exp(daily_drift + rng.normal(0, 0.008))
        out.append({
            "date": f"2023-{(i // 28) + 1:02d}-{1 + (i % 28):02d}",
            "close": round(float(price), 2),
        })
    return out


def test_growth_path_scenarios_ordering():
    start = 10_000.0
    mu, sigma = 0.10, 0.18
    avg = pp._growth_path(start, mu, sigma, 365, 30, "avg")
    best = pp._growth_path(start, mu, sigma, 365, 30, "best")
    worst = pp._growth_path(start, mu, sigma, 365, 30, "worst")

    assert avg[0]["value"] == start
    assert best[-1]["value"] > avg[-1]["value"] > worst[-1]["value"]


def test_portfolio_daily_returns_weighted():
    series_a = [("2024-01-01", 100.0), ("2024-01-02", 110.0), ("2024-01-03", 121.0)]
    series_b = [("2024-01-01", 50.0), ("2024-01-02", 50.0), ("2024-01-03", 50.0)]
    rets = pp._portfolio_daily_returns([
        ("AAA", 6000.0, series_a),
        ("BBB", 4000.0, series_b),
    ])
    assert rets.size == 2
    assert rets[0] > 0


@patch.object(pp, "get_historical_prices")
def test_compute_projection_returns_all_horizons(mock_hist):
    spy = _synthetic_rows(400.0, 0.0004)
    voo = _synthetic_rows(350.0, 0.0005)
    mock_hist.side_effect = lambda ticker, period: {
        "SPY": spy,
        "VOO": voo,
    }.get(ticker, [])

    holdings = [
        {"ticker": "VOO", "current_value": 8000.0, "is_watchlist": False},
    ]
    result = pp.compute_portfolio_projection(holdings, 8000.0)

    assert result["has_holdings"] is True
    assert set(result["horizons"].keys()) == {"30d", "1y", "3y", "5y", "10y"}
    hz = result["horizons"]["1y"]
    assert hz["portfolio"]["end"]["best"] > hz["portfolio"]["end"]["avg"]
    assert hz["portfolio"]["end"]["avg"] > hz["portfolio"]["end"]["worst"]
    assert len(hz["labels"]) >= 2


@patch.object(pp, "get_historical_prices")
def test_projection_cache_reuses_payload(mock_hist):
    mock_hist.return_value = _synthetic_rows(400.0, 0.0003)
    holdings = [{"ticker": "VOO", "current_value": 5000.0, "is_watchlist": False}]

    pp._cache.clear()
    first = pp.get_cached_projection(holdings, 5000.0)
    second = pp.get_cached_projection(holdings, 5000.0)

    assert first["cached"] is False
    assert second["cached"] is True
    assert mock_hist.call_count == 2  # VOO + SPY fetched once
