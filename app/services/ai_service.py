"""
app/services/ai_service.py
Claude AI integration for generating stock and portfolio summaries.
"""

import json
import logging
import re
import threading
import time
from itertools import cycle
from time import perf_counter

import anthropic
from app.config import settings

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

MODEL = "claude-haiku-4-5-20251001"

_HEARTBEAT_CACHE: tuple[float, dict] | None = None
_HEARTBEAT_TTL = 120  # seconds — matches frontend poll interval

# Lifetime token accumulator — reset on process restart, updated after every API call.
# Sync FastAPI handlers run in a threadpool, so concurrent dashboard requests can call
# _track_usage() from several threads at once; guard the read-modify-write with a lock.
_TOKEN_USAGE: dict[str, int] = {"total_in": 0, "total_out": 0}
_USAGE_LOCK = threading.Lock()


def reinitialize_client(new_key: str) -> None:
    """Swap in a new API key at runtime without restarting the server."""
    global client, _HEARTBEAT_CACHE  # pylint: disable=global-statement
    setattr(settings, "ANTHROPIC_API_KEY", new_key)
    client = anthropic.Anthropic(api_key=new_key)
    _HEARTBEAT_CACHE = None  # force next poll to do a live check


def _track_usage(_model: str, usage) -> None:
    in_tokens = getattr(usage, "input_tokens", 0) or 0
    out_tokens = getattr(usage, "output_tokens", 0) or 0
    with _USAGE_LOCK:
        _TOKEN_USAGE["total_in"] += in_tokens
        _TOKEN_USAGE["total_out"] += out_tokens


def get_accumulated_usage() -> dict:
    with _USAGE_LOCK:
        return dict(_TOKEN_USAGE)


def _compact_json(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _cached_system(text: str) -> list[dict]:
    """System block with ephemeral prompt cache for repeated Haiku calls."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def claude_api_heartbeat(timeout: float = 2.0) -> dict:
    """Check whether the configured Claude API key can reach Anthropic."""
    if not settings.ANTHROPIC_API_KEY.strip():
        return {
            "live": False,
            "status": "missing_key",
            "latency_ms": None,
            "message": "Claude API key is not configured",
        }

    start = perf_counter()
    try:
        client.models.list(limit=1, timeout=timeout)
        return {
            "live": True,
            "status": "ok",
            "latency_ms": round((perf_counter() - start) * 1000),
            "message": "Claude API reachable",
        }
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug(
            "Claude heartbeat failed; exception_type=%s",
            type(exc).__name__,
        )
        return {
            "live": False,
            "status": type(exc).__name__,
            "latency_ms": round((perf_counter() - start) * 1000),
            "message": "Claude API heartbeat failed",
        }


def get_cached_claude_heartbeat(timeout: float = 2.0) -> dict:
    """Return a cached Claude reachability check to avoid blocking every poll."""
    global _HEARTBEAT_CACHE  # pylint: disable=global-statement
    now = time.monotonic()
    if _HEARTBEAT_CACHE and _HEARTBEAT_CACHE[0] > now:
        return _HEARTBEAT_CACHE[1]

    result = claude_api_heartbeat(timeout=timeout)
    _HEARTBEAT_CACHE = (now + _HEARTBEAT_TTL, result)
    return result

# Rotating fallback quips per action (no Claude required)
_FALLBACK_QUIPS: dict[str, list[str]] = {
    "add": [
        "Quietly compounding while nobody's watching — the boring kind of brilliant.",
        "The numbers like it, the signal likes it — a patient entry could pay off.",
        "Solid footing at this price; the math whispers 'yes' without shouting.",
        "Fundamentals doing the heavy lifting — a thoughtful add makes sense here.",
    ],
    "hold": [
        "Doing exactly what it promised, no fireworks — let it cook.",
        "No drama, no dazzle — and sometimes that's the whole strategy.",
        "The boring middle ground where most of the real compounding happens.",
        "Steady as she goes — sitting tight is a position, and right now it's the right one.",
    ],
    "trim": [
        "Lovely run, but it's wearing a valuation it can't quite afford — maybe shave a slice.",
        "The price has gotten ahead of the story — locking in a bit of that profit isn't cowardly.",
        "When everything looks rich, it usually is — a light trim keeps your options open.",
        "It's done the work; let some of those gains do theirs.",
    ],
    "needs-data": [
        "The data fairy skipped this one — more signal needed before a verdict lands.",
        "Gaps in the data make for gaps in the call — check back with better coverage.",
        "Not enough to go on — a confident guess would just be noise in a suit.",
        "Verdict: pending. The data gods are stingy here.",
    ],
}

_FALLBACK_CYCLE: dict[str, int] = {}


def fallback_quip(action: str) -> str:
    """Return a rotating deterministic quip for the given action (no API required)."""
    options = _FALLBACK_QUIPS.get(action, _FALLBACK_QUIPS["needs-data"])
    with _USAGE_LOCK:
        idx = _FALLBACK_CYCLE.get(action, 0) % len(options)
        _FALLBACK_CYCLE[action] = idx + 1
    return options[idx]


def generate_verdict_quips(signals: list[dict]) -> dict[str, str]:
    """Backward-compatible wrapper — returns ticker→quip only."""
    bundles = generate_verdict_ai_bundles(signals)
    return {
        ticker: data["quip"]
        for ticker, data in bundles.items()
        if data.get("quip")
    }


def _compact_verdict_input(s: dict) -> str:
    mix = s.get("mix") or ""
    reason = str(s.get("reason", "")).replace('"', "'")[:72]
    return (
        f'{s["ticker"]}|{s["action"]}|loc={s["confidence"]}|{mix}|'
        f'mood={s.get("market_mood", "neutral")}|"{reason}"'
    )


_VERDICT_SYSTEM = (
    "Refine verdict cards. JSON keyed by ticker. Each value:\n"
    "q: witty ≤18w | n: int -12..12 overall nudge | "
    "cn: 4 ints [-6..6] Analyst,Valuation,Momentum,Quality\n"
    "h: headline ≤8w | p: 1-2 neutral advisory sentences ≤40w "
    "(consider/may want — no buy/sell orders)\n"
    "t: ≤2 tags | w: optional watch ≤20w | agrees: bool | tension: conflict phrase or \"\"\n"
    "flip_if: optional {metric,direction} | likely: base|bull|bear | "
    "sc_p: [base,bull,bear] sum 100\n"
    "sc_w: ≤22w path note | ins: 2-3 bullets ≤12w | fc: 4 factor callouts ≤8w\n"
    "drv: key driver ≤15w | conv: high|moderate|low\n"
    "Rules: no invented numbers; n=0 cn=[0,0,0,0] unless tension or agrees=false; "
    "base usually 35-55%; hold near local score; BOOK=q only. JSON only."
)


def generate_verdict_ai_bundles(signals: list[dict]) -> dict[str, dict]:
    """
    One batched Haiku call: quip + bounded confidence nudges per ticker.
    Returns ticker → {quip, ai} where ai may be None for BOOK-only rows.
    On failure returns {} so the router falls back to local-only rendering.
    """
    if not signals:
        return {}

    from app.services.verdict_ai_enhancement import parse_ai_bundle_response

    lines = "\n".join(_compact_verdict_input(s) for s in signals)
    ticker_set = {str(s["ticker"]).upper() for s in signals}

    prompt = f"Refine:\n{lines}"

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=min(95 * len(signals) + 80, 4096),
            system=_cached_system(_VERDICT_SYSTEM),
            messages=[{"role": "user", "content": prompt}],
        )
        _track_usage(MODEL, message.usage)
        text_block = next((b for b in message.content if b.type == "text"), None)
        raw = text_block.text.strip() if text_block else ""
        bundles = parse_ai_bundle_response(raw, ticker_set)
        logger.info("Generated %d verdict AI bundles", len(bundles))
        return bundles

    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "generate_verdict_ai_bundles failed; exception_type=%s",
            type(exc).__name__,
        )
        return {}


def generate_etf_profile_seed(ticker: str, name: str | None = None, limit: int = 10) -> dict:
    """
    Ask Claude for a tiny ETF profile seed when Yahoo has no fund profile.
    Returns {"aum": number|None, "holdings": [...]}, or empty values on failure.
    """
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return {"aum": None, "holdings": []}

    fund_name = (name or ticker).strip()
    limit = max(3, min(int(limit or 10), 15))
    prompt = (
        f"{ticker}|{fund_name}|{limit}\n"
        "Return JSON only: "
        "{\"aum\":12300000000,"
        "\"holdings\":[{\"ticker\":\"AAPL\",\"name\":\"Apple\",\"weight\":7.2}]}. "
        "Use known ETF AUM in USD and top holdings; approximate weights %. Unknown fields: null/[]."
    )

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=300,
            temperature=0,
            system=_cached_system(
                "Compact ETF constituent seeds for dashboards. JSON only — no prose or markdown."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        _track_usage(MODEL, message.usage)
        text_block = next((b for b in message.content if b.type == "text"), None)
        raw = text_block.text.strip() if text_block else ""
        raw = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            parsed = {"aum": None, "holdings": parsed}
        if not isinstance(parsed, dict):
            return {"aum": None, "holdings": []}

        aum = None
        try:
            raw_aum = parsed.get("aum")
            if raw_aum is not None and float(raw_aum) > 0:
                aum = round(float(raw_aum))
        except (TypeError, ValueError):
            aum = None

        holdings: list[dict] = []
        for item in (parsed.get("holdings") or [])[:limit]:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("ticker") or item.get("symbol") or "").upper().strip()
            holding_name = str(item.get("name") or symbol).strip()
            try:
                weight = round(float(item.get("weight")), 2)
            except (TypeError, ValueError):
                continue
            if symbol and 0 < weight <= 100:
                holdings.append({
                    "ticker": symbol,
                    "name": holding_name or symbol,
                    "weight": weight,
                })

        if len(holdings) < 3:
            holdings = []
        return {"aum": aum, "holdings": holdings}
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "generate_etf_profile_seed failed; exception_type=%s",
            type(exc).__name__,
        )
        return {"aum": None, "holdings": []}


def generate_etf_holdings_seed(ticker: str, name: str | None = None, limit: int = 10) -> list[dict]:
    """
    Backward-compatible helper for callers/tests that only need holdings.
    """
    return generate_etf_profile_seed(ticker, name, limit).get("holdings") or []


def normalize_bullets(text: str) -> str:
    """
    Normalize Claude's output to exactly 3 '• '-prefixed lines.
    Accepts •, -, or * as bullet markers; strips label prefixes like "Bullet 1:".
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    bullets = []
    for line in lines:
        # Strip any leading bullet marker
        clean = re.sub(r"^[•\-*]+\s*", "", line).strip()
        # Drop bare label lines like "Bullet 1:" with no content after them
        clean = re.sub(r"^bullet\s*\d+:\s*", "", clean, flags=re.IGNORECASE).strip()
        if clean:
            bullets.append(clean)

    bullets = bullets[:3]
    while len(bullets) < 3:
        bullets.append("Data not available.")
    return "\n".join(f"• {b}" for b in bullets)


def _mktcap_str(mktcap: float) -> str:
    if mktcap >= 1e9:
        return f"${mktcap / 1e9:.1f}B"
    if mktcap >= 1e6:
        return f"${mktcap / 1e6:.0f}M"
    return "N/A"


_SUMMARY_SYSTEM = (
    "Write exactly 3 bullets for a stock/ETF/fund fact sheet.\n"
    "Rules: each line starts with '• ', one sentence ≤18 words; "
    "use only provided numbers; no markdown, headers, or buy/sell advice."
)


def _build_prompt(stock_data: dict) -> str:
    ticker   = stock_data.get("ticker", "?")
    name     = stock_data.get("name", ticker)
    sector   = stock_data.get("sector", "N/A")
    price    = stock_data.get("current_price", 0)
    chg_pct  = stock_data.get("day_change_pct", 0)
    fwh      = stock_data.get("fifty_two_week_high", 0)
    fwl      = stock_data.get("fifty_two_week_low", 0)
    pe       = stock_data.get("pe_ratio")
    _dv      = stock_data.get("dividend_yield")
    div_pct  = round(_dv * 100, 2) if _dv is not None else None
    mktcap   = stock_data.get("market_cap", 0)
    qt       = (stock_data.get("quote_type") or "EQUITY").upper()

    range_pct = (
        round((price - fwl) / (fwh - fwl) * 100)
        if (fwh - fwl) > 0 else None
    )

    metrics = (
        f"px={price:.2f}|day={chg_pct:+.2f}%|52w={fwl:.2f}-{fwh:.2f}"
        + (f"|range={range_pct}%" if range_pct is not None else "")
        + f"|pe={pe if pe else 'n/a'}|div={f'{div_pct}%' if div_pct else 'none'}"
        + f"|cap={_mktcap_str(mktcap)}"
    )

    if qt in ("ETF", "MUTUALFUND"):
        kind = "ETF" if qt == "ETF" else "FUND"
        hints = (
            "B1: index/sector/asset tracked. "
            "B2: today move + 52w range. "
            "B3: dividend yield or sector/geographic focus."
        )
    else:
        kind = "STOCK"
        hints = (
            "B1: company + sector. "
            "B2: today move + 52w range. "
            "B3: standout P/E, dividend, or market cap."
        )

    return f"{kind}|{name}|{ticker}|{sector}|{metrics}\n{hints}"


_BRIEFING_SYSTEM = (
    "Portfolio briefer. Compact JSON snapshot → JSON only:\n"
    '"health": one sentence on overall P/L.\n'
    '"drivers": 2-3 strings citing biggest movers with snapshot numbers.\n'
    '"adjustments": 1-2 rebalancing observations; if none '
    '["No changes needed — the book looks balanced."].\n'
    '"quote": witty motivational one-liner ≤20w.\n'
    "Use only snapshot numbers. No buy/sell advice."
)

_BRIEFING_CANNED_QUOTES: list[str] = [
    "Even when the market sneezes, a well-diversified portfolio hands you a tissue.",
    "Compounding: the one magic trick where watching paint dry is actually the strategy.",
    "Your portfolio called — it said 'thanks for not panic-selling today.'",
    "The best investment decision is usually the one you didn't make at 3 a.m.",
]
_briefing_quote_cycle = cycle(_BRIEFING_CANNED_QUOTES)


def next_briefing_canned_quote() -> str:
    """Return a rotating canned quote — no API required."""
    return next(_briefing_quote_cycle)


def generate_portfolio_briefing(snapshot: dict) -> dict:
    """
    One Haiku call: portfolio briefing from a compact snapshot.
    Returns {health, drivers, adjustments, quote}.
    Raises on API failure — let the caller handle fallback.
    """
    message = client.messages.create(
        model=MODEL,
        max_tokens=320,
        system=_cached_system(_BRIEFING_SYSTEM),
        messages=[{"role": "user", "content": _compact_json(snapshot)}],
    )
    _track_usage(MODEL, message.usage)
    text_block = next((b for b in message.content if b.type == "text"), None)
    raw = (text_block.text.strip() if text_block else "")
    logger.info(
        "Generated portfolio briefing: %s+%s tokens",
        message.usage.input_tokens,
        message.usage.output_tokens,
    )

    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Briefing response is not a JSON object")

    health = str(data.get("health") or "").strip()
    if not health:
        raise ValueError("Briefing response missing 'health' key")

    raw_drivers = data.get("drivers")
    if not isinstance(raw_drivers, list):
        raw_drivers = [str(raw_drivers)] if raw_drivers else []
    drivers = [str(d).strip() for d in raw_drivers[:3] if d]

    raw_adj = data.get("adjustments")
    if not isinstance(raw_adj, list):
        raw_adj = [str(raw_adj)] if raw_adj else []
    adjustments = [str(a).strip() for a in raw_adj[:2] if a]
    if not adjustments:
        adjustments = ["No changes needed — the book looks balanced."]

    quote = str(data.get("quote") or "").strip() or next_briefing_canned_quote()

    return {"health": health, "drivers": drivers, "adjustments": adjustments, "quote": quote}


# ── News themes ───────────────────────────────────────────────────────────────

_NEWS_THEMES_SYSTEM = (
    "Portfolio news narrator. Compact holdings+headlines JSON → JSON only:\n"
    '"briefing": 1-2 sentence second-person read of what in today\'s news '
    "matters to THIS book.\n"
    '"themes": 2-4 items, each {"title": ≤6w, "summary": ≤28w, '
    '"tickers": [...]}.\n'
    "Each theme ties a shared narrative to the holdings it touches.\n"
    "Use only the supplied headlines. No buy/sell advice."
)


def generate_news_themes(snapshot: dict) -> dict:
    """
    One Haiku call: news briefing + cross-holding theme clusters.
    Returns {"briefing": str, "themes": [{"title", "summary", "tickers"}]}.
    Raises on any failure so the caller can serve a 503.
    """
    message = client.messages.create(
        model=MODEL,
        max_tokens=480,
        system=_cached_system(_NEWS_THEMES_SYSTEM),
        messages=[{"role": "user", "content": _compact_json(snapshot)}],
    )
    _track_usage(MODEL, message.usage)
    text_block = next((b for b in message.content if b.type == "text"), None)
    raw = text_block.text.strip() if text_block else ""
    logger.info(
        "Generated news themes: %s+%s tokens",
        message.usage.input_tokens,
        message.usage.output_tokens,
    )

    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("News themes response is not a JSON object")

    briefing = str(data.get("briefing") or "").strip()
    if not briefing:
        raise ValueError("News themes response missing 'briefing'")

    raw_themes = data.get("themes")
    if not isinstance(raw_themes, list):
        raise ValueError("News themes response missing 'themes' list")

    themes: list[dict] = []
    for t in raw_themes[:4]:
        if not isinstance(t, dict):
            continue
        title   = str(t.get("title")   or "").strip()
        summary = str(t.get("summary") or "").strip()
        tickers = [str(x).upper() for x in (t.get("tickers") or []) if x]
        if title and summary:
            themes.append({"title": title, "summary": summary, "tickers": tickers})

    if not themes:
        raise ValueError("News themes response contained no usable themes")

    return {"briefing": briefing, "themes": themes}


def _analytics_insights_system() -> str:
    from app.services.analytics_insights import KEY_TIP_WIDGETS

    keys = ", ".join(sorted(KEY_TIP_WIDGETS))
    return (
        "Analytics narrator. Compact portfolio JSON → JSON only:\n"
        '1. "insights": {performance,risk,exposure,signals,markets} — '
        "one second-person sentence each ≤28w.\n"
        f'2. "widget_insights": ONLY these keys as {{"headline":5-8w,"insight":≤28w}}: {keys}\n'
        "Use snapshot numbers only. No financial advice."
    )


def generate_analytics_insights(snapshot: dict) -> dict:
    """One Haiku call: tab sentences + KEY widget tip cards."""
    from app.services.analytics_insights import build_ai_analytics_prompt_snapshot

    slim = build_ai_analytics_prompt_snapshot(snapshot)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=_cached_system(_analytics_insights_system()),
        messages=[{"role": "user", "content": _compact_json(slim)}],
    )
    _track_usage(MODEL, message.usage)
    text_block = next((b for b in message.content if b.type == "text"), None)
    raw = (text_block.text.strip() if text_block else "")
    logger.info(
        "Generated analytics insights: %s+%s tokens",
        message.usage.input_tokens,
        message.usage.output_tokens,
    )

    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Analytics insights response is not a JSON object")

    tab_keys = ("performance", "risk", "exposure", "signals", "markets")
    insights_raw = data.get("insights") if isinstance(data.get("insights"), dict) else data
    insights = {
        k: str(insights_raw.get(k) or data.get(k) or "").strip()
        for k in tab_keys
    }
    if not any(insights.values()):
        raise ValueError("Analytics insights response empty")

    widget_raw = data.get("widget_insights") or {}
    widget_insights: dict = {}
    for k, v in widget_raw.items():
        if isinstance(v, dict):
            headline = str(v.get("headline") or "").strip()
            insight = str(v.get("insight") or "").strip()
            if insight:
                widget_insights[k] = {"headline": headline, "insight": insight}
        elif isinstance(v, str) and v.strip():
            widget_insights[k] = v.strip()

    return {"insights": insights, "widget_insights": widget_insights}


ACTION_PLAN_MODEL = "claude-sonnet-4-5"

_ACTION_PLAN_SYSTEM = (
    "Portfolio action planner. Compact portfolio snapshot → JSON only:\n"
    '"headline": ≤12w one-line portfolio stance.\n'
    '"thesis": ≤40w why, citing concrete snapshot numbers '
    "(concentration, regime, top risks).\n"
    '"buckets": {'
    '"hold":[{"ticker","reason":≤16w}],'
    '"add":[{"ticker","reason":≤16w}],'
    '"trim":[{"ticker","reason":≤16w}],'
    '"exit":[{"ticker","reason":≤16w}]'
    "}\n"
    '"priority_moves":[≤18w each, highest-impact-first, max 3].\n'
    '"best_return_note": One crisp executive sentence ≤20w — '
    "the single clearest gap or opportunity in plain English. "
    "No internal labels: write 'large holds' not 'heavy_hold', "
    "'oversized position' not 'large_trim', 'underweight' not 'small_add'.\n"
    "Rules: use ONLY supplied numbers; never invent prices or targets; "
    "plain English only — NEVER use snake_case or underscores in prose "
    "(heavy_hold large_trim small_add uncertain_hold are FORBIDDEN); "
    "no ALL-CAPS except ticker symbols; "
    "advisory voice only — consider/may want, no buy/sell orders; "
    "respect each holding's existing action as the prior — only escalate "
    "trim→exit when watchlist=true or clearly deteriorating; "
    "portfolio-level stance, not a wall of per-stock text. JSON only."
)


_INTERNAL_TERM_MAP = [
    (re.compile(r"\bheavy[_\s]hold\b", re.IGNORECASE), "large hold"),
    (re.compile(r"\blarge[_\s]trim\b", re.IGNORECASE), "oversized position"),
    (re.compile(r"\bsmall[_\s]add\b", re.IGNORECASE), "underweight position"),
    (re.compile(r"\buncertain[_\s]hold\b", re.IGNORECASE), "low-conviction hold"),
]


def _sanitize_plan_text(text: str) -> str:
    for pattern, replacement in _INTERNAL_TERM_MAP:
        text = pattern.sub(replacement, text)
    return text


def generate_action_plan(snapshot: dict) -> dict:
    """
    One Sonnet call: prioritised action plan from a compact portfolio snapshot.
    Returns {headline, thesis, buckets, priority_moves, best_return_note}.
    Raises on any API failure — let the caller handle the deterministic fallback.
    """
    message = client.messages.create(
        model=ACTION_PLAN_MODEL,
        max_tokens=800,
        system=_cached_system(_ACTION_PLAN_SYSTEM),
        messages=[{"role": "user", "content": _compact_json(snapshot)}],
    )
    _track_usage(ACTION_PLAN_MODEL, message.usage)
    text_block = next((b for b in message.content if b.type == "text"), None)
    raw = text_block.text.strip() if text_block else ""
    logger.info(
        "Generated action plan: %s+%s tokens",
        message.usage.input_tokens,
        message.usage.output_tokens,
    )

    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Action plan response is not a JSON object")

    headline = _sanitize_plan_text(str(data.get("headline") or "").strip())
    if not headline:
        raise ValueError("Action plan response missing 'headline'")

    thesis = _sanitize_plan_text(str(data.get("thesis") or "").strip())

    raw_buckets = data.get("buckets") or {}
    if not isinstance(raw_buckets, dict):
        raise ValueError("Action plan response missing 'buckets'")

    def _parse_bucket(items: object) -> list[dict]:
        if not isinstance(items, list):
            return []
        result: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").upper().strip()
            reason = str(item.get("reason") or "").strip()
            if ticker:
                result.append({"ticker": ticker, "reason": _sanitize_plan_text(reason)})
        return result

    buckets = {
        "hold": _parse_bucket(raw_buckets.get("hold")),
        "add":  _parse_bucket(raw_buckets.get("add")),
        "trim": _parse_bucket(raw_buckets.get("trim")),
        "exit": _parse_bucket(raw_buckets.get("exit")),
    }

    raw_pm = data.get("priority_moves")
    priority_moves = (
        [_sanitize_plan_text(str(m).strip()) for m in raw_pm[:3] if m]
        if isinstance(raw_pm, list) else []
    )

    best_return_note = _sanitize_plan_text(str(data.get("best_return_note") or "").strip())

    return {
        "headline": headline,
        "thesis": thesis,
        "buckets": buckets,
        "priority_moves": priority_moves,
        "best_return_note": best_return_note,
    }


def generate_stock_summary(stock_data: dict) -> str:
    """
    Generate a 3-bullet AI summary for a single holding.
    Returns normalized '• ' bullets, or a fallback string on error.
    """
    ticker = stock_data.get("ticker", "Unknown")

    try:
        prompt = _build_prompt(stock_data)

        message = client.messages.create(
            model=MODEL,
            max_tokens=120,
            system=_cached_system(_SUMMARY_SYSTEM),
            messages=[{"role": "user", "content": prompt}],
        )
        _track_usage(MODEL, message.usage)
        text_block = next((b for b in message.content if b.type == "text"), None)
        raw = text_block.text.strip() if text_block else ""
        logger.info(
            "Generated summary: %s+%s tokens",
            message.usage.input_tokens,
            message.usage.output_tokens,
        )
        return normalize_bullets(raw)

    except anthropic.AuthenticationError:
        logger.error("Invalid API key — check ANTHROPIC_API_KEY in .env")
        return (
            f"• {ticker} summary unavailable (API authentication error).\n"
            "• Check ANTHROPIC_API_KEY in your .env file.\n"
            "• Data not available."
        )

    except anthropic.RateLimitError:
        logger.warning("Rate limit hit while generating summary")
        return (
            f"• {ticker} summary temporarily unavailable (rate limit).\n"
            "• Try again in a few moments.\n"
            "• Data not available."
        )

    except Exception as exc:
        logger.error(
            "AI summary failed; exception_type=%s",
            type(exc).__name__,
        )
        chg = stock_data.get("day_change_pct", 0)
        direction = "up" if chg >= 0 else "down"
        return (
            f"• {ticker} is {direction} {abs(chg):.2f}% today.\n"
            "• Full summary could not be generated.\n"
            "• Data not available."
        )
