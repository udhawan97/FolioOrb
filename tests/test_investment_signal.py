"""
Tests for app/services/investment_signal.py and related verdict infrastructure.
No real network calls — AnalystRec objects are constructed directly.
"""
# pylint: disable=protected-access
import json
import asyncio
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import AISummary, Base, Holding, Portfolio
from app.routers import ai as ai_router
from app.services.analyst_recommendation import AnalystRec
from app.services.investment_signal import (
    _derive_etf_market_mood,
    _derive_stock_market_mood,
    _needs_data,
    _valuation_component_score,
    build_investment_signal,
    signal_to_dict,
)
from app.services.ai_service import fallback_quip, generate_verdict_quips


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _stock_rec(action="buy", count=15, mean=1.8, upside=12.0, fcf=None):
    return AnalystRec(
        ticker="NOW",
        action=action,
        label={"buy": "Buy", "hold": "Hold", "sell": "Sell"}.get(action, "Unavailable"),
        analyst_count=count,
        recommendation_mean=mean,
        target_price=120.0,
        target_upside_pct=upside,
        fcf_yield=fcf,
        subtext="test",
        source="yfinance",
        security_type="STOCK",
        rating_type="analyst",
    )


def _unavailable_rec(fcf=None, ticker="XYZ"):
    return AnalystRec(
        ticker=ticker,
        action="unavailable",
        label="Unavailable",
        analyst_count=None,
        recommendation_mean=None,
        target_price=None,
        target_upside_pct=None,
        fcf_yield=fcf,
        subtext="Analyst rating unavailable",
        source="yfinance",
        security_type="STOCK",
        rating_type="analyst",
    )


def _etf_rec(
    zone="Fair",
    quality_score=75,
    category_risk="Low",
    quality_label="Strong",
    price_overrides=None,
):
    price_signal = {
        "priceZoneLabel": zone,
        "percentile": {
            "Bargain": 5.0,
            "Fair": 50.0,
            "Elevated": 65.0,
            "Rich": 95.0,
        }.get(zone, 50.0),
        "dataWarnings": [],
    }
    if price_overrides:
        price_signal.update(price_overrides)
    etf_quality = {
        "score": quality_score,
        "qualityLabel": quality_label,
        "costLabel": "Low",
        "liquidityLabel": "High",
        "diversificationLabel": "Broad",
        "categoryRiskLabel": category_risk,
        "category": "broad",
    }
    return AnalystRec(
        ticker="VOO",
        action="etf-quality",
        label=f"ETF Quality: {quality_label}",
        analyst_count=None,
        recommendation_mean=None,
        target_price=None,
        target_upside_pct=None,
        fcf_yield=None,
        subtext="Low cost · High liquidity",
        source="etf-quality",
        security_type="ETF",
        rating_type="etf_quality",
        etf_quality=etf_quality,
        price_signal=price_signal,
    )


def _stock_quote(price=100.0, low=50.0, high=120.0, day_change_pct=0.2, ticker="NOW"):
    return {
        "ticker": ticker,
        "current_price": price,
        "day_change_pct": day_change_pct,
        "fifty_two_week_low": low,
        "fifty_two_week_high": high,
        "error": None,
    }


def _make_ai_db(tickers=("NOW",), shares=10):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    db.add(Portfolio(id=1, name="Test Portfolio"))
    for ticker in tickers:
        db.add(
            Holding(
                portfolio_id=1,
                ticker=ticker,
                shares=shares,
                avg_cost=100,
                is_active=True,
            )
        )
    db.commit()
    return db


def _timing(
    *,
    state="neutral",
    cross_type=None,
    sessions_ago=6,
    near_low=False,
    vs50=1.0,
    vs200=2.0,
    drawdown=8.0,
):
    return {
        "available": True,
        "momentum_state": state,
        "cross": (
            {"type": cross_type, "sessions_ago": sessions_ago, "recent": sessions_ago <= 20}
            if cross_type else None
        ),
        "vs50d_pct": vs50,
        "vs200d_pct": vs200,
        "drawdown_from_52w_high_pct": drawdown,
        "near_52w_low": near_low,
        "bucket": state,
    }


# ── Stock buy/hold/sell → add/hold/trim mapping ────────────────────────────────

class TestStockActionMapping:
    def test_buy_maps_to_add(self):
        sig = build_investment_signal(_stock_rec("buy"))
        assert sig.action == "add"
        assert sig.label == "Add"

    def test_hold_maps_to_hold(self):
        sig = build_investment_signal(_stock_rec("hold", mean=3.0, upside=1.0))
        assert sig.action == "hold"
        assert sig.label == "Hold"

    def test_sell_maps_to_trim(self):
        sig = build_investment_signal(_stock_rec("sell", mean=4.5, upside=-8.0))
        assert sig.action == "trim"
        assert sig.label == "Trim"


# ── Confidence bounds ──────────────────────────────────────────────────────────

class TestConfidenceBounds:
    def test_confidence_is_0_to_100(self):
        for action in ("buy", "hold", "sell"):
            sig = build_investment_signal(_stock_rec(action))
            assert 0 <= sig.confidence <= 100, f"confidence out of range for {action}"

    def test_unavailable_no_fcf_is_needs_data_with_0_confidence(self):
        sig = build_investment_signal(_unavailable_rec(fcf=None))
        assert sig.action == "needs-data"
        assert sig.confidence == 0

    def test_needs_data_sentinel_confidence(self):
        sig = _needs_data("ABC")
        assert sig.confidence == 0
        assert sig.action == "needs-data"

    def test_no_analyst_fcf_high_confidence_capped_at_45(self):
        sig = build_investment_signal(_unavailable_rec(fcf=8.0))
        assert sig.confidence <= 45

    def test_strong_buy_conviction_boosts_confidence(self):
        sig_strong = build_investment_signal(_stock_rec("buy", count=25, mean=1.0, upside=25.0))
        sig_weak   = build_investment_signal(_stock_rec("buy", count=2,  mean=2.8, upside=2.0))
        assert sig_strong.confidence > sig_weak.confidence


# ── ETF price-zone → action mapping ───────────────────────────────────────────

class TestEtfActionMapping:
    def test_bargain_zone_gives_add(self):
        sig = build_investment_signal(_etf_rec("Bargain"))
        assert sig.action == "add"

    def test_fair_zone_gives_hold(self):
        sig = build_investment_signal(_etf_rec("Fair"))
        assert sig.action == "hold"

    def test_elevated_zone_gives_hold(self):
        sig = build_investment_signal(_etf_rec("Elevated"))
        assert sig.action == "hold"

    def test_rich_zone_gives_trim(self):
        sig = build_investment_signal(_etf_rec("Rich"))
        assert sig.action == "trim"

    def test_unavailable_zone_gives_needs_data(self):
        sig = build_investment_signal(_etf_rec("Unavailable"))
        assert sig.action == "needs-data"
        assert sig.confidence == 0


# ── market mood + momentum refinements ────────────────────────────────────────

class TestMarketMood:
    def test_etf_market_mood_hot_from_price_signal(self):
        mood = _derive_etf_market_mood({
            "percentile": 88,
            "vs50dPct": 3.2,
            "vs200dPct": 8.5,
            "vs30dChangePct": 2.4,
            "vs200dChangePct": 9.0,
        })
        assert mood == "hot"

    def test_stock_market_mood_cold_from_quote_fields(self):
        mood = _derive_stock_market_mood(
            _stock_quote(price=54, low=50, high=120, day_change_pct=-1.2)
        )
        assert mood == "cold"

    def test_neutral_momentum_keeps_hold_default(self):
        sig = build_investment_signal(
            _stock_rec("hold", mean=3.0, upside=1.0),
            stock_data=_stock_quote(price=83, low=50, high=120, day_change_pct=0.0),
        )
        assert sig.action == "hold"
        assert sig.market_mood == "neutral"

    def test_rich_etf_strong_uptrend_holds_instead_of_trim(self):
        sig = build_investment_signal(_etf_rec("Rich", price_overrides={
            "percentile": 92,
            "vs50dPct": 4.0,
            "vs200dPct": 11.0,
            "vs30dChangePct": 3.0,
            "vs200dChangePct": 12.0,
        }))
        assert sig.market_mood == "hot"
        assert sig.action == "hold"
        assert any("trend" in reason.lower() for reason in sig.reasons)

    def test_bargain_etf_falling_is_hold_with_lower_conviction(self):
        improving = build_investment_signal(_etf_rec("Bargain", price_overrides={
            "percentile": 10,
            "vs50dPct": 3.0,
            "vs200dPct": 7.0,
            "vs30dChangePct": 2.5,
            "vs200dChangePct": 6.0,
        }))
        falling = build_investment_signal(_etf_rec("Bargain", price_overrides={
            "percentile": 8,
            "vs50dPct": -4.0,
            "vs200dPct": -9.0,
            "vs30dChangePct": -3.0,
            "vs200dChangePct": -8.0,
        }))
        assert improving.action == "add"
        assert falling.action == "hold"
        assert falling.confidence < improving.confidence
        assert any("watched" in reason.lower() for reason in falling.reasons)


# ── Speculative gate ───────────────────────────────────────────────────────────

class TestSpeculativeGate:
    def test_speculative_bargain_capped_at_hold(self):
        sig = build_investment_signal(_etf_rec("Bargain", category_risk="Speculative"))
        assert sig.action == "hold", "Speculative ETF in Bargain zone must not output 'add'"

    def test_speculative_risk_bullet_present(self):
        sig = build_investment_signal(_etf_rec("Bargain", category_risk="Speculative"))
        risk_text = " ".join(sig.risks)
        assert "speculative" in risk_text.lower() or "Speculative" in risk_text

    def test_non_speculative_bargain_is_add(self):
        sig = build_investment_signal(_etf_rec("Bargain", category_risk="Low"))
        assert sig.action == "add"


class TestAnchorAndRole:
    def test_anchor_never_trims_even_when_rich_and_concentrated(self):
        sig = build_investment_signal(
            _etf_rec("Rich", price_overrides={"percentile": 95}),
            allocation_pct=28,
            hold_class="anchor",
            timing=_timing(state="rolling_over", cross_type="death"),
        )
        assert sig.action != "trim"
        assert sig.hold_class == "anchor"
        assert sig.instrument_role == "anchor"
        assert any("Anchor hold" in reason for reason in sig.reasons)

    def test_anchor_emits_buy_more_state_on_weakness(self):
        sig = build_investment_signal(
            _etf_rec("Bargain", price_overrides={"percentile": 8}),
            hold_class="anchor",
            timing=_timing(state="trend_intact", near_low=True, vs50=-4.0, vs200=2.5),
        )
        assert sig.action == "add"
        assert sig.label == "Add (anchor)"
        assert any("add to your anchor" in reason for reason in sig.reasons)

    def test_broad_core_etf_stays_hold_under_mild_rich_noise(self):
        sig = build_investment_signal(
            _etf_rec("Rich", price_overrides={"percentile": 84}),
            timing=_timing(state="trend_intact"),
        )
        assert sig.instrument_role == "core"
        assert sig.action == "hold"

    def test_tactical_rich_rolling_over_trims(self):
        rec = _etf_rec("Rich", price_overrides={"percentile": 92})
        rec.etf_quality["category"] = "sector"
        sig = build_investment_signal(
            rec,
            timing=_timing(state="rolling_over", cross_type="death", sessions_ago=6),
        )
        assert sig.instrument_role == "tactical"
        assert sig.action == "trim"
        assert "50-day crossed below" in sig.reasons[0]

    def test_tactical_bargain_golden_cross_adds(self):
        rec = _etf_rec("Bargain", price_overrides={"percentile": 10})
        rec.etf_quality["category"] = "thematic"
        sig = build_investment_signal(
            rec,
            timing=_timing(state="stabilizing", cross_type="golden", sessions_ago=4),
        )
        assert sig.instrument_role == "tactical"
        assert sig.action == "add"
        assert "50-day crossed above" in sig.reasons[0]


# ── Allocation risk modifier ───────────────────────────────────────────────────

class TestAllocationRisk:
    def test_high_allocation_adds_risk_bullet(self):
        sig = build_investment_signal(_stock_rec("buy"), allocation_pct=15.0)
        risk_text = " ".join(sig.risks)
        assert "concentration" in risk_text.lower()

    def test_high_allocation_add_softens_confidence(self):
        sig_no_alloc = build_investment_signal(_stock_rec("buy"))
        sig_high_alloc = build_investment_signal(
            _stock_rec("buy"), allocation_pct=15.0
        )
        assert sig_high_alloc.confidence <= sig_no_alloc.confidence

    def test_watchlist_skips_concentration_penalty(self):
        sig_watchlist = build_investment_signal(
            _stock_rec("buy"), allocation_pct=15.0, is_watchlist=True
        )
        # watchlist should not have concentration risk bullet
        risk_text = " ".join(sig_watchlist.risks)
        assert "concentration" not in risk_text.lower()

    def test_low_allocation_no_risk_bullet(self):
        sig = build_investment_signal(_stock_rec("buy"), allocation_pct=2.0)
        risk_text = " ".join(sig.risks)
        assert "concentration" not in risk_text.lower()


# ── needs-data path ────────────────────────────────────────────────────────────

class TestNeedsData:
    def test_needs_data_has_no_reasons(self):
        sig = _needs_data("ABC")
        assert not sig.reasons

    def test_needs_data_has_generic_risk(self):
        sig = _needs_data("ABC")
        assert len(sig.risks) >= 1

    def test_unavailable_no_fcf_needs_data(self):
        sig = build_investment_signal(_unavailable_rec())
        assert sig.action == "needs-data"

    def test_exception_in_build_returns_needs_data(self):
        bad_rec = MagicMock(spec=AnalystRec)
        bad_rec.ticker = "ERR"
        bad_rec.security_type = "STOCK"
        bad_rec.action = "buy"
        bad_rec.analyst_count = None
        bad_rec.recommendation_mean = None
        bad_rec.target_upside_pct = None
        bad_rec.fcf_yield = None
        # Make something blow up inside the scorer
        type(bad_rec).action = property(lambda s: (_ for _ in ()).throw(RuntimeError("oops")))
        sig = build_investment_signal(bad_rec)
        assert sig.action == "needs-data"


# ── source_fields populated ────────────────────────────────────────────────────

class TestSourceFields:
    def test_stock_buy_has_source_fields(self):
        sig = build_investment_signal(_stock_rec("buy"))
        assert len(sig.source_fields) >= 1
        assert "action" in sig.source_fields

    def test_etf_has_price_signal_source(self):
        sig = build_investment_signal(_etf_rec("Bargain"))
        assert any("price_signal" in s for s in sig.source_fields)

    def test_allocation_adds_source_field(self):
        sig = build_investment_signal(_stock_rec("buy"), allocation_pct=15.0)
        assert "allocation_pct" in sig.source_fields


# ── signal_to_dict ─────────────────────────────────────────────────────────────

class TestSignalToDict:
    def test_returns_json_serializable_dict(self):
        sig = build_investment_signal(_stock_rec("buy"))
        d = signal_to_dict(sig)
        json.dumps(d)  # must not raise

    def test_dict_has_all_required_keys(self):
        sig = build_investment_signal(_stock_rec("buy"))
        d = signal_to_dict(sig)
        for key in ("ticker", "action", "label", "confidence", "reasons",
                    "market_mood", "risks", "data_quality", "source_fields", "generated_at",
                    "flip_triggers", "signal_mix", "freshness", "confidence_detail"):
            assert key in d, f"signal_to_dict missing key: {key}"

    def test_stock_signal_includes_static_verdict_addons(self):
        sig = build_investment_signal(
            _stock_rec("buy"),
            stock_data=_stock_quote(price=90, low=50, high=120),
        )
        d = signal_to_dict(sig)
        assert d["flip_triggers"]["add_price"] < d["flip_triggers"]["trim_price"]
        assert [item["label"] for item in d["signal_mix"]] == [
            "Analyst", "Valuation", "Momentum", "Quality",
        ]
        assert d["freshness"]["label"] == "Fresh now"

    def test_etf_signal_includes_static_verdict_addons(self):
        sig = build_investment_signal(_etf_rec("Bargain", price_overrides={
            "currentPrice": 80.0,
            "lowPrice": 70.0,
            "highPrice": 110.0,
        }))
        d = signal_to_dict(sig)
        assert d["flip_triggers"] == {"add_price": 80.0, "trim_price": 102.0}
        assert any(item["label"] == "Quality" for item in d["signal_mix"])


class TestConfidenceDetail:
    def test_confidence_detail_has_components(self):
        sig = build_investment_signal(_etf_rec("Fair"))
        detail = sig.confidence_detail
        assert detail is not None
        assert detail["score"] == sig.confidence
        assert len(detail["components"]) == 4
        assert detail["level"]
        assert detail["summary"]

    def test_component_scores_in_range(self):
        sig = build_investment_signal(_stock_rec("buy"))
        for comp in sig.confidence_detail["components"]:
            assert 0 <= comp["score"] <= 100
            assert comp["label"]
            assert comp["tip_title"]
            assert comp["tip_body"]

    def test_anchor_confidence_stays_moderate_band(self):
        sig = build_investment_signal(
            _etf_rec("Rich", price_overrides={"percentile": 95}),
            hold_class="anchor",
        )
        assert sig.hold_class == "anchor"
        assert 45 <= sig.confidence <= 68

    def test_allocation_modifier_in_detail(self):
        sig = build_investment_signal(_stock_rec("buy"), allocation_pct=15.0)
        modifiers = sig.confidence_detail.get("modifiers") or []
        assert any("portfolio" in m["label"].lower() for m in modifiers)


# ── fallback_quip ──────────────────────────────────────────────────────────────

class TestFallbackQuip:
    @pytest.mark.parametrize("action", ["add", "hold", "trim", "needs-data"])
    def test_returns_non_empty_sentence(self, action):
        q = fallback_quip(action)
        assert isinstance(q, str)
        assert len(q) > 0

    def test_unknown_action_returns_string(self):
        q = fallback_quip("unknown-action")
        assert isinstance(q, str)
        assert len(q) > 0

    def test_rotates_across_calls(self):
        results = {fallback_quip("add") for _ in range(4)}
        assert len(results) > 1, "fallback_quip should rotate through templates"


# ── generate_verdict_quips ─────────────────────────────────────────────────────

class TestGenerateVerdictQuips:
    def test_returns_empty_dict_on_api_error(self):
        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.side_effect = Exception("network error")
            result = generate_verdict_quips([
                {"ticker": "NOW", "action": "add", "confidence": 72, "reason": "Analysts bullish"}
            ])
        assert not result

    def test_returns_empty_dict_on_empty_signals(self):
        result = generate_verdict_quips([])
        assert not result

    def test_parses_valid_json_response(self):
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = (
            '{"NOW": {"q": "Quietly stacking gains like nobody is watching.", '
            '"n": 2, "cn": [0,0,0,0]}}'
        )
        mock_msg.content = [mock_block]
        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = generate_verdict_quips([
                {
                    "ticker": "NOW",
                    "action": "add",
                    "confidence": 72,
                    "reason": "Analysts bullish",
                    "mix": "An:s",
                }
            ])
        assert "NOW" in result
        assert isinstance(result["NOW"], str)
        assert len(result["NOW"]) > 0

    def test_parses_json_with_code_fence(self):
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = (
            '```json\n{"VOO": {"q": "The index never blinked.", '
            '"n": 0, "cn": [0,0,0,0]}}\n```'
        )
        mock_msg.content = [mock_block]
        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = generate_verdict_quips([
                {
                    "ticker": "VOO",
                    "action": "hold",
                    "confidence": 55,
                    "reason": "Fair value zone",
                    "mix": "Val:n",
                }
            ])
        assert "VOO" in result


# ── route cache keys + brand serialization ────────────────────────────────────

def test_verdict_quip_cache_uses_action_and_market_mood(monkeypatch):
    db = _make_ai_db(("NOW",))
    quote_state = {"quote": _stock_quote(price=100, low=50, high=120, day_change_pct=0.1)}
    calls = []

    monkeypatch.setattr(ai_router, "get_all_quotes", lambda _tickers: [quote_state["quote"]])
    monkeypatch.setattr(ai_router, "get_batched_history_closes", lambda _tickers: {})
    monkeypatch.setattr(
        ai_router,
        "get_analyst_recommendation",
        lambda _ticker, closes=None: _stock_rec("buy"),
    )

    def fake_generate(inputs):
        calls.append(inputs)
        return {
            item["ticker"]: {
                "quip": f"quip {item['ticker']} {len(calls)}",
                "ai": {"n": 1, "cn": [0, 0, 0, 0], "h": "Test", "t": []},
            }
            for item in inputs
        }

    monkeypatch.setattr(ai_router, "generate_verdict_ai_bundles", fake_generate)

    first = asyncio.run(ai_router.get_all_investment_signals(db))
    assert first["signals"]["NOW"]["market_mood"] == "warm"
    assert len(calls) == 1

    quote_state["quote"] = _stock_quote(price=101, low=50, high=120, day_change_pct=0.1)
    second = asyncio.run(ai_router.get_all_investment_signals(db))
    assert second["signals"]["NOW"]["market_mood"] == "warm"
    assert len(calls) == 1, "same action + mood should reuse cached Claude quip"

    quote_state["quote"] = _stock_quote(price=54, low=50, high=120, day_change_pct=-1.1)
    third = asyncio.run(ai_router.get_all_investment_signals(db))
    assert third["signals"]["NOW"]["market_mood"] == "cold"
    assert len(calls) == 2, "mood flip should request a fresh quip"
    assert set(calls[0][0]) == {"ticker", "action", "confidence", "market_mood", "reason", "mix"}


def test_verdict_quip_key_includes_hold_class_and_timing_bucket():
    auto_key = ai_router._verdict_summary_type("hold", "neutral", "auto", "trend_intact")
    anchor_key = ai_router._verdict_summary_type("hold", "neutral", "anchor", "trend_intact")
    timing_key = ai_router._verdict_summary_type("hold", "neutral", "auto", "death-recent")

    assert auto_key != anchor_key
    assert auto_key != timing_key


def test_all_signals_passes_batched_history_into_recommendation(monkeypatch):
    db = _make_ai_db(("VOO",))
    received = {}
    closes = [100] * 210 + [102, 104, 106, 108, 110]

    monkeypatch.setattr(
        ai_router,
        "get_all_quotes",
        lambda _tickers: [_stock_quote(price=110, low=90, high=120, ticker="VOO")],
    )
    monkeypatch.setattr(ai_router, "get_batched_history_closes", lambda _tickers: {"VOO": closes})

    def fake_rec(ticker, closes=None):
        received[ticker] = closes
        return _etf_rec("Fair")

    monkeypatch.setattr(ai_router, "get_analyst_recommendation", fake_rec)
    monkeypatch.setattr(ai_router, "generate_verdict_ai_bundles", lambda inputs: {})

    result = asyncio.run(ai_router.get_all_investment_signals(db))

    assert received["VOO"] is closes
    assert result["signals"]["VOO"]["timing"]["cross"]["type"] == "golden"


def test_portfolio_quip_cache_and_fallback(monkeypatch):
    db = _make_ai_db(("AAA", "BBB"))
    recs = {
        "AAA": _stock_rec("hold", mean=3.0, upside=1.0),
        "BBB": _stock_rec("hold", mean=3.0, upside=1.0),
    }
    calls = []

    monkeypatch.setattr(
        ai_router,
        "get_all_quotes",
        lambda _tickers: [
            _stock_quote(price=80, low=50, high=120, day_change_pct=0.0, ticker="AAA"),
            _stock_quote(price=80, low=50, high=120, day_change_pct=0.0, ticker="BBB"),
        ],
    )
    monkeypatch.setattr(ai_router, "get_batched_history_closes", lambda _tickers: {})
    monkeypatch.setattr(
        ai_router,
        "get_analyst_recommendation",
        lambda ticker, closes=None: recs[ticker],
    )

    def fail_generate(inputs):
        calls.append(inputs)
        return {}

    monkeypatch.setattr(ai_router, "generate_verdict_ai_bundles", fail_generate)

    first = asyncio.run(ai_router.get_all_investment_signals(db))
    assert "portfolio_health" in first
    assert first["portfolio_health"]["quip"]
    assert first["portfolio_health"]["brand"]["kicker"] == ai_router.VERDICT_BRAND_KICKER_LOCAL
    assert "FolioOrb" in first["signals"]["AAA"]["disclaimer"]
    assert len(calls) == 1

    asyncio.run(ai_router.get_all_investment_signals(db))
    assert len(calls) == 1, (
        "portfolio quip should reuse cache when coarse state is unchanged"
    )

    recs["AAA"] = _stock_rec("sell", mean=4.5, upside=-15.0)
    recs["BBB"] = _stock_rec("sell", mean=4.5, upside=-15.0)
    changed = asyncio.run(ai_router.get_all_investment_signals(db))
    assert changed["portfolio_health"]["dominant_action"] == "trim"
    assert len(calls) == 2, "portfolio quip should refresh when state signature changes"

    cached_rows = db.query(AISummary).filter(AISummary.ticker == "BOOK").all()
    assert cached_rows


def test_confidence_detail_has_range_and_scenarios():
    sig = build_investment_signal(_etf_rec("Fair"))
    detail = sig.confidence_detail
    assert "range_low" in detail
    assert "range_high" in detail
    assert detail["range_high"] >= detail["range_low"]
    assert "base" in detail["scenarios"]
    assert "bull" in detail["scenarios"]
    assert "bear" in detail["scenarios"]
    forecast = detail["scenarios"].get("forecast") or {}
    assert forecast.get("likely") in ("base", "bull", "bear")
    probs = forecast.get("probabilities") or {}
    assert sum(probs.values()) == 100


def test_horizon_trade_weights_momentum_heavier():
    from app.services.investment_signal import _horizon_weights
    trade = _horizon_weights("trade", is_etf=False)
    auto = _horizon_weights("auto", is_etf=False)
    assert trade["momentum"] > auto["momentum"]
    assert trade["valuation"] <= auto["valuation"]


def test_regime_modifier_in_confidence():
    regime = {
        "label": "Risk-off",
        "component_adjustments": {"analyst": 0, "valuation": 2, "momentum": -4, "quality": 4},
        "tip_title": "Market backdrop",
        "tip_body": "Test",
    }
    sig = build_investment_signal(_etf_rec("Fair"), regime=regime)
    mod_labels = [m["label"] for m in sig.confidence_detail.get("modifiers") or []]
    assert any("Market backdrop" in lbl for lbl in mod_labels)


def test_exposure_context_penalizes_add():
    exposure_ctx = {
        "crowded_themes": [{"theme": "US tech", "weight_pct": 40, "label": "~40% US tech"}],
    }
    sig = build_investment_signal(_etf_rec("Bargain"), exposure_context=exposure_ctx)
    mod_labels = [m["label"] for m in sig.confidence_detail.get("modifiers") or []]
    assert any("Book already heavy" in lbl for lbl in mod_labels)


def test_earnings_cap_on_add():
    event = {
        "confidence_cap": 55,
        "tip_title": "Earnings",
        "tip_body": "Soon",
        "risk_note": "Earnings soon",
    }
    sig = build_investment_signal(_stock_rec("buy"), event_context=event)
    if sig.action == "add":
        assert sig.confidence <= 55


# ── Valuation component score: zone/action alignment ──────────────────────────
# Bargain supports "add"; Rich supports "trim" (see TestEtfActionMapping above,
# and _apply_anchor_override's own zone→action stance map). The trim score must
# invert the add-scale, not reuse it verbatim, or a cheap (Bargain) stock scores
# a HIGH confidence to trim it — backwards.

class TestValuationComponentScoreZoneActionAlignment:
    def test_trim_scores_low_on_bargain_zone(self):
        score = _valuation_component_score(
            action="trim", upside=None, zone="Bargain", percentile=15,
        )
        assert score < 50

    def test_trim_scores_high_on_rich_zone(self):
        score = _valuation_component_score(
            action="trim", upside=None, zone="Rich", percentile=85,
        )
        assert score > 50

    def test_add_still_scores_high_on_bargain_zone(self):
        score = _valuation_component_score(
            action="add", upside=None, zone="Bargain", percentile=15,
        )
        assert score > 50

    def test_add_still_scores_low_on_rich_zone(self):
        score = _valuation_component_score(
            action="add", upside=None, zone="Rich", percentile=85,
        )
        assert score < 50
