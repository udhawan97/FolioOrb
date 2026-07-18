import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pytz
from fastapi import APIRouter, HTTPException, Query
from app.services import market_data
from app.services.stock_service import (
    DEFAULT_HOLDINGS,
    QUOTE_FETCH_ERROR,
    get_stock_data,
    get_all_quotes,
    get_historical_prices,
)
from app.services.world_markets import WORLD_MARKETS, fetch_world_market

logger = logging.getLogger(__name__)

# All routes in this file are grouped under the /api/stocks prefix
router = APIRouter(prefix="/api/stocks", tags=["stocks"])

_WORLD_MARKETS_CACHE: tuple[float, list] | None = None
_WORLD_MARKETS_TTL = 300  # seconds


def _get_world_markets_cached() -> list:
    global _WORLD_MARKETS_CACHE  # pylint: disable=global-statement
    now = time.monotonic()
    if _WORLD_MARKETS_CACHE and _WORLD_MARKETS_CACHE[0] > now:
        return _WORLD_MARKETS_CACHE[1]

    with ThreadPoolExecutor(max_workers=min(10, len(WORLD_MARKETS))) as pool:
        results = list(pool.map(fetch_world_market, WORLD_MARKETS))

    _WORLD_MARKETS_CACHE = (now + _WORLD_MARKETS_TTL, results)
    return results


def _fetch_ticker_history(ticker: str, period: str) -> tuple[str, list]:
    try:
        return ticker, get_historical_prices(ticker, period)
    except Exception as exc:
        logger.warning(
            "Batch history skipped ticker; ticker=%s exception_type=%s",
            ticker,
            type(exc).__name__,
        )
        return ticker, []


@router.get("/prices")
def get_all_prices():
    """Return live quotes for configured default holdings."""
    quotes = get_all_quotes()
    return {"quotes": quotes, "count": len(quotes)}


@router.get("/price/{ticker}")
def get_price(ticker: str):
    """
    Return a live quote for a single ticker.
    Example: GET /api/stocks/price/VOO
    """
    ticker = ticker.upper()
    quote = get_stock_data(ticker)
    # If the stock service couldn't fetch data, return a 404 with the reason
    if quote.get("error"):
        raise HTTPException(status_code=404, detail=QUOTE_FETCH_ERROR)
    return quote


@router.get("/history/batch")
def get_batch_history(
    tickers: str | None = None,
    period: str = Query("1mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|ytd|max)$"),
):
    """
    Fetch historical prices for multiple tickers at once.
    tickers: comma-separated list. Defaults to configured DEFAULT_HOLDINGS.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    Example: GET /api/stocks/history/batch?period=1mo
    """
    ticker_list = (
        [t.strip().upper() for t in tickers.split(",") if t.strip()]
        if tickers
        else DEFAULT_HOLDINGS
    )
    if not ticker_list:
        return {"period": period, "data": {}}

    with ThreadPoolExecutor(max_workers=min(10, len(ticker_list))) as pool:
        pairs = pool.map(
            lambda ticker: _fetch_ticker_history(ticker, period),
            ticker_list,
        )
    return {"period": period, "data": dict(pairs)}


@router.get("/history/{ticker}")
def get_price_history(
    ticker: str,
    # Query parameter with a strict list of allowed values; defaults to 1 month
    period: str = Query("1mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|ytd|max)$"),
):
    """
    Return OHLCV (open/high/low/close/volume) price history for a ticker.
    Example: GET /api/stocks/history/VOO?period=3mo
    """
    history = get_historical_prices(ticker.upper(), period)
    return {"ticker": ticker.upper(), "period": period, "data": history}

@router.get("/market-status")
async def get_market_status():
    """Check if US markets are currently open."""
    eastern = pytz.timezone("America/New_York")
    now = datetime.now(eastern)

    is_weekday = now.weekday() < 5  # Monday=0, Friday=4
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)

    is_open = is_weekday and market_open <= now <= market_close

    # Describe the next opening only while the market is closed.
    if is_open:
        next_open = None
    elif is_weekday and now < market_open:
        next_open = "9:30 AM ET today"      # weekday, before the bell
    elif now.weekday() >= 4:
        next_open = "Mon 9:30 AM ET"        # Fri after close, or the weekend
    else:
        next_open = "9:30 AM ET tomorrow"   # Mon–Thu after close

    return {
        "is_open": is_open,
        "status": "OPEN" if is_open else "CLOSED",
        "eastern_time": now.strftime("%I:%M %p ET"),
        "next_open": next_open,
    }


@router.get("/world-markets")
def get_world_markets():
    """
    Return current quotes for major world market indices.
    Uses fast_info for speed (single lightweight request per ticker).
    Results are cached for 5 minutes and fetched in parallel.
    """
    return {"markets": _get_world_markets_cached()}
