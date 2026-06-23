"""
app/services/ai_service.py
Claude AI integration for generating stock and portfolio summaries.
"""

import logging
import re

import anthropic
from app.config import settings

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

MODEL = "claude-haiku-4-5-20251001"


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
