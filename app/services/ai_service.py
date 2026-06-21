"""
app/services/ai_service.py
Claude AI integration for generating stock and portfolio summaries.
Uses claude-haiku for speed and cost efficiency.
"""

import anthropic
import logging
from app.config import settings

logger = logging.getLogger(__name__)

# Create the Anthropic client once (reuse across requests)
client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# The model we use for all summaries
MODEL = "claude-haiku-4-5-20251001"


def generate_stock_summary(stock_data: dict) -> str:
    """
    Generate a 2-sentence AI summary for a single stock holding.

    Args:
        stock_data: Dictionary from get_stock_quote() containing
                    ticker, name, current_price, day_change_pct, etc.

    Returns:
        2-sentence summary string, or fallback message on error.
    """
    ticker = stock_data.get("ticker", "Unknown")

    try:
        price   = stock_data.get("current_price", 0)
        fwh     = stock_data.get("fifty_two_week_high", 0)
        fwl     = stock_data.get("fifty_two_week_low", 0)
        range_pct = round((price - fwl) / (fwh - fwl) * 100) if (fwh - fwl) > 0 else None
        pe      = stock_data.get("pe_ratio") or None
        div_pct = round(stock_data.get("dividend_yield", 0) * 100, 2) or None
        mktcap  = stock_data.get("market_cap", 0)
        mktcap_str = f"${mktcap/1e9:.1f}B" if mktcap >= 1e9 else (f"${mktcap/1e6:.0f}M" if mktcap else "N/A")
        volume  = stock_data.get("volume", 0)

        prompt = f"""You are a Wall Street analyst briefing a sophisticated retail investor on a holding in their personal portfolio.

Write exactly 3 sentences. Each must reveal something a retail investor cannot easily find on Robinhood, Fidelity, or a basic Google search.

DO NOT mention: today's price, today's % change, or anything visible at a glance on a brokerage screen.

Focus on:
- Hidden risks or structural edges specific to this holding (e.g. ETF concentration, earnings quality, competitive moat cracks)
- What the valuation or 52-week positioning signals about market expectations — and where those expectations could be wrong
- A specific tail-risk trigger (macro shift, regulatory event, earnings quality issue, index rebalance) that most retail investors aren't tracking

Be blunt and specific. Use numbers when possible. No hedging language.

Holding: {stock_data.get("name", ticker)} ({ticker})
Sector/Category: {stock_data.get("sector", "N/A")}
P/E: {pe if pe else "N/A (likely ETF or no earnings)"}
Dividend Yield: {f"{div_pct}%" if div_pct else "None"}
Market Cap / AUM: {mktcap_str}
52-Week Range: ${fwl:.2f}–${fwh:.2f} | Current ${price:.2f} = {f"{range_pct}% of range" if range_pct is not None else "N/A"}
Volume: {volume:,}"""

        message = client.messages.create(
            model=MODEL,
            max_tokens=220,  # 3 dense sentences ≈ 150-200 tokens; 220 gives headroom without waste
            messages=[{"role": "user", "content": prompt}],
        )

        summary = message.content[0].text.strip()
        logger.info(
            f"Generated summary for {ticker}: "
            f"{message.usage.input_tokens}+{message.usage.output_tokens} tokens"
        )
        return summary

    except anthropic.AuthenticationError:
        logger.error("Invalid API key — check ANTHROPIC_API_KEY in .env")
        return f"{ticker} summary unavailable (API authentication error)."

    except anthropic.RateLimitError:
        logger.warning(f"Rate limit hit while generating summary for {ticker}")
        return f"{ticker} summary temporarily unavailable (rate limit)."

    except Exception as e:
        logger.error(f"AI summary failed for {ticker}: {e}")
        return (
            f"{ticker} is {"up" if stock_data.get("day_change_pct", 0) >= 0 else "down"} "
            f"{abs(stock_data.get('day_change_pct', 0)):.2f}% today."
        )
