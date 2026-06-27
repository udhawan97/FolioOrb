"""
Claude synthesis layer for investment verdicts.

Applies small, bounded nudges on top of deterministic local intelligence.
No network calls — parsing and math only.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.investment_signal import (
    _clamp,
    _confidence_level,
    _confidence_summary,
    _normalize_scenario_probs,
    _weighted_score,
)

_COMPONENT_KEYS = ("analyst", "valuation", "momentum", "quality")
_MAX_OVERALL_NUDGE = 12
_MAX_COMPONENT_NUDGE = 6


def compact_signal_mix(signal_mix: list[dict] | None) -> str:
    """Compact mix for Claude input: An:s Val:n Mom:a Qual:s"""
    labels = {"Analyst": "An", "Valuation": "Val", "Momentum": "Mom", "Quality": "Qual"}
    stance_code = {"support": "s", "neutral": "n", "against": "a"}
    parts: list[str] = []
    for item in signal_mix or []:
        abbr = labels.get(item.get("label", ""), "")
        if not abbr:
            continue
        code = stance_code.get(item.get("stance", "neutral"), "n")
        parts.append(f"{abbr}:{code}")
    return " ".join(parts) if parts else "mix:unknown"


def encode_verdict_cache(quip: str, ai: dict | None = None) -> str:
    payload: dict[str, Any] = {"q": quip.strip()}
    if ai:
        payload["a"] = ai
    return json.dumps(payload, separators=(",", ":"))


def decode_verdict_cache(text: str | None) -> dict[str, Any]:
    if not text or not str(text).strip():
        return {"quip": "", "ai": None}
    raw = str(text).strip()
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                ai_raw = parsed.get("a") or parsed.get("ai")
                return {
                    "quip": str(parsed.get("q") or parsed.get("quip") or "").strip(),
                    "ai": normalize_ai_bundle(ai_raw) if ai_raw else None,
                }
        except json.JSONDecodeError:
            pass
    return {"quip": raw, "ai": None}


def _int_nudge(value, lo: int, hi: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(lo, min(hi, number))


def normalize_ai_bundle(raw: dict | None) -> dict | None:
    """Normalize compact Claude keys into a stable enhancement dict."""
    if not isinstance(raw, dict):
        return None
    tags = raw.get("t") or raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(t).strip()[:24] for t in tags if str(t).strip()][:2]

    cn = raw.get("cn") or raw.get("component_nudges") or []
    if not isinstance(cn, list):
        cn = []
    while len(cn) < 4:
        cn.append(0)
    cn = [_int_nudge(v, -_MAX_COMPONENT_NUDGE, _MAX_COMPONENT_NUDGE) for v in cn[:4]]

    likely_raw = str(raw.get("likely") or raw.get("likely_scenario") or "").strip().lower()
    likely = likely_raw if likely_raw in ("base", "bull", "bear") else None

    sc_p_raw = raw.get("sc_p") or raw.get("scenario_probs")
    scenario_probs = None
    if sc_p_raw is not None:
        scenario_probs = _normalize_scenario_probs(sc_p_raw)

    scenario_note = str(raw.get("sc_w") or raw.get("scenario_note") or "").strip()[:120]

    insights_raw = raw.get("ins") or raw.get("insights") or []
    if isinstance(insights_raw, str):
        insights_raw = [insights_raw]
    insights = [
        str(item).strip()[:80]
        for item in (insights_raw if isinstance(insights_raw, list) else [])
        if str(item).strip()
    ][:3]

    fc_raw = raw.get("fc") or raw.get("factor_callouts") or []
    if isinstance(fc_raw, str):
        fc_raw = [fc_raw]
    factor_callouts: list[str] = []
    if isinstance(fc_raw, list):
        for item in fc_raw[:4]:
            factor_callouts.append(str(item).strip()[:48])
        while len(factor_callouts) < 4:
            factor_callouts.append("")

    conv_raw = str(raw.get("conv") or raw.get("conviction") or "").strip().lower()
    conviction = conv_raw if conv_raw in ("high", "moderate", "low") else None

    return {
        "headline": str(raw.get("h") or raw.get("headline") or "").strip()[:80],
        "plain_summary": str(raw.get("p") or raw.get("plain_summary") or "").strip()[:220],
        "key_driver": str(raw.get("drv") or raw.get("key_driver") or "").strip()[:80],
        "overall_nudge": _int_nudge(
            raw.get("n", raw.get("overall_nudge", 0)),
            -_MAX_OVERALL_NUDGE,
            _MAX_OVERALL_NUDGE,
        ),
        "component_nudges": cn,
        "tags": tags,
        "note": str(raw.get("w") or raw.get("note") or "").strip()[:160],
        "agrees": raw.get("agrees") if raw.get("agrees") is not None else True,
        "tension": str(raw.get("tension") or "").strip()[:120],
        "flip_if": raw.get("flip_if") if isinstance(raw.get("flip_if"), dict) else None,
        "likely_scenario": likely,
        "scenario_probs": scenario_probs,
        "scenario_note": scenario_note,
        "insights": insights,
        "factor_callouts": factor_callouts,
        "conviction": conviction,
    }


def _should_apply_nudge(ai: dict) -> bool:
    """Only nudge when Claude surfaces tension or explicit disagreement."""
    tension = (ai.get("tension") or "").strip()
    agrees = ai.get("agrees")
    if tension:
        return True
    if agrees is False:
        return True
    return False


def apply_ai_enhancement(sig_dict: dict, ai_raw: dict | None) -> dict:
    """
    Merge Claude nudges into an existing signal dict (mutates and returns sig_dict).
    Preserves local scores under confidence_detail.local_score.
    """
    ai = normalize_ai_bundle(ai_raw)
    if not ai:
        return sig_dict

    apply_nudge = _should_apply_nudge(ai)
    if not apply_nudge:
        ai["overall_nudge"] = 0
        ai["component_nudges"] = [0, 0, 0, 0]

    detail = dict(sig_dict.get("confidence_detail") or {})
    local_score = int(sig_dict.get("confidence") or detail.get("score") or 0)
    detail["local_score"] = local_score

    components = []
    for idx, comp in enumerate(detail.get("components") or []):
        base_score = int(comp.get("score") or 0)
        nudge = ai["component_nudges"][idx] if idx < 4 else 0
        adjusted = _clamp(base_score + nudge)
        updated = dict(comp)
        updated["local_score"] = base_score
        updated["ai_nudge"] = nudge
        updated["score"] = adjusted
        updated["bar_pct"] = adjusted
        components.append(updated)
    detail["components"] = components

    if components:
        recomputed = _weighted_score(components)
    else:
        recomputed = local_score

    final = _clamp(recomputed + ai["overall_nudge"])
    detail["score"] = final
    detail["level"] = _confidence_level(final)
    detail["summary"] = _confidence_summary(final, sig_dict.get("action", "hold"))
    detail["ai_applied"] = True

    modifiers = list(detail.get("modifiers") or [])
    modifiers.append({
        "label": "Claude synthesis",
        "delta": ai["overall_nudge"],
        "tip_title": "AI refinement",
        "tip_body": (
            "Claude read the same local inputs and applied a small bounded adjustment "
            f"({ai['overall_nudge']:+d} pts) after re-weighting component scores. "
            "It cannot invent new numbers — only nudge the deterministic read."
        ),
    })
    detail["modifiers"] = modifiers

    scenarios = dict(detail.get("scenarios") or {})
    local_forecast = dict((scenarios.get("forecast") or {}))
    if ai.get("scenario_probs") or ai.get("likely_scenario") or ai.get("scenario_note"):
        probs = ai["scenario_probs"] or _normalize_scenario_probs(
            local_forecast.get("probabilities"),
        )
        likely = ai.get("likely_scenario") or max(probs, key=probs.get)
        if likely not in ("base", "bull", "bear"):
            likely = max(probs, key=probs.get)
        note = ai.get("scenario_note") or local_forecast.get("note") or ""
        scenarios["forecast"] = {
            "likely": likely,
            "probabilities": probs,
            "note": note,
            "source": "claude",
        }
        detail["scenarios"] = scenarios

    sig_dict["confidence"] = final
    sig_dict["confidence_detail"] = detail
    sig_dict["ai_enhancement"] = {
        "headline": ai["headline"],
        "plain_summary": ai.get("plain_summary", ""),
        "key_driver": ai.get("key_driver", ""),
        "tags": ai["tags"],
        "note": ai["note"],
        "local_score": local_score,
        "ai_score": final,
        "delta": final - local_score,
        "component_nudges": ai["component_nudges"],
        "overall_nudge": ai["overall_nudge"],
        "agrees": ai.get("agrees", True),
        "tension": ai.get("tension", ""),
        "flip_if": ai.get("flip_if"),
        "nudge_applied": apply_nudge,
        "likely_scenario": ai.get("likely_scenario"),
        "scenario_probs": ai.get("scenario_probs"),
        "scenario_note": ai.get("scenario_note"),
        "insights": ai.get("insights") or [],
        "factor_callouts": ai.get("factor_callouts") or ["", "", "", ""],
        "conviction": ai.get("conviction"),
    }
    return sig_dict


def parse_ai_bundle_response(raw: str, tickers: set[str]) -> dict[str, dict]:
    """Parse Claude JSON response into ticker → {quip, ai} bundles."""
    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw.strip(), flags=re.DOTALL).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    out: dict[str, dict] = {}
    for ticker, payload in parsed.items():
        symbol = str(ticker).upper()
        if symbol not in tickers and symbol != "BOOK":
            continue
        if isinstance(payload, str):
            out[symbol] = {"quip": payload.strip(), "ai": None}
            continue
        if not isinstance(payload, dict):
            continue
        quip = str(payload.get("q") or payload.get("quip") or "").strip()
        ai = normalize_ai_bundle(payload)
        out[symbol] = {"quip": quip, "ai": ai}
    return out
