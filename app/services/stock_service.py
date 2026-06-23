import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import yfinance as yf

from app.config import settings
from app.services.security_type import classify_security

logger = logging.getLogger(__name__)
QUOTE_FETCH_ERROR = "Quote data is temporarily unavailable."

# Tickers fetched when no specific list is provided.
# Configure with DEFAULT_HOLDINGS=VOO,QQQ,... in .env.
DEFAULT_HOLDINGS: list[str] = settings.DEFAULT_HOLDINGS


def get_stock_data(ticker: str) -> dict:
    """
    Fetch live quote data for a single ticker using the yfinance library.

    yfinance pulls data from Yahoo Finance — no API key needed.
    Returns a dict with price, change, range, and metadata.
    On failure, returns a dict with an "error" key instead of raising an exception.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # Yahoo Finance uses different field names depending on the security type
        # (stocks vs ETFs vs mutual funds), so we try several fallbacks
        current_price: float = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")  # Used for ETFs/mutual funds
            or 0.0
        )
        prev_close: float = (
            info.get("previousClose") or info.get("regularMarketPreviousClose") or 0.0
        )

        # Calculate day change only when we have both prices
        if prev_close > 0 and current_price > 0:
            day_change = current_price - prev_close
            day_change_pct = (day_change / prev_close) * 100
        else:
            day_change = 0.0
            day_change_pct = 0.0

        bid = info.get("bid")
        ask = info.get("ask")
        bid_ask_spread_pct = None
        if bid is not None and ask is not None and current_price > 0:
            bid_ask_spread_pct = round((float(ask) - float(bid)) / current_price, 5)

        security_type = classify_security(ticker, info).value

        market_cap = info.get("marketCap") or 0
        free_cashflow = info.get("freeCashflow")
        fcf_yield = None
        if free_cashflow is not None and market_cap:
            try:
                fcf_yield = round(float(free_cashflow) / float(market_cap) * 100, 2)
            except (TypeError, ValueError, ZeroDivisionError):
                fcf_yield = None

        # Helper: round a numeric field to n decimal places, or return None if missing.
        # Using explicit None check instead of `or 0` so callers can distinguish
        # "zero" from "not available" — important for ratio display in the UI.
        def _r(val, n: int):
            return round(val, n) if val is not None else None

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
            "volume": info.get("volume") or info.get("regularMarketVolume") or 0,
            "average_volume": info.get("averageVolume") or info.get("averageVolume10days") or 0,
            "market_cap": market_cap,
            "enterprise_value": info.get("enterpriseValue"),
            "total_revenue": info.get("totalRevenue"),
            "ebitda": info.get("ebitda"),
            "free_cashflow": free_cashflow,
            "fcf_yield": fcf_yield,
            "aum": info.get("totalAssets") or info.get("netAssets"),
            "bid": bid,
            "ask": ask,
            "bid_ask_spread_pct": bid_ask_spread_pct,
            "expense_ratio": (
                info.get("annualReportExpenseRatio")
                or info.get("expenseRatio")
                or info.get("netExpenseRatio")
            ),
            "holdings_count": info.get("holdingsCount"),
            "pe_ratio": _r(info.get("trailingPE"), 2),
            "forward_pe": _r(info.get("forwardPE"), 2),
            "price_to_sales": _r(info.get("priceToSalesTrailing12Months"), 2),
            "enterprise_to_revenue": _r(info.get("enterpriseToRevenue"), 2),
            "enterprise_to_ebitda": _r(info.get("enterpriseToEbitda"), 2),
            "revenue_growth": info.get("revenueGrowth"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "profit_margin": info.get("profitMargins"),
            "dividend_yield": _r(info.get("dividendYield"), 4),
            "currency": info.get("currency") or "USD",
            "sector": info.get("sector") or info.get("categoryName") or "N/A",
            "quote_type": info.get("quoteType") or "EQUITY",
            "security_type": security_type,
            "error": None,
        }

    except Exception as exc:
        logger.error(
            "Error fetching stock data; exception_type=%s",
            type(exc).__name__,
        )
        # Return a safe error dict so callers can check quote["error"] instead of crashing
        return {
            "ticker": ticker.upper(),
            "name": ticker,
            "current_price": 0.0,
            "day_change": 0.0,
            "day_change_pct": 0.0,
            "error": QUOTE_FETCH_ERROR,
        }


def get_all_quotes(tickers: Optional[list[str]] = None) -> list[dict]:
    """
    Fetch live quotes for a list of tickers in parallel.
    Defaults to DEFAULT_HOLDINGS when no list is provided.
    Quote order matches the input ticker order.
    """
    if tickers is None:
        tickers = DEFAULT_HOLDINGS
    if not tickers:
        return []
    with ThreadPoolExecutor(max_workers=min(10, len(tickers))) as pool:
        quotes = list(pool.map(get_stock_data, tickers))
    logger.info("Fetched %d quotes", len(quotes))
    return quotes


def get_historical_prices(ticker: str, period: str = "1mo") -> list[dict]:
    """
    Return daily OHLCV (open/high/low/close/volume) data for a ticker.

    period examples: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd"
    Returns an empty list if the data cannot be fetched.
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        results = []
        for date, row in hist.iterrows():
            results.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                }
            )
        return results
    except Exception as exc:
        logger.error(
            "Error fetching historical data; exception_type=%s",
            type(exc).__name__,
        )
        return []


