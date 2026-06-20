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
        # Build the prompt with real data
        # The more context we give Claude, the more relevant the summary
        prompt = f"""You are a financial analyst providing brief portfolio updates.
 
Generate exactly 4 sentences about this holding for a personal portfolio dashboard.
First sentence: What is the current market sentiment for this stock today (up/down, % change, price change)?
Second sentence: Any large inflows/outflows, news, or sector trends that might be impacting it today?
Third sentence: How does this holding compare to its sector peers in terms of performance?
Fourth sentence: What are the key factors driving the stock's movement today?
Keep it professional but accessible. Do not use jargon.
 
Holding: {stock_data.get("name", ticker)} ({ticker})
Current Price: ${stock_data.get("current_price", 0):.2f}
Today's Change: {stock_data.get("day_change_pct", 0):+.2f}% (${stock_data.get("day_change", 0):+.2f})
Day Range: ${stock_data.get("day_low", 0):.2f} – ${stock_data.get("day_high", 0):.2f}
52-Week Range: ${stock_data.get("fifty_two_week_low", 0):.2f} – ${stock_data.get("fifty_two_week_high", 0):.2f}
Sector: {stock_data.get("sector", "N/A")}"""

        message = client.messages.create(
            model=MODEL,
            max_tokens=150,  # 2 sentences ≈ 80-120 tokens
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
