from datetime import datetime
import pytz
from fastapi import APIRouter, HTTPException, Query
from app.services.stock_service import (
    get_stock_data,
    get_all_quotes,
    get_historical_prices,
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


@router.get("/history/batch")
async def get_batch_history(
    tickers: str = "NOW,QTUM,VOO,CGDV,IBIT,VT,ITA,IEMG,SETM,WSML",
    period: str = "1mo"
):
    """
    Fetch historical prices for multiple tickers at once.
    tickers: comma-separated list
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y
    Example: GET /api/stocks/history/batch?period=1mo
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",")]
    result = {}
    for ticker in ticker_list:
        result[ticker] = get_historical_prices(ticker, period)
    return {"period": period, "data": result}


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
