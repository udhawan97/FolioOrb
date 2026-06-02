from fastapi import APIRouter, HTTPException, Query
from app.services.stock_service import (
    get_stock_data,
    get_all_quotes,
    get_historical_prices,
    DEFAULT_HOLDINGS,
)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


# Calling api to retrieve stock data for a specific ticker and return it in a structured format
@router.get("/prices")
async def get_all_prices():
    quotes = get_all_quotes()
    return {"quotes": quotes, "count": len(quotes)}


@router.get("/price/{ticker}")
async def get_price(ticker: str):
    ticker = ticker.upper()
    quote = get_stock_data(ticker)
    if quote.get("error"):
        raise HTTPException(status_code=404, detail=quote["error"])
    return quote


@router.get("/history/{ticker}")
async def get_price_history(
    ticker: str,
    period: str = Query("1mo", regex="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|ytd)$"),
):
    history = get_historical_prices(ticker.upper(), period)
    return {"ticker": ticker.upper(), "period": period, "data": history}
