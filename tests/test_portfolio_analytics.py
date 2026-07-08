"""Tests for portfolio analytics service."""
# pylint: disable=protected-access

from unittest.mock import patch

import numpy as np

from app.services import portfolio_analytics as pa


def test_annualize_stats_from_synthetic():
    rng = np.random.default_rng(0)
    closes = [100.0]
    for _ in range(100):
        closes.append(closes[-1] * np.exp(rng.normal(0.0005, 0.01)))
    rets = pa._log_returns(closes)
    ann_ret, ann_vol = pa._annualize_stats(rets)
    assert ann_vol > 0
    assert isinstance(ann_ret, float)


def test_compute_drawdown_series():
    history = [
        {"date": "2024-01-01", "total_value": 10000},
        {"date": "2024-01-02", "total_value": 11000},
        {"date": "2024-01-03", "total_value": 9900},
        {"date": "2024-01-04", "total_value": 10500},
    ]
    result = pa.compute_drawdown(history)
    assert result["has_data"] is True
    assert result["max_drawdown_pct"] < 0
    assert len(result["series"]) == 4
    assert result["series"][0]["drawdown_pct"] == 0.0


def test_compute_drawdown_empty():
    result = pa.compute_drawdown([])
    assert result["has_data"] is False
    assert not result["series"]


def test_compute_contribution_day():
    holdings = [
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "shares": 10,
            "day_change": 2.0,
            "day_change_pct": 1.5,
            "current_value": 2000.0,
            "allocation_pct": 60,
            "is_watchlist": False,
        },
        {
            "ticker": "MSFT",
            "name": "Microsoft",
            "shares": 5,
            "day_change": -1.0,
            "day_change_pct": -0.8,
            "current_value": 1333.33,
            "allocation_pct": 40,
            "is_watchlist": False,
        },
    ]
    result = pa.compute_contribution(holdings, period="day")
    assert result["has_data"] is True
    assert result["total_contribution"] == 15.0  # 10*2 + 5*(-1)
    assert result["holdings"][0]["ticker"] == "AAPL"
    assert result["holdings"][0]["name"] == "Apple Inc."
    assert result["holdings"][0]["change_pct"] == 1.5
    assert result["holdings"][0]["contribution"] == 20.0
    assert result["portfolio_value"] == 3333.33
    assert result["top_gainers"][0]["ticker"] == "AAPL"
    assert result["top_losers"][0]["ticker"] == "MSFT"
    assert result["holdings_count"] == 2
    assert result["others"] is None


def test_compute_contribution_aggregates_others():
    holdings = [
        {
            "ticker": f"T{i}",
            "name": f"Ticker {i}",
            "shares": 1,
            "day_change": float(i + 1) if i < 6 else -float(i),
            "day_change_pct": 1.0,
            "current_value": 100.0,
            "allocation_pct": 10,
            "is_watchlist": False,
        }
        for i in range(12)
    ]
    result = pa.compute_contribution(holdings, period="day")
    assert result["has_data"] is True
    assert len(result["top_gainers"]) == 5
    assert len(result["top_losers"]) == 5
    assert result["others"] is not None
    assert result["others"]["count"] == 2
    assert result["others"]["contribution"] != 0


def _range_perf_holdings():
    return [
        {"ticker": "AAPL", "shares": 10, "is_watchlist": False},
        {"ticker": "MSFT", "shares": 5, "is_watchlist": False},
        {"ticker": "WATCH", "shares": 1, "is_watchlist": True},
    ]


@patch.object(pa, "get_batched_history_closes")
def test_compute_range_performance_all_ranges(mock_history):
    # 300 trading days of linear growth: 100, 100.5, 101, …
    closes = [100.0 + i * 0.5 for i in range(300)]
    mock_history.return_value = {"AAPL": closes, "MSFT": closes}

    result = pa.compute_range_performance(_range_perf_holdings())

    assert set(result["ranges"].keys()) == set(pa.RANGE_TRADING_DAYS.keys())
    # Watchlist ticker excluded; one history fetch for the active tickers only
    mock_history.assert_called_once()
    assert sorted(mock_history.call_args[0][0]) == ["AAPL", "MSFT"]

    week = result["ranges"]["week"]
    # 5 trading days back: last=249.5, first=247.0 → +2.5/share
    assert week["holdings"]["AAPL"]["value_change"] == 25.0
    assert week["holdings"]["MSFT"]["value_change"] == 12.5
    assert week["net_change"] == 37.5
    assert week["net_change_pct"] is not None and week["net_change_pct"] > 0

    year = result["ranges"]["year"]
    # 252 trading days back from index 299 → first index 47
    expected = (closes[-1] - closes[47]) * 10
    assert abs(year["holdings"]["AAPL"]["value_change"] - expected) < 0.01


@patch.object(pa, "get_batched_history_closes")
def test_compute_range_performance_partial_history(mock_history):
    mock_history.return_value = {"AAPL": [100.0, 110.0], "MSFT": []}
    result = pa.compute_range_performance(_range_perf_holdings())
    month = result["ranges"]["month"]
    # Short history clamps to the available window; empty history is skipped
    assert month["holdings"]["AAPL"]["change_pct"] == 10.0
    assert "MSFT" not in month["holdings"]
    assert month["net_change"] == 100.0


@patch.object(pa, "get_batched_history_closes")
def test_compute_range_performance_empty(mock_history):
    result = pa.compute_range_performance([])
    mock_history.assert_not_called()
    assert not result["ranges"]["week"]["holdings"]
    assert result["ranges"]["week"]["net_change_pct"] is None


@patch.object(pa, "get_batched_history_closes")
def test_compute_range_rows_single_range(mock_history):
    closes = [100.0 + i for i in range(30)]
    mock_history.return_value = {"AAPL": closes}
    rows = pa.compute_range_rows(
        [{"ticker": "AAPL", "shares": 2, "is_watchlist": False}], "week"
    )
    assert rows["holdings"]["AAPL"]["value_change"] == 10.0  # 2 shares × 5 days × $1
    unknown = pa.compute_range_rows(
        [{"ticker": "AAPL", "shares": 2, "is_watchlist": False}], "nope"
    )
    assert not unknown["holdings"]


def test_correlation_label():
    from app.services.portfolio_analytics import _correlation_label, _market_insight
    assert _correlation_label(0.8) == "High"
    assert _correlation_label(-0.2) == "Inverse"
    assert "exposure" in _market_insight(0.6, 40, "S&P 500").lower()


@patch.object(pa, "_portfolio_index_correlations")
@patch.object(pa, "build_portfolio_exposure")
@patch.object(pa, "get_all_quotes")
def test_compute_market_context_enriches(mock_quotes, mock_exposure, mock_corr):
    mock_quotes.return_value = [{"ticker": "VOO", "current_price": 400}]
    mock_exposure.return_value = {
        "country_exposure": [{"name": "United States", "weight_pct": 61.0}],
    }
    mock_corr.return_value = {"^GSPC": 0.82, "^N225": 0.15}

    world = [
        {
            "ticker": "^GSPC",
            "name": "S&P 500",
            "region": "US",
            "flag": "🇺🇸",
            "price": 100,
            "day_change_pct": -0.1,
        },
        {
            "ticker": "^N225",
            "name": "Nikkei 225",
            "region": "Asia",
            "flag": "🇯🇵",
            "price": 200,
            "day_change_pct": -1.0,
        },
    ]
    holdings = [
        {"ticker": "VOO", "allocation_pct": 50, "current_value": 5000, "is_watchlist": False}
    ]

    pa._cache.clear()
    result = pa.compute_market_context(holdings, world)

    assert result["has_data"] is True
    assert result["markets"][0]["ticker"] == "^GSPC"
    assert result["markets"][0]["correlation"] == 0.82
    assert result["markets"][0]["geo_weight_pct"] == 61.0
    assert "S&P 500" in result["summary"]


def test_correlation_single_holding():
    holdings = [{"ticker": "VOO", "current_value": 5000, "is_watchlist": False}]
    result = pa.compute_correlation_matrix(holdings)
    assert result["tickers"] == ["VOO"]
    assert result["has_data"] is False


def test_compute_return_calendar():
    history = [
        {"date": "2024-01-05", "total_value": 10000},
        {"date": "2024-01-20", "total_value": 10500},
        {"date": "2024-02-05", "total_value": 10200},
        {"date": "2024-02-20", "total_value": 10800},
    ]
    result = pa.compute_return_calendar(history)
    assert result["has_data"] is True
    assert len(result["months"]) >= 2


def test_compute_confidence_spectrum():
    holdings = [
        {"ticker": "A", "allocation_pct": 60, "is_watchlist": False},
        {"ticker": "B", "allocation_pct": 40, "is_watchlist": False},
    ]
    signals = {"A": {"action": "hold", "confidence": 80}, "B": {"action": "trim", "confidence": 55}}
    result = pa.compute_confidence_spectrum(holdings, signals)
    assert result["has_data"] is True
    assert result["avg_confidence"] > 0


def test_compute_conviction_gaps():
    holdings = [
        {"ticker": "BIG", "allocation_pct": 30, "is_watchlist": False},
    ]
    signals = {"BIG": {"action": "trim", "confidence": 80}}
    result = pa.compute_conviction_gaps(holdings, signals)
    assert result["has_data"] is True
    assert result["gaps"][0]["ticker"] == "BIG"
