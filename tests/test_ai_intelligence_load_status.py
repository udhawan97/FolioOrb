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
