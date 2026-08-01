import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Query
from app.services import market_hours
from app.services.stock_service import (
    DEFAULT_HOLDINGS,
    QUOTE_FETCH_ERROR,
    get_stock_data,
    get_all_quotes,
    get_historical_prices,
)
from app.services.world_markets import get_world_markets_cached

logger = logging.getLogger(__name__)

# All routes in this file are grouped under the /api/stocks prefix
router = APIRouter(prefix="/api/stocks", tags=["stocks"])


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
    """Check if US markets are currently open.

    Pure clock arithmetic — no I/O, so this one genuinely belongs on the loop.
    """
    return market_hours.session_status()


@router.get("/world-markets")
def get_world_markets():
    """
    Return current quotes for major world market indices.
    Uses fast_info for speed (single lightweight request per ticker).
    Results are cached for 5 minutes and fetched in parallel.
    """
    return {"markets": get_world_markets_cached()}
