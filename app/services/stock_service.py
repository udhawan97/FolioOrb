import yfinance as yf 
import logging 
from typing import Optional

#Setting up logging configuration
logger = logging.getLogger(__name__)

DEFAULT_HOLDINGS: list[str] = ["NOW", "QTUM", "VOO", "CGDV", "IBIT", "VT", "ITA", "IEMG", "SETM", "WSML"]

#Getting stock data for a specific ticker using yfinance and returning it in a structured format
def get_stock_data(ticker: str) -> dict:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        current_price: float = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")
            or 0.0
            )
        prev_close: float = (
            info.get("previousClose")
            or info.get("regularMarketPreviousClose")
            or 0.0
            )
        
        if prev_close > 0 and current_price > 0:
            day_change = current_price - prev_close
            day_change_pct = (day_change / prev_close) * 100
        else:
            day_change = 0.0
            day_change_pct = 0.0
        return {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName") or ticker,
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "day_change": round(day_change, 2),
            "day_change_pct": round(day_change_pct, 2),
            "day_high": round(info.get("dayHigh") or current_price, 2),
            "day_low": round(info.get("dayLow") or current_price, 2),
            "fifty_two_week_high": round(info.get("fiftyTwoWeekHigh") or 0, 2),
            "fifty_two_week_low": round(info.get("fiftyTwoWeekLow") or 0, 2),
            "volume": info.get("volume") or info.get("averageVolume") or 0,
            "market_cap": info.get("marketCap") or 0,
            "pe_ratio": round(info.get("trailingPE") or 0, 2),
            "dividend_yield": round(info.get("dividendYield") or 0, 4),
            "currency": info.get("currency") or "USD",
            "sector": info.get("sector") or "N/A",
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error fetching data for {ticker}: {e}")
        return {
            "ticker": ticker.upper(),
            "name": ticker,
            "current_price": 0.0,
            "day_change": 0.0,
            "day_change_pct": 0.0,
            "error": str(e),
        }

#Getting stock data for a list of tickers and returning it as a list of structured dictionaries
def get_all_quotes(tickers: list[str] = None) -> list[dict]:
    if tickers is None:
        tickers = DEFAULT_HOLDINGS
    quotes = [] 
    for ticker in tickers:
        quote = get_stock_data(ticker)
        quotes.append(quote)
        logger.info(f"Fetched {ticker}: ${quote.get('current_price', 'N/A')}")
    return quotes

def get_historical_prices (ticker: str, period: str = "1mo") -> dict:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        results = []
        for date, row in hist.iterrows():
            results.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        return results
    except Exception as e:
        logger.error(f"Error fetching historical data for {ticker}: {e}")
        return []