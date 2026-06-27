import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import yfinance as yf

from app.config import settings
from app.services.security_type import classify_security

logger = logging.getLogger(__name__)
QUOTE_FETCH_ERROR = "Quote data is temporarily unavailable."

_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}
_QUOTE_TTL = 60
_HISTORY_CACHE: dict[tuple[str, str], tuple[float, list]] = {}
_HISTORY_TTL = 300
TICKER_PATTERN = re.compile(r"^[A-Z0-9.^-]{1,10}$")
SUGGESTION_QUERY_PATTERN = re.compile(r"[^A-Za-z0-9 .^\-&]")
SUPPORTED_QUOTE_TYPES = {
    "EQUITY",
    "ETF",
    "MUTUALFUND",
    "CRYPTOCURRENCY",
    "INDEX",
}

# Tickers fetched when no specific list is provided.
# Configure with DEFAULT_HOLDINGS=VOO,QQQ,... in .env.
DEFAULT_HOLDINGS: list[str] = settings.DEFAULT_HOLDINGS


def normalize_ticker(ticker: str) -> str:
    """Normalize user-entered symbols before validation or storage."""
    return (ticker or "").strip().upper()


def ticker_shape_is_safe(ticker: str) -> bool:
    """Keep ticker input narrow enough to be safe in logs, URLs, and storage."""
    return bool(TICKER_PATTERN.fullmatch(normalize_ticker(ticker)))


def _clean_suggestion_query(query: str) -> str:
    """Allow company-name searches while stripping punctuation used in injections."""
    return SUGGESTION_QUERY_PATTERN.sub("", (query or "").strip())[:80]


def quote_resolves(quote: dict) -> bool:
    """Return True only when Yahoo returned usable market data for a symbol."""
    if not quote or quote.get("error"):
        return False
    price = quote.get("current_price") or 0.0
    return price > 0


def get_stock_data(ticker: str) -> dict:
    """
    Fetch live quote data for a single ticker using the yfinance library.

    yfinance pulls data from Yahoo Finance — no API key needed.
    Returns a dict with price, change, range, and metadata.
    On failure, returns a dict with an "error" key instead of raising an exception.
    Results are cached for _QUOTE_TTL seconds to keep dashboard loads snappy.
    """
    now = time.monotonic()
    cached = _QUOTE_CACHE.get(ticker)
    if cached and cached[0] > now:
        return cached[1]

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

        result = {
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
            "fifty_day_average": _r(info.get("fiftyDayAverage"), 2),
            "two_hundred_day_average": _r(info.get("twoHundredDayAverage"), 2),
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
        _QUOTE_CACHE[ticker] = (now + _QUOTE_TTL, result)
        return result

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


def _fast_float(value, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def get_fast_quote(ticker: str) -> dict:
    """
    Lightweight quote via yfinance fast_info — much faster than stock.info.
    Used for portfolio valuation on dashboard load; falls back to full fetch
    when fast_info does not return a usable price.
    """
    ticker = normalize_ticker(ticker)
    cache_key = f"fast:{ticker}"
    now = time.monotonic()
    cached = _QUOTE_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    try:
        fi = yf.Ticker(ticker).fast_info
        current_price = _fast_float(getattr(fi, "last_price", None))
        prev_close = _fast_float(getattr(fi, "previous_close", None))
        if current_price <= 0:
            return get_stock_data(ticker)

        if prev_close > 0:
            day_change = current_price - prev_close
            day_change_pct = (day_change / prev_close) * 100
        else:
            day_change = 0.0
            day_change_pct = 0.0

        year_high = _fast_float(
            getattr(fi, "year_high", None) or getattr(fi, "fifty_two_week_high", None)
        )
        year_low = _fast_float(
            getattr(fi, "year_low", None) or getattr(fi, "fifty_two_week_low", None)
        )
        security_type = classify_security(ticker, None).value

        result = {
            "ticker": ticker,
            "name": ticker,
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "day_change": round(day_change, 2),
            "day_change_pct": round(day_change_pct, 2),
            "day_high": round(_fast_float(getattr(fi, "day_high", None), current_price), 2),
            "day_low": round(_fast_float(getattr(fi, "day_low", None), current_price), 2),
            "fifty_two_week_high": round(year_high, 2) if year_high > 0 else 0,
            "fifty_two_week_low": round(year_low, 2) if year_low > 0 else 0,
            "fifty_day_average": None,
            "two_hundred_day_average": None,
            "volume": int(_fast_float(getattr(fi, "last_volume", None))),
            "average_volume": 0,
            "market_cap": int(_fast_float(getattr(fi, "market_cap", None))),
            "enterprise_value": None,
            "total_revenue": None,
            "ebitda": None,
            "free_cashflow": None,
            "fcf_yield": None,
            "aum": None,
            "bid": None,
            "ask": None,
            "bid_ask_spread_pct": None,
            "expense_ratio": None,
            "holdings_count": None,
            "pe_ratio": None,
            "forward_pe": None,
            "price_to_sales": None,
            "enterprise_to_revenue": None,
            "enterprise_to_ebitda": None,
            "revenue_growth": None,
            "gross_margin": None,
            "operating_margin": None,
            "profit_margin": None,
            "dividend_yield": None,
            "currency": str(getattr(fi, "currency", None) or "USD"),
            "sector": "N/A",
            "quote_type": "ETF" if security_type == "ETF" else "EQUITY",
            "security_type": security_type,
            "error": None,
        }
        _QUOTE_CACHE[cache_key] = (now + _QUOTE_TTL, result)
        return result
    except Exception as exc:
        logger.warning(
            "Fast quote failed, falling back to full fetch; ticker=%s exception_type=%s",
            ticker,
            type(exc).__name__,
        )
        return get_stock_data(ticker)


def suggest_tickers(query: str, limit: int = 3) -> list[dict]:
    """Return likely ticker matches from Yahoo Finance search."""
    query = _clean_suggestion_query(query)
    if not query:
        return []

    try:
        search = yf.Search(
            query,
            max_results=max(limit, 3),
            news_count=0,
            lists_count=0,
            include_research=False,
            raise_errors=False,
            timeout=5,
        )
        suggestions = []
        seen = set()
        for item in search.quotes or []:
            symbol = str(item.get("symbol") or "").upper().strip()
            if not symbol or symbol in seen or not ticker_shape_is_safe(symbol):
                continue
            quote_type = str(item.get("quoteType") or item.get("typeDisp") or "").upper()
            if quote_type and quote_type not in SUPPORTED_QUOTE_TYPES:
                continue
            seen.add(symbol)
            suggestions.append({
                "ticker": symbol,
                "name": item.get("longname") or item.get("shortname") or symbol,
                "exchange": item.get("exchDisp") or item.get("exchange") or "",
            })
            if len(suggestions) >= limit:
                break
        return suggestions
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "Ticker search failed; exception_type=%s",
            type(exc).__name__,
        )
        return []


def validate_ticker_symbol(ticker: str, suggestion_limit: int = 3) -> dict:
    """
    Validate that a user-entered ticker is safe and resolves to live quote data.

    The shape check protects the app from injection-shaped strings before any
    network call. The quote check prevents arbitrary safe-looking text from
    becoming a portfolio holding.
    """
    normalized = normalize_ticker(ticker)
    if not ticker_shape_is_safe(normalized):
        return {
            "valid": False,
            "ticker": normalized,
            "message": (
                "Ticker can use only letters, numbers, '.', '-', or '^' "
                "and must be 10 characters or fewer."
            ),
            "suggestions": suggest_tickers(ticker, limit=suggestion_limit),
        }

    quote = get_stock_data(normalized)
    if not quote_resolves(quote):
        return {
            "valid": False,
            "ticker": normalized,
            "message": f"Couldn't find ticker {normalized} — check the symbol",
            "suggestions": suggest_tickers(normalized, limit=suggestion_limit),
        }

    return {
        "valid": True,
        "ticker": normalized,
        "quote": quote,
        "suggestions": [],
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


def get_portfolio_quotes(tickers: Optional[list[str]] = None) -> list[dict]:
    """Fast parallel quotes for dashboard portfolio valuation."""
    if tickers is None:
        tickers = DEFAULT_HOLDINGS
    if not tickers:
        return []
    with ThreadPoolExecutor(max_workers=min(10, len(tickers))) as pool:
        quotes = list(pool.map(get_fast_quote, tickers))
    logger.info("Fetched %d fast portfolio quotes", len(quotes))
    return quotes


def get_historical_prices(ticker: str, period: str = "1mo") -> list[dict]:
    """
    Return daily OHLCV (open/high/low/close/volume) data for a ticker.

    period examples: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
    Returns an empty list if the data cannot be fetched.
    Rows where any OHLCV field is NaN or non-finite are silently dropped so the
    caller always receives JSON-safe floats (Starlette serializes with allow_nan=False).
    """
    try:
        cache_key = (ticker.upper(), period)
        now = time.monotonic()
        cached = _HISTORY_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        results = []
        for date, row in hist.iterrows():
            open_ = float(row["Open"])
            high = float(row["High"])
            low = float(row["Low"])
            close = float(row["Close"])
            volume = float(row["Volume"])
            if not all(math.isfinite(v) for v in (open_, high, low, close, volume)):
                continue
            results.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "open": round(open_, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": int(volume),
                }
            )
        _HISTORY_CACHE[cache_key] = (now + _HISTORY_TTL, results)
        return results
    except Exception as exc:
        logger.error(
            "Error fetching historical data; exception_type=%s",
            type(exc).__name__,
        )
        return []
