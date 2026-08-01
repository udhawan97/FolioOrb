"""
World market indices — the index strip and the market-context baseline.

One tracked-index list, one per-index quote fetch, and one cached fan-out over
the whole list.  ``fetch_world_market`` stays public for the analytics snapshot,
which walks the list sequentially once per build; every other caller wants
``get_world_markets_cached()`` — the stocks router serving the dashboard strip,
and the startup warmup priming it before the first page load.

That fan-out used to live in the stocks router behind a hand-rolled
``(expiry, payload)`` global, which meant the app's composition root had to
import a private function *out of* an HTTP router to warm it.  Holding it here
puts the cache below the routers where both callers can reach it, and hands the
eviction, locking, and request-coalescing to ``ttl_cache``: two dashboards that
miss together now share one fan-out instead of each spinning up ten workers.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from app.services import market_data
from app.services.ttl_cache import ttl_cache

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # seconds — the strip is glanceable, not a trading feed

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


def _any_index_priced(markets: list[dict]) -> bool:
    """True when at least one index came back with a real price.

    Guards the cache against pinning a fully-zeroed strip for the whole window
    when Yahoo is briefly unreachable — an all-dead result is retried on the
    next request instead of being remembered as an answer.
    """
    return any((m.get("price") or 0) > 0 for m in markets)


@ttl_cache(ttl=_CACHE_TTL, cache_when=_any_index_priced, copy=list)
def get_world_markets_cached() -> list[dict]:
    """Quote every tracked index in parallel, cached for five minutes.

    Callers get their own list, so sorting or filtering the strip can't corrupt
    what the next caller reads.
    """
    with ThreadPoolExecutor(max_workers=min(10, len(WORLD_MARKETS))) as pool:
        return list(pool.map(fetch_world_market, WORLD_MARKETS))
