"""Tests for Claude verdict synthesis merge layer."""
from app.services.investment_signal import build_investment_signal, signal_to_dict
from app.services.verdict_ai_enhancement import (
    apply_ai_enhancement,
    compact_signal_mix,
    decode_verdict_cache,
    encode_verdict_cache,
    normalize_ai_bundle,
    parse_ai_bundle_response,
)
from tests.test_investment_signal import _etf_rec


def test_compact_signal_mix():
    mix = [
        {"label": "Analyst", "stance": "neutral"},
        {"label": "Valuation", "stance": "support"},
        {"label": "Momentum", "stance": "neutral"},
        {"label": "Quality", "stance": "support"},
    ]
    assert compact_signal_mix(mix) == "An:n Val:s Mom:n Qual:s"


def test_encode_decode_verdict_cache_roundtrip():
    ai = {"n": 4, "h": "Steady core", "cn": [0, 2, 0, 3], "t": ["anchor"]}
    raw = encode_verdict_cache("Quiet compounding.", ai)
    decoded = decode_verdict_cache(raw)
    assert decoded["quip"] == "Quiet compounding."
    assert decoded["ai"]["overall_nudge"] == 4


def test_decode_plain_text_cache_backward_compat():
    decoded = decode_verdict_cache("Legacy quip only.")
    assert decoded["quip"] == "Legacy quip only."
    assert decoded["ai"] is None


def test_apply_ai_enhancement_adjusts_confidence():
    sig = build_investment_signal(_etf_rec("Fair"))
    base = sig.confidence
    sig_dict = signal_to_dict(sig)
    apply_ai_enhancement(sig_dict, {
        "n": 6, "cn": [0, 2, 2, 4], "h": "Core hold", "t": ["steady"],
        "tension": "Momentum cold while valuation fair",
    })
    assert sig_dict["confidence"] >= base
    assert sig_dict["ai_enhancement"]["delta"] == sig_dict["confidence"] - base
    assert sig_dict["ai_enhancement"]["headline"] == "Core hold"
    assert sig_dict["ai_enhancement"]["nudge_applied"] is True
    assert sig_dict["confidence_detail"]["ai_applied"] is True


def test_apply_ai_enhancement_skips_nudge_without_tension():
    sig = build_investment_signal(_etf_rec("Fair"))
    base = sig.confidence
    sig_dict = signal_to_dict(sig)
    apply_ai_enhancement(sig_dict, {"n": 6, "cn": [0, 2, 2, 4], "agrees": True, "tension": ""})
    assert sig_dict["confidence"] == base
    assert sig_dict["ai_enhancement"]["nudge_applied"] is False


def test_tension_and_flip_if_preserved():
    ai = normalize_ai_bundle({
        "tension": "Valuation rich",
        "agrees": False,
        "flip_if": {"metric": "Price vs 50-day", "direction": "reclaims above"},
    })
    assert ai["tension"] == "Valuation rich"
    assert ai["agrees"] is False
    assert ai["flip_if"]["metric"] == "Price vs 50-day"


def test_normalize_ai_bundle_clamps_nudges():
    ai = normalize_ai_bundle({"n": 99, "cn": [20, -20, 0, 0]})
    assert ai["overall_nudge"] == 12
    assert ai["component_nudges"] == [6, -6, 0, 0]


def test_parse_ai_bundle_response():
    raw = '{"VOO":{"q":"Hold steady.","n":3,"cn":[0,1,0,2],"h":"Patience","t":["core"]}}'
    parsed = parse_ai_bundle_response(raw, {"VOO"})
    assert parsed["VOO"]["quip"] == "Hold steady."
    assert parsed["VOO"]["ai"]["overall_nudge"] == 3


def test_normalize_ai_bundle_scenario_forecast():
    ai = normalize_ai_bundle({
        "likely": "bull",
        "sc_p": [35, 45, 20],
        "sc_w": "Momentum warming while valuation still fair.",
    })
    assert ai["likely_scenario"] == "bull"
    assert ai["scenario_probs"]["bull"] == 45
    assert ai["scenario_note"].startswith("Momentum")


def test_normalize_ai_bundle_briefing_artifacts():
    ai = normalize_ai_bundle({
        "h": "Quality anchor",
        "drv": "Trend is the strongest input",
        "conv": "moderate",
        "ins": ["Trend at 94%", "Valuation neutral"],
        "fc": ["Wall Street split", "Mid-range", "Uptrend intact", "Low-cost fund"],
    })
    assert ai["key_driver"] == "Trend is the strongest input"
    assert ai["conviction"] == "moderate"
    assert len(ai["insights"]) == 2
    assert ai["factor_callouts"][2] == "Uptrend intact"
    assert ai["factor_callouts"][3] == "Low-cost fund"


def test_apply_ai_enhancement_merges_scenario_forecast():
    sig = build_investment_signal(_etf_rec("Fair"))
    sig_dict = signal_to_dict(sig)
    apply_ai_enhancement(sig_dict, {
        "n": 0,
        "cn": [0, 0, 0, 0],
        "agrees": True,
        "tension": "",
        "likely": "bear",
        "sc_p": [30, 25, 45],
        "sc_w": "Cooling trend could pressure the hold case.",
    })
    forecast = sig_dict["confidence_detail"]["scenarios"]["forecast"]
    assert forecast["source"] == "claude"
    assert forecast["likely"] == "bear"
    assert forecast["probabilities"]["bear"] == 45
    assert "Cooling" in forecast["note"]
    assert sig_dict["ai_enhancement"]["insights"] == []
    assert len(sig_dict["ai_enhancement"]["factor_callouts"]) == 4


def test_apply_ai_enhancement_preserves_briefing_fields():
    sig = build_investment_signal(_etf_rec("Fair"))
    sig_dict = signal_to_dict(sig)
    apply_ai_enhancement(sig_dict, {
        "n": 0,
        "cn": [0, 0, 0, 0],
        "agrees": True,
        "tension": "",
        "h": "Steady hold",
        "drv": "Quality supports patience",
        "conv": "high",
        "ins": ["All four inputs align", "No red flags"],
        "fc": ["Neutral views", "Fair price", "Trend ok", "Solid fund"],
    })
    ai = sig_dict["ai_enhancement"]
    assert ai["key_driver"] == "Quality supports patience"
    assert ai["conviction"] == "high"
    assert ai["insights"] == ["All four inputs align", "No red flags"]
    assert ai["factor_callouts"][0] == "Neutral views"
