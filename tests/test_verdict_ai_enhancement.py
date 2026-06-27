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
    apply_ai_enhancement(sig_dict, {"n": 6, "cn": [0, 2, 2, 4], "h": "Core hold", "t": ["steady"]})
    assert sig_dict["confidence"] >= base
    assert sig_dict["ai_enhancement"]["delta"] == sig_dict["confidence"] - base
    assert sig_dict["ai_enhancement"]["headline"] == "Core hold"
    assert sig_dict["confidence_detail"]["ai_applied"] is True


def test_normalize_ai_bundle_clamps_nudges():
    ai = normalize_ai_bundle({"n": 99, "cn": [20, -20, 0, 0]})
    assert ai["overall_nudge"] == 12
    assert ai["component_nudges"] == [6, -6, 0, 0]


def test_parse_ai_bundle_response():
    raw = '{"VOO":{"q":"Hold steady.","n":3,"cn":[0,1,0,2],"h":"Patience","t":["core"]}}'
    parsed = parse_ai_bundle_response(raw, {"VOO"})
    assert parsed["VOO"]["quip"] == "Hold steady."
    assert parsed["VOO"]["ai"]["overall_nudge"] == 3
