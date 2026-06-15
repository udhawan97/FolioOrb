from fastapi import APIRouter, HTTPException, Query
from app.services.stock_service import (
    get_stock_data,
    get_all_quotes,
    get_historical_prices,
    DEFAULT_HOLDINGS,
)

# All routes in this file are grouped under the /api/stocks prefix
router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/prices")
async def get_all_prices():
    """Return live quotes for all default holdings."""
    quotes = get_all_quotes()
    return {"quotes": quotes, "count": len(quotes)}


@router.get("/price/{ticker}")
async def get_price(ticker: str):
    """
    Return a live quote for a single ticker.
    Example: GET /api/stocks/price/VOO
    """
    ticker = ticker.upper()
    quote = get_stock_data(ticker)
    # If the stock service couldn't fetch data, return a 404 with the reason
    if quote.get("error"):
        raise HTTPException(status_code=404, detail=quote["error"])
    return quote


@router.get("/history/{ticker}")
async def get_price_history(
    ticker: str,
    # Query parameter with a strict list of allowed values; defaults to 1 month
    period: str = Query("1mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|ytd)$"),
):
    """
    Return OHLCV (open/high/low/close/volume) price history for a ticker.
    Example: GET /api/stocks/history/VOO?period=3mo
    """
    history = get_historical_prices(ticker.upper(), period)
    return {"ticker": ticker.upper(), "period": period, "data": history}
