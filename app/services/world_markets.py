"""
World market indices — the index strip and the market-context baseline.

One tracked-index list and one per-index quote fetch, shared by two callers
with different needs: the stocks router maps ``fetch_world_market`` over a
thread pool behind its own TTL cache (the dashboard strip refreshes often),
while the analytics snapshot walks the list sequentially once per build.
Concurrency and caching stay with the callers; only the list and the single
quote live here, so an index added below appears in both surfaces at once.
"""
from __future__ import annotations

import logging

from app.services import market_data

logger = logging.getLogger(__name__)

WORLD_MARKETS: list[dict] = [
    {"ticker": "^GSPC",  "name": "S&P 500",     "region": "US",      "flag": "🇺🇸"},
    {"ticker": "^IXIC",  "name": "NASDAQ",       "region": "US",      "flag": "🇺🇸"},
    {"ticker": "^DJI",   "name": "Dow Jones",    "region": "US",      "flag": "🇺🇸"},
    {"ticker": "^FTSE",  "name": "FTSE 100",     "region": "Europe",  "flag": "🇬🇧"},
    {"ticker": "^GDAXI", "name": "DAX",          "region": "Europe",  "flag": "🇩🇪"},
    {"ticker": "^FCHI",  "name": "CAC 40",       "region": "Europe",  "flag": "🇫🇷"},
    {"ticker": "^N225",  "name": "Nikkei 225",   "region": "Asia",    "flag": "🇯🇵"},
    {"ticker": "^HSI",   "name": "Hang Seng",    "region": "Asia",    "flag": "🇭🇰"},
    {"ticker": "^NSEI",  "name": "Nifty 50",     "region": "Asia",    "flag": "🇮🇳"},
    {"ticker": "^AXJO",  "name": "ASX 200",      "region": "Pacific", "flag": "🇦🇺"},
]


def fetch_world_market(market: dict) -> dict:
    """Quote one index: the market's static fields plus price and day change.

    Never raises, and never returns a partial payload — a failed or priceless
    fetch zeroes the numbers rather than dropping keys, so one dead index
    can't blank the strip or trip up market-context scoring.
    """
    try:
        fast = market_data.get_fast_info(market["ticker"]) or {}
        price = float(fast.get("last_price") or 0)
        prev = float(fast.get("previous_close") or 0)
        if price > 0 and prev > 0:
            chg = price - prev
            chg_pct = chg / prev * 100
        else:
            chg = chg_pct = 0.0
        return {
            **market,
            "price": round(price, 2),
            "day_change": round(chg, 2),
            "day_change_pct": round(chg_pct, 2),
        }
    except Exception as exc:
        logger.warning(
            "World market fetch failed; ticker=%s exception_type=%s",
            market.get("ticker"),
            type(exc).__name__,
        )
        return {**market, "price": 0, "day_change": 0, "day_change_pct": 0}
