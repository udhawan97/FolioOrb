from unittest.mock import patch

from app.routers.ai import _market_pulse_status


def test_equity_market_pulse_status_reports_complete_metrics():
    status = _market_pulse_status(
        {
            "coverage_type": "equity",
            "market_cap": 100_000_000_000,
            "forward_pe": 24.5,
            "revenue_growth": 0.12,
        }
    )

    assert status == {"loaded": True, "missing": []}


def test_equity_market_pulse_status_lists_sparse_metric_groups():
    status = _market_pulse_status({"coverage_type": "equity", "market_cap": None})

    assert status["loaded"] is False
    assert status["missing"] == ["market_cap", "valuation", "quality"]


def test_fund_market_pulse_status_requires_fee_volume_and_spread():
    status = _market_pulse_status(
        {
            "coverage_type": "etf-broad",
            "expense_ratio": 0.0003,
            "volume": 5_000_000,
            "bid_ask_spread_pct": 0.0001,
        }
    )

    assert status == {"loaded": True, "missing": []}


def test_fund_market_pulse_status_lists_missing_boxes():
    status = _market_pulse_status(
        {
            "coverage_type": "etf-broad",
            "expense_ratio": 0.0003,
        }
    )

    assert status["loaded"] is False
    assert status["missing"] == ["volume", "bid_ask_spread"]


def test_single_intelligence_uses_claude_holdings_fallback_only_when_requested():
    from app.routers.ai import get_holding_intelligence_single

    stock_data = {
        "ticker": "MYST",
        "name": "Mystery ETF",
        "quote_type": "ETF",
        "day_change_pct": 0.4,
        "expense_ratio": 0.001,
        "volume": 1000,
        "average_volume": 2000,
        "bid_ask_spread_pct": 0.03,
    }
    base_intel = {
        "ticker": "MYST",
        "coverage_type": "etf-sector",
        "coverage_label": "Sector ETF",
        "strategy": "ETF tracking a sector.",
        "asset_class": "equities",
        "theme": None,
        "sectors": [],
        "countries": [],
        "top_holdings": [],
        "benchmark_tickers": ["SPY"],
        "benchmark_labels": {"SPY": "S&P 500"},
        "peer_tickers": [],
        "key_drivers": [],
        "concentration_level": "medium",
        "concentration_label": "",
        "expense_ratio": None,
        "expense_ratio_bps": None,
        "data_quality": "static",
        "data_sources": [],
    }
    ai_holdings = [
        {"ticker": "AAA", "name": "A Co", "weight": 5.0},
        {"ticker": "BBB", "name": "B Co", "weight": 4.0},
        {"ticker": "CCC", "name": "C Co", "weight": 3.0},
    ]
    ai_profile = {"aum": 1_230_000_000, "holdings": ai_holdings}

    with (
        patch("app.routers.ai.get_stock_data", return_value=stock_data),
        patch("app.routers.ai.get_holding_intelligence", return_value=object()),
        patch("app.routers.ai.intelligence_to_dict", side_effect=lambda _intel: dict(base_intel)),
        patch("app.routers.ai.generate_etf_profile_seed", return_value=ai_profile) as mock_seed,
        patch("app.routers.ai.compute_contribution_breakdown", return_value=[]),
    ):
        without_fallback = get_holding_intelligence_single("MYST", ai_holdings_fallback=False)
        with_fallback = get_holding_intelligence_single("MYST", ai_holdings_fallback=True)

    assert without_fallback["top_holdings"] == []
    assert without_fallback["aum"] is None
    assert with_fallback["top_holdings"] == ai_holdings
    assert with_fallback["aum"] == 1_230_000_000
    assert with_fallback["holdings_estimated"] is True
    assert with_fallback["aum_estimated"] is True
    assert "claude_estimate" in with_fallback["data_sources"]
    mock_seed.assert_called_once_with("MYST", "Mystery ETF")
