"""
app/services/ai_service.py
Claude AI integration for generating stock and portfolio summaries.
"""

import json
import logging
import re
from time import perf_counter

import anthropic
from app.config import settings

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

MODEL = "claude-haiku-4-5-20251001"


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
    reason = str(s.get("reason", "")).replace('"', "'")[:90]
    return (
        f'{s["ticker"]}|{s["action"]}|loc={s["confidence"]}|{mix}|'
        f'mood={s.get("market_mood", "neutral")}|"{reason}"'
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

    system = (
        "You refine investment verdict cards. For each ticker line, return JSON keyed by ticker. "
        "Each value is an object with:\n"
        "  q: one witty sentence (≤18 words), professional Claude voice\n"
        "  n: integer overall nudge -12..12 (how much local confidence should move)\n"
        "  cn: array of 4 integers [-6..6] nudging [Analyst, Valuation, Momentum, Quality]\n"
        "  h: headline ≤8 plain words for the card\n"
        "  t: up to 2 short tags (e.g. steady, core, watch)\n"
        "  w: optional watch note ≤20 words (plain English)\n"
        "  agrees: boolean — true if you agree with local action/confidence\n"
        "  tension: short phrase when inputs conflict (empty string if none)\n"
        "  flip_if: optional {metric, direction} when a specific change would flip the call\n"
        "  likely: base|bull|bear — your best guess for the most probable near-term path\n"
        "  sc_p: array of 3 integers [base%, bull%, bear%] summing to 100 (rough split)\n"
        "  sc_w: ≤22 words explaining why you picked that likely path (plain English)\n"
        "Rules: never invent prices or percentages; only set n/cn when tension is non-empty "
        "OR agrees is false — otherwise n=0 and cn=[0,0,0,0]; "
        "sc_p must sum to 100 and likely should match your highest bucket (or explain in sc_w); "
        "base usually 35–55% unless trend is strong; "
        "hold calls usually stay near local score; BOOK ticker gets q only (no n/cn/h/t/w/sc_*). "
        "Return ONLY JSON."
    )

    prompt = f"Refine these verdicts. Return only JSON.\n\n{lines}"

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=min(120 * len(signals) + 120, 4096),
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
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
            max_tokens=360,
            temperature=0,
            system=(
                "You provide compact ETF constituent seeds for dashboards. "
                "No prose. No markdown. Only valid JSON."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
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
        f"Price: ${price:.2f} ({chg_pct:+.2f}% today)\n"
        f"52-week range: ${fwl:.2f}–${fwh:.2f}"
        + (f" | Now at {range_pct}% of range" if range_pct is not None else "")
        + f"\nP/E: {pe if pe else 'N/A'}"
        + f" | Dividend yield: {f'{div_pct}%' if div_pct else 'none'}"
        + f" | Market cap: {_mktcap_str(mktcap)}"
    )

    rules = (
        "Rules:\n"
        "• Each bullet starts with '• ' and is one sentence, max 18 words\n"
        "• Use only the numbers provided — do not invent any data\n"
        "• No markdown, no headers, no financial advice, no buy/sell/hold"
    )

    if qt in ("ETF", "MUTUALFUND"):
        security_label = "ETF" if qt == "ETF" else "fund"
        return (
            f"Write a 3-bullet fact sheet for this {security_label}.\n\n"
            f"{rules}\n\n"
            f"Bullet 1: What index, sector, or asset class this {security_label} tracks.\n"
            f"Bullet 2: Today's price change and where it sits in its 52-week range.\n"
            f"Bullet 3: One notable characteristic — dividend yield if any, "
            f"or the sector/geographic focus.\n\n"
            f"{security_label.upper()}: {name} ({ticker})\n"
            f"Category: {sector}\n"
            f"{metrics}"
        )

    # Default: individual stock / equity
    return (
        "Write a 3-bullet snapshot for this stock.\n\n"
        f"{rules}\n\n"
        "Bullet 1: What this company does and its sector in one sentence.\n"
        "Bullet 2: Today's price change and where it sits in its 52-week range.\n"
        "Bullet 3: One standout metric — P/E context, dividend yield, or market cap tier.\n\n"
        f"Stock: {name} ({ticker})\n"
        f"Sector: {sector}\n"
        f"{metrics}"
    )


_BRIEFING_SYSTEM = (
    "You are FolioSense's portfolio briefer. You receive a compact JSON snapshot of the user's "
    "portfolio. Write a crisp, confident briefing in the second person (\"your portfolio\"). "
    "Return ONLY valid JSON (no markdown, no prose outside JSON) with exactly these keys:\n"
    "- \"health\": one sentence on how the portfolio is doing overall, grounded in the P/L numbers.\n"
    "- \"drivers\": array of 2–3 short strings naming the specific holdings or sectors behind the "
    "biggest change, each citing its number from the snapshot.\n"
    "- \"adjustments\": array of 1–2 short strings — optional rebalancing OBSERVATIONS (e.g. "
    "concentration, a runaway winner, a persistent laggard). If nothing stands out, return "
    "[\"No changes needed — the book looks balanced.\"].\n"
    "- \"quote\": one funny, witty, motivational one-liner to send the user off (≤20 words).\n"
    "Rules: use ONLY numbers present in the snapshot — never invent prices, percentages, or news. "
    "No buy/sell financial advice; frame adjustments as observations. Keep every line tight and human."
)

_BRIEFING_CANNED_QUOTES: list[str] = [
    "Even when the market sneezes, a well-diversified portfolio hands you a tissue.",
    "Compounding: the one magic trick where watching paint dry is actually the strategy.",
    "Your portfolio called — it said 'thanks for not panic-selling today.'",
    "The best investment decision is usually the one you didn't make at 3 a.m.",
]
_BRIEFING_CANNED_IDX = 0


def next_briefing_canned_quote() -> str:
    """Return a rotating canned quote — no API required."""
    global _BRIEFING_CANNED_IDX
    q = _BRIEFING_CANNED_QUOTES[_BRIEFING_CANNED_IDX % len(_BRIEFING_CANNED_QUOTES)]
    _BRIEFING_CANNED_IDX += 1
    return q


def generate_portfolio_briefing(snapshot: dict) -> dict:
    """
    One Haiku call: portfolio briefing from a compact snapshot.
    Returns {health, drivers, adjustments, quote}.
    Raises on API failure — let the caller handle fallback.
    """
    message = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=_BRIEFING_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(snapshot)}],
    )
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
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )

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
