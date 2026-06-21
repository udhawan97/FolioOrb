"""
Tests for app/services/analyst_recommendation.py
No real network calls — yfinance is mocked throughout.
"""
from unittest.mock import MagicMock, patch

from app.services.analyst_recommendation import (
    AnalystRec,
    _action_from_mean,
    _build_subtext,
    _not_rated,
    get_analyst_recommendation,
    rec_to_dict,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_info(**kwargs):
    """Return a minimal yfinance .info dict with caller-supplied overrides."""
    defaults = {
        "quoteType": "EQUITY",
        "recommendationKey": None,
        "recommendationMean": None,
        "numberOfAnalystOpinions": None,
        "targetMeanPrice": None,
        "targetMedianPrice": None,
        "currentPrice": 100.0,
        "regularMarketPrice": 100.0,
    }
    return {**defaults, **kwargs}


def _patch_yf(info_dict):
    """Context manager that patches yf.Ticker(...).info with info_dict."""
    mock_ticker = MagicMock()
    mock_ticker.info = info_dict
    return patch("app.services.analyst_recommendation.yf.Ticker", return_value=mock_ticker)


# ── _build_subtext ────────────────────────────────────────────────────────────

class TestBuildSubtext:
    def test_count_and_upside(self):
        assert _build_subtext(18, 12.0) == "18 analysts · PT +12%"

    def test_negative_upside(self):
        assert _build_subtext(5, -8.3) == "5 analysts · PT -8%"

    def test_count_only(self):
        assert _build_subtext(10, None) == "10 analysts"

    def test_upside_only(self):
        assert _build_subtext(None, 20.0) == "PT +20%"

    def test_both_none(self):
        assert _build_subtext(None, None) == "Analyst rating unavailable"

    def test_singular_analyst(self):
        assert _build_subtext(1, None) == "1 analyst"

    def test_zero_upside(self):
        result = _build_subtext(3, 0.0)
        assert "PT +0%" in result


# ── _action_from_mean ─────────────────────────────────────────────────────────

class TestActionFromMean:
    def test_strong_buy_range(self):
        assert _action_from_mean(1.0) == "buy"
        assert _action_from_mean(2.0) == "buy"

    def test_hold_range(self):
        assert _action_from_mean(2.1) == "hold"
        assert _action_from_mean(3.5) == "hold"

    def test_sell_range(self):
        assert _action_from_mean(3.6) == "sell"
        assert _action_from_mean(5.0) == "sell"


# ── normalization from recommendationKey ─────────────────────────────────────

class TestRecommendationKeyMapping:
    def _rec(self, key):
        info = _make_info(recommendationKey=key, numberOfAnalystOpinions=10,
                          targetMeanPrice=120.0)
        with _patch_yf(info):
            return get_analyst_recommendation("NOW")

    def test_strong_buy_maps_to_buy(self):
        rec = self._rec("strong_buy")
        assert rec.action == "buy"
        assert rec.label == "Buy"

    def test_buy_maps_to_buy(self):
        assert self._rec("buy").action == "buy"

    def test_hold_maps_to_hold(self):
        rec = self._rec("hold")
        assert rec.action == "hold"
        assert rec.label == "Hold"

    def test_underperform_maps_to_sell(self):
        assert self._rec("underperform").action == "sell"

    def test_sell_maps_to_sell(self):
        assert self._rec("sell").action == "sell"

    def test_strong_sell_maps_to_sell(self):
        rec = self._rec("strong_sell")
        assert rec.action == "sell"
        assert rec.label == "Sell"


# ── fallback from recommendationMean ─────────────────────────────────────────

class TestMeanFallback:
    def test_mean_1_5_gives_buy(self):
        info = _make_info(recommendationMean=1.5, numberOfAnalystOpinions=8,
                          targetMeanPrice=115.0)
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert rec.action == "buy"

    def test_mean_3_0_gives_hold(self):
        info = _make_info(recommendationMean=3.0, numberOfAnalystOpinions=12)
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert rec.action == "hold"

    def test_mean_4_5_gives_sell(self):
        info = _make_info(recommendationMean=4.5, numberOfAnalystOpinions=6)
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert rec.action == "sell"


# ── ETF quality / unavailable fallbacks ───────────────────────────────────────

class TestNotRatedFallbacks:
    def test_etf_gets_quality_rating(self):
        info = _make_info(quoteType="ETF", recommendationKey="buy",
                          numberOfAnalystOpinions=5)
        with _patch_yf(info):
            rec = get_analyst_recommendation("VOO")
        assert rec.action == "etf-quality"
        assert rec.rating_type == "etf_quality"
        assert rec.security_type == "ETF"
        assert rec.label.startswith("ETF Quality:")
        assert rec.label != "Unavailable"

    def test_mutualfund_is_not_rated(self):
        info = _make_info(quoteType="MUTUALFUND")
        with _patch_yf(info):
            rec = get_analyst_recommendation("VTSAX")
        assert rec.action == "etf-quality"

    def test_cryptocurrency_is_not_rated(self):
        info = _make_info(quoteType="CRYPTOCURRENCY")
        with _patch_yf(info):
            rec = get_analyst_recommendation("BTC-USD")
        assert rec.action == "unavailable"

    def test_missing_key_and_mean_is_not_rated(self):
        info = _make_info(recommendationKey=None, recommendationMean=None)
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert rec.action == "unavailable"
        assert rec.label == "Unavailable"

    def test_yfinance_exception_returns_not_rated(self):
        with patch("app.services.analyst_recommendation.yf.Ticker",
                   side_effect=RuntimeError("network error")):
            rec = get_analyst_recommendation("NOW")
        assert rec.action == "unavailable"
        assert rec.subtext == "Analyst rating unavailable"

    def test_not_rated_helper(self):
        rec = _not_rated("XYZ")
        assert rec.ticker == "XYZ"
        assert rec.action == "unavailable"
        assert rec.analyst_count is None
        assert rec.target_price is None


# ── target upside calculation ────────────────────────────────────────────────

class TestTargetUpside:
    def test_upside_computed_from_target_and_price(self):
        info = _make_info(
            recommendationKey="buy",
            numberOfAnalystOpinions=20,
            targetMeanPrice=115.0,
            currentPrice=100.0,
        )
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert rec.target_upside_pct == 15.0
        assert rec.target_price == 115.0

    def test_downside_is_negative_pct(self):
        info = _make_info(
            recommendationKey="hold",
            numberOfAnalystOpinions=8,
            targetMeanPrice=90.0,
            currentPrice=100.0,
        )
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert rec.target_upside_pct == -10.0

    def test_no_target_price_omits_upside(self):
        info = _make_info(recommendationKey="buy", targetMeanPrice=None,
                          targetMedianPrice=None, numberOfAnalystOpinions=5)
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert rec.target_price is None
        assert rec.target_upside_pct is None

    def test_subtext_includes_pt_when_target_available(self):
        info = _make_info(
            recommendationKey="buy",
            numberOfAnalystOpinions=15,
            targetMeanPrice=120.0,
            currentPrice=100.0,
        )
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert "15 analysts" in rec.subtext
        assert "PT +20%" in rec.subtext

    def test_median_price_used_when_mean_absent(self):
        info = _make_info(
            recommendationKey="buy",
            targetMeanPrice=None,
            targetMedianPrice=110.0,
            currentPrice=100.0,
        )
        with _patch_yf(info):
            rec = get_analyst_recommendation("NOW")
        assert rec.target_price == 110.0
        assert rec.target_upside_pct == 10.0


# ── rec_to_dict ────────────────────────────────────────────────────────────────

class TestRecToDict:
    def test_returns_json_serializable_dict(self):
        import json
        rec = _not_rated("XYZ")
        d = rec_to_dict(rec)
        json.dumps(d)  # must not raise

    def test_dict_has_all_required_keys(self):
        rec = _not_rated("XYZ")
        d = rec_to_dict(rec)
        required = [
            "ticker", "action", "label", "analyst_count",
            "recommendation_mean", "target_price", "target_upside_pct",
            "subtext", "source",
        ]
        for key in required:
            assert key in d, f"rec_to_dict missing key: {key}"

    def test_not_rated_dict_values(self):
        d = rec_to_dict(_not_rated("IBIT"))
        assert d["action"] == "unavailable"
        assert d["label"] == "Unavailable"
        assert d["analyst_count"] is None
        assert d["target_price"] is None
        assert d["subtext"] == "Analyst rating unavailable"

    def test_buy_dict_values(self):
        rec = AnalystRec(
            ticker="NOW",
            action="buy",
            label="Buy",
            analyst_count=18,
            recommendation_mean=1.8,
            target_price=120.0,
            target_upside_pct=12.0,
            fcf_yield=None,
            subtext="18 analysts · PT +12%",
            source="yfinance",
        )
        d = rec_to_dict(rec)
        assert d["action"] == "buy"
        assert d["analyst_count"] == 18
        assert d["target_upside_pct"] == 12.0
        assert d["subtext"] == "18 analysts · PT +12%"

    def test_ticker_preserved(self):
        rec = _not_rated("VOO")
        assert rec_to_dict(rec)["ticker"] == "VOO"


# ── get_analyst_recommendation: ticker normalization ─────────────────────────

class TestTickerNormalization:
    def test_lowercase_ticker_normalized(self):
        info = _make_info(recommendationKey="buy", numberOfAnalystOpinions=5,
                          targetMeanPrice=110.0)
        with _patch_yf(info):
            rec = get_analyst_recommendation("now")
        assert rec.ticker == "NOW"

    def test_mixed_case_normalized(self):
        info = _make_info(quoteType="ETF")
        with _patch_yf(info):
            rec = get_analyst_recommendation("Voo")
        assert rec.ticker == "VOO"
        assert rec.action == "etf-quality"
