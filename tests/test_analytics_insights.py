"""
Tests for analytics insights service and GET /api/ai/analytics-insights.
"""
import json
from unittest.mock import MagicMock, patch

from app.services.analytics_insights import (
    KEY_TIP_WIDGETS,
    MODULE_DIGEST,
    WIDGET_TIP_HEADLINES,
    build_ai_analytics_prompt_snapshot,
    build_local_analytics_insights,
)


_FAKE_SNAPSHOT = {
    "as_of": "2026-06-27",
    "valuation": {"data_quality": "complete", "missing_tickers": []},
    "performance": {
        "has_holdings": True,
        "total_return_pct": 12.5,
        "today_pnl_pct": 0.8,
        "history_days": 30,
        "max_drawdown_pct": -5.2,
    },
    "risk": {
        "has_data": True,
        "concentration_hhi": 0.35,
        "portfolio_vol_pct": 18.0,
        "max_drawdown_pct": -5.2,
        "top_sector": "Technology",
    },
    "exposure": {
        "has_data": True,
        "top_sectors": [{"name": "Technology", "weight_pct": 42.0}],
        "top_countries": [{"name": "United States", "weight_pct": 65.0}],
    },
    "signals": {
        "has_data": True,
        "dominant_action": "hold",
        "hold_weight_pct": 70.0,
        "add_weight_pct": 20.0,
        "trim_weight_pct": 10.0,
        "avg_confidence": 72,
    },
    "markets": {
        "has_data": True,
        "best_match_name": "S&P 500",
        "best_correlation": 0.82,
        "us_exposure_pct": 65.0,
        "summary": "Moves with US equities.",
    },
}

_AI_INSIGHTS = {
    "performance": "Your portfolio is up 12.5% overall with a steady 0.8% gain today.",
    "risk": "Technology concentration keeps volatility near 18% annually.",
    "exposure": "Technology dominates your look-through book at 42%.",
    "signals": "Most of the book sits on hold with solid confidence.",
    "markets": "Your holdings track the S&P 500 more closely than other regions.",
}

_AI_WIDGET_INSIGHTS = {
    # Key widgets must return structured objects
    "benchmark-tracker": {
        "headline": "Benchmark shows if you're ahead of the market",
        "insight": "You are beating the S&P 500 over the past year.",
    },
    "beta-dial": {
        "headline": "Beta measures your market sensitivity",
        "insight": "Beta near 1.0 means your book moves in step with the market.",
    },
    # Non-key widget stays as a plain string
    "total-return": "All-in return is +12.5% with +0.8% today.",
}


def test_ai_prompt_snapshot_omits_non_key_widget_data():
    full = {
        **_FAKE_SNAPSHOT,
        "widgets": {
            "benchmark": {"has_data": True},
            "beta": {"has_data": True, "beta": 1.05},
            "return_calendar": {"has_data": True, "months": [{"return_pct": 1.0}]},
            "market_sensitivity": {"has_data": True, "indices": [{"name": "S&P 500"}]},
        },
    }
    slim = build_ai_analytics_prompt_snapshot(full)
    assert slim["valuation"] == {"data_quality": "complete", "missing_tickers": []}
    assert "return_calendar" not in slim["widgets"]
    assert "market_sensitivity" not in slim["widgets"]
    assert "benchmark" in slim["widgets"]
    assert "summary" not in slim["markets"]


def test_local_insights_include_digest_and_one_liners():
    payload = build_local_analytics_insights(_FAKE_SNAPSHOT)
    assert payload["mode"] == "local"
    assert payload["digest"] == MODULE_DIGEST
    assert "performance" in payload["insights"]
    assert "risk" in payload["insights"]
    assert "+12.5%" in payload["insights"]["performance"]
    assert payload["insights"]["exposure"].startswith("Largest look-through")
    assert "widget_insights" in payload
    wids = payload["widget_insights"]
    assert "total-return" in wids or "benchmark-tracker" in wids


def test_local_widget_insights_key_widgets_are_structured():
    """Key widgets return {headline, insight} dicts; others stay strings."""
    payload = build_local_analytics_insights(_FAKE_SNAPSHOT)
    wids = payload["widget_insights"]
    for key in KEY_TIP_WIDGETS:
        if key in wids:
            val = wids[key]
            assert isinstance(val, dict), f"{key} should be a dict"
            assert "headline" in val and "insight" in val
            assert val["headline"] == WIDGET_TIP_HEADLINES[key]
            assert len(val["insight"]) > 0
    # Non-key widgets must be plain strings
    for key, val in wids.items():
        if key not in KEY_TIP_WIDGETS:
            assert isinstance(val, str), f"{key} should be a plain string"


def test_analytics_insights_local_endpoint():
    from app.routers.ai import get_analytics_insights

    db = MagicMock()
    with patch(
        "app.services.analytics_insights.build_analytics_snapshot",
        return_value=_FAKE_SNAPSHOT,
    ):
        result = get_analytics_insights(mode="local", force_refresh=False, db=db)
    assert result["mode"] == "local"
    assert result["digest"]["risk"] == MODULE_DIGEST["risk"]
    assert "insights" in result


def test_analytics_insights_ai_endpoint_uses_claude():
    from app.routers.ai import get_analytics_insights

    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    with patch(
        "app.services.analytics_insights.build_analytics_snapshot",
        return_value=_FAKE_SNAPSHOT,
    ), patch(
        "app.routers.ai.generate_analytics_insights",
        return_value={"insights": _AI_INSIGHTS, "widget_insights": _AI_WIDGET_INSIGHTS},
    ):
        result = get_analytics_insights(mode="ai", force_refresh=True, db=db)

    assert result["mode"] == "ai"
    assert result["source"] == "claude"
    assert result["widget_insights_version"] == 2
    assert result["insights"]["markets"] == _AI_INSIGHTS["markets"]
    db.add.assert_called_once()
    db.commit.assert_called_once()

    # Structured key-widget values should be preserved in the merged output
    wids = result["widget_insights"]
    bt = wids.get("benchmark-tracker")
    assert isinstance(bt, dict), "benchmark-tracker should be a structured dict"
    assert bt["insight"] == _AI_WIDGET_INSIGHTS["benchmark-tracker"]["insight"]
    assert isinstance(wids.get("total-return"), str), "total-return should stay a plain string"
    assert "correlation" not in wids, "local-only widgets must not be backfilled into AI tips"


def test_analytics_insights_partial_valuation_skips_claude():
    from app.routers.ai import get_analytics_insights

    partial_snapshot = {
        **_FAKE_SNAPSHOT,
        "valuation": {
            "data_quality": "partial",
            "missing_tickers": ["MSFT"],
            "priced_position_count": 1,
            "expected_position_count": 2,
        },
    }
    db = MagicMock()

    with patch(
        "app.services.analytics_insights.build_analytics_snapshot",
        return_value=partial_snapshot,
    ), patch("app.routers.ai.generate_analytics_insights") as gen_mock:
        result = get_analytics_insights(mode="ai", force_refresh=True, db=db)

    gen_mock.assert_not_called()
    assert result["source"] == "local-fallback"
    assert result["data_quality"] == "partial"
    assert result["missing_tickers"] == ["MSFT"]
    assert "partial" in result["insights"]["performance"]


def test_analytics_insights_ai_serves_cache():
    from datetime import datetime, timezone

    from app.models import AISummary
    from app.routers.ai import get_analytics_insights

    cached_payload = {
        "mode": "ai",
        "source": "claude",
        "insights": _AI_INSIGHTS,
        "widget_insights": _AI_WIDGET_INSIGHTS,
        "widget_insights_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    cached = AISummary(
        ticker="BOOK",
        summary_type="analytics_insights",
        summary_text=json.dumps(cached_payload),
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = cached

    with patch("app.services.analytics_insights.build_analytics_snapshot") as snap_mock, patch(
        "app.routers.ai.generate_analytics_insights"
    ) as gen_mock:
        result = get_analytics_insights(mode="ai", force_refresh=False, db=db)

    assert result["from_cache"] is True
    assert result["insights"]["risk"] == _AI_INSIGHTS["risk"]
    snap_mock.assert_not_called()
    gen_mock.assert_not_called()
