"""
Claude synthesis layer for investment verdicts.

Applies small, bounded nudges on top of deterministic local intelligence.
No network calls — parsing and math only.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.investment_signal import _clamp, _confidence_level, _confidence_summary, _weighted_score

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

    return {
        "headline": str(raw.get("h") or raw.get("headline") or "").strip()[:80],
        "overall_nudge": _int_nudge(
            raw.get("n", raw.get("overall_nudge", 0)),
            -_MAX_OVERALL_NUDGE,
            _MAX_OVERALL_NUDGE,
        ),
        "component_nudges": cn,
        "tags": tags,
        "note": str(raw.get("w") or raw.get("note") or "").strip()[:160],
    }


def apply_ai_enhancement(sig_dict: dict, ai_raw: dict | None) -> dict:
    """
    Merge Claude nudges into an existing signal dict (mutates and returns sig_dict).
    Preserves local scores under confidence_detail.local_score.
    """
    ai = normalize_ai_bundle(ai_raw)
    if not ai:
        return sig_dict

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

    sig_dict["confidence"] = final
    sig_dict["confidence_detail"] = detail
    sig_dict["ai_enhancement"] = {
        "headline": ai["headline"],
        "tags": ai["tags"],
        "note": ai["note"],
        "local_score": local_score,
        "ai_score": final,
        "delta": final - local_score,
        "component_nudges": ai["component_nudges"],
        "overall_nudge": ai["overall_nudge"],
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
