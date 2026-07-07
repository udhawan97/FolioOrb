"""
app/services/stock_service.py

Central data-fetching layer for all yfinance calls.

Design note — shared `.info` cache:
  Every service that needs Yahoo Finance fundamentals (quotes, analyst recs,
  holding intelligence, ETF profiles) calls `get_ticker_info()` instead of
  `yf.Ticker(t).info` directly. This ensures the expensive network scrape
  happens at most once per ticker per cache window and is reused everywhere,
  eliminating the biggest source of repeated latency on dashboard load.
"""
from __future__ import annotations

import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import pytz
import yfinance as yf

from app.config import settings
from app.services.security_type import classify_security

logger = logging.getLogger(__name__)

# ── Module-level constants ─────────────────────────────────────────────────────

QUOTE_FETCH_ERROR = "Quote data is temporarily unavailable."

# Ticker symbols: letters, digits, '.', '-', '^'; max 10 chars.
TICKER_PATTERN = re.compile(r"^[A-Z0-9.^-]{1,10}$")

# Suggestion queries: allow company-name chars, strip injection-prone punctuation.
SUGGESTION_QUERY_PATTERN = re.compile(r"[^A-Za-z0-9 .^\-&]")

SUPPORTED_QUOTE_TYPES = {"EQUITY", "ETF", "MUTUALFUND", "CRYPTOCURRENCY", "INDEX"}

# Populated from DEFAULT_HOLDINGS in .env; used when no ticker list is supplied.
DEFAULT_HOLDINGS: list[str] = settings.DEFAULT_HOLDINGS

# ── Cache tables ───────────────────────────────────────────────────────────────
# Each entry is (expiry_monotonic, payload); stale entries are replaced on read.

_INFO_CACHE: dict[str, tuple[float, dict]] = {}
_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}
_HISTORY_CACHE: dict[tuple[str, str], tuple[float, list]] = {}

# TTLs in seconds.  Caches live longer while the market is closed because
# prices and fundamentals barely move outside trading hours.
_INFO_TTL = 300             # 5 min while open
_INFO_TTL_CLOSED = 3600     # 1 hr  while closed
_QUOTE_TTL = 60             # 1 min while open
_QUOTE_TTL_CLOSED = 900     # 15 min while closed
_HISTORY_TTL = 300

_EASTERN = pytz.timezone("America/New_York")


# ── Pure helpers ───────────────────────────────────────────────────────────────

def normalize_ticker(ticker: str) -> str:
    """Strip whitespace and upper-case a user-supplied ticker symbol."""
    return (ticker or "").strip().upper()


def ticker_shape_is_safe(ticker: str) -> bool:
    """Return True if the symbol is narrow enough to be safe in logs, URLs, and storage."""
    return bool(TICKER_PATTERN.fullmatch(normalize_ticker(ticker)))


def _clean_suggestion_query(query: str) -> str:
    """Allow company-name searches while stripping punctuation used in injections."""
    return SUGGESTION_QUERY_PATTERN.sub("", (query or "").strip())[:80]


def quote_resolves(quote: dict) -> bool:
    """Return True only when Yahoo returned usable market data for the symbol."""
    if not quote or quote.get("error"):
        return False
    return (quote.get("current_price") or 0.0) > 0


def _fast_float(value, default: float = 0.0) -> float:
    """Cast to float, returning `default` for None, NaN, or Inf."""
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _round_or_none(val, decimals: int):
    """Round to `decimals` places, or return None when the value is absent."""
    return round(val, decimals) if val is not None else None


# ── Market-hours detection ─────────────────────────────────────────────────────

def _market_is_open() -> bool:
    """Best-effort US market-hours check (no holiday calendar)."""
    now = datetime.now(_EASTERN)
    if now.weekday() >= 5:  # Saturday / Sunday
        return False
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now <= close_t


def _quote_ttl() -> float:
    return _QUOTE_TTL if _market_is_open() else _QUOTE_TTL_CLOSED


def _info_ttl() -> float:
    return _INFO_TTL if _market_is_open() else _INFO_TTL_CLOSED


# ── Core fetch functions ───────────────────────────────────────────────────────

def get_ticker_info(ticker: str) -> dict:
    """
    Fetch and cache yfinance `.info` for a ticker.

    Call this instead of ``yf.Ticker(t).info`` directly so the expensive
    Yahoo scrape happens at most once per ticker per cache window.
    """
    symbol = normalize_ticker(ticker)
    now = time.monotonic()
    cached = _INFO_CACHE.get(symbol)
    if cached and cached[0] > now:
        return cached[1]
    info = yf.Ticker(symbol).info or {}
    _INFO_CACHE[symbol] = (now + _info_ttl(), info)
    return info


def get_stock_data(ticker: str) -> dict:
    """
    Fetch a full live quote for a single ticker via yfinance (no API key needed).

    Returns a dict with price, change, range, valuation ratios, and metadata.
    On failure returns a dict with an ``"error"`` key so callers never raise.
    Results are cached for `_QUOTE_TTL` seconds.
    """
    ticker = normalize_ticker(ticker)
    now = time.monotonic()
    cached = _QUOTE_CACHE.get(ticker)
    if cached and cached[0] > now:
        return cached[1]

    try:
        info = get_ticker_info(ticker)

        # Yahoo uses different field names per security type; try several fallbacks.
        current_price: float = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")   # ETFs / mutual funds
            or 0.0
        )
        prev_close: float = (
            info.get("previousClose") or info.get("regularMarketPreviousClose") or 0.0
        )

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
                pass

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
            "fifty_day_average": _round_or_none(info.get("fiftyDayAverage"), 2),
            "two_hundred_day_average": _round_or_none(info.get("twoHundredDayAverage"), 2),
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
            "pe_ratio": _round_or_none(info.get("trailingPE"), 2),
            "forward_pe": _round_or_none(info.get("forwardPE"), 2),
            "price_to_sales": _round_or_none(info.get("priceToSalesTrailing12Months"), 2),
            "enterprise_to_revenue": _round_or_none(info.get("enterpriseToRevenue"), 2),
            "enterprise_to_ebitda": _round_or_none(info.get("enterpriseToEbitda"), 2),
            "revenue_growth": info.get("revenueGrowth"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "profit_margin": info.get("profitMargins"),
            "dividend_yield": _round_or_none(info.get("dividendYield"), 4),
            "currency": info.get("currency") or "USD",
            "sector": info.get("sector") or info.get("categoryName") or "N/A",
            "quote_type": info.get("quoteType") or "EQUITY",
            "security_type": security_type,
            "error": None,
        }
        _QUOTE_CACHE[ticker] = (now + _quote_ttl(), result)
        return result

    except Exception as exc:
        logger.error("Error fetching stock data; exception_type=%s", type(exc).__name__)
        return {
            "ticker": ticker.upper(),
            "name": ticker,
            "current_price": 0.0,
            "day_change": 0.0,
            "day_change_pct": 0.0,
            "error": QUOTE_FETCH_ERROR,
        }


def get_fast_quote(ticker: str) -> dict:
    """
    Lightweight quote via yfinance ``fast_info`` — much faster than ``.info``.
    Used for portfolio valuation on dashboard load.
    Falls back to `get_stock_data` when ``fast_info`` returns no usable price.
    """
    ticker = normalize_ticker(ticker)
    cache_key = f"fast:{ticker}"
    now = time.monotonic()
    cached = _QUOTE_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    def _fallback() -> dict:
        # Cache the full-quote fallback under the fast key too, so a ticker whose
        # fast_info never carries a price doesn't re-run the fast_info network call
        # on every dashboard valuation refresh.
        result = get_stock_data(ticker)
        _QUOTE_CACHE[cache_key] = (now + _quote_ttl(), result)
        return result

    try:
        fi = yf.Ticker(ticker).fast_info
        current_price = _fast_float(getattr(fi, "last_price", None))
        prev_close = _fast_float(getattr(fi, "previous_close", None))
        if current_price <= 0:
            return _fallback()

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
            # Fields unavailable from fast_info; callers should upgrade to get_stock_data
            # if they need these ratios.
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
        _QUOTE_CACHE[cache_key] = (now + _quote_ttl(), result)
        return result

    except Exception as exc:
        logger.warning(
            "Fast quote failed, falling back to full fetch; ticker=%s exception_type=%s",
            ticker,
            type(exc).__name__,
        )
        return _fallback()


# ── Search and validation ──────────────────────────────────────────────────────

def suggest_tickers(query: str, limit: int = 3) -> list[dict]:
    """Return likely ticker matches from Yahoo Finance search (used for autocomplete)."""
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
        seen: set[str] = set()
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
        logger.warning("Ticker search failed; exception_type=%s", type(exc).__name__)
        return []


def validate_ticker_symbol(ticker: str, suggestion_limit: int = 3) -> dict:
    """
    Validate that a user-entered ticker is safe and resolves to live quote data.

    Shape check: rejects injection-shaped strings before any network call.
    Quote check: prevents arbitrary safe-looking text from becoming a holding.
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

    return {"valid": True, "ticker": normalized, "quote": quote, "suggestions": []}


# ── Portfolio-level parallel fetching ─────────────────────────────────────────

def _parallel_fetch(tickers: list[str], fetch_fn) -> list[dict]:
    """Fan out `fetch_fn` over `tickers` using a thread pool; preserve input order."""
    with ThreadPoolExecutor(max_workers=min(10, len(tickers))) as pool:
        return list(pool.map(fetch_fn, tickers))


def get_all_quotes(tickers: Optional[list[str]] = None) -> list[dict]:
    """
    Fetch full live quotes for a list of tickers in parallel.
    Defaults to DEFAULT_HOLDINGS when no list is provided.
    """
    tickers = tickers if tickers is not None else DEFAULT_HOLDINGS
    if not tickers:
        return []
    quotes = _parallel_fetch(tickers, get_stock_data)
    logger.info("Fetched %d quotes", len(quotes))
    return quotes


def get_portfolio_quotes(tickers: Optional[list[str]] = None) -> list[dict]:
    """Fast parallel quotes for dashboard portfolio valuation (uses fast_info)."""
    tickers = tickers if tickers is not None else DEFAULT_HOLDINGS
    if not tickers:
        return []
    quotes = _parallel_fetch(tickers, get_fast_quote)
    logger.info("Fetched %d fast portfolio quotes", len(quotes))
    return quotes


def warm_caches(tickers: Optional[list[str]] = None) -> None:
    """
    Pre-populate the quote + `.info` caches in parallel so the first dashboard
    load hits warm data instead of cold Yahoo. Safe to call from a background
    thread on startup; failures are swallowed.
    """
    targets = [t for t in (tickers or DEFAULT_HOLDINGS) if t]
    if not targets:
        return
    try:
        # get_all_quotes fills both _QUOTE_CACHE and _INFO_CACHE (via get_ticker_info),
        # so analyst recs and holding intelligence also benefit from the warmup.
        get_all_quotes(targets)
        get_portfolio_quotes(targets)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Cache warmup failed; exception_type=%s", type(exc).__name__)


# ── Historical price data ──────────────────────────────────────────────────────

def get_historical_prices(ticker: str, period: str = "1mo") -> list[dict]:
    """
    Return daily OHLCV data for a ticker.

    Accepted period strings: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y",
    "5y", "10y", "ytd", "max".  Returns [] on fetch failure.

    Rows where any OHLCV field is NaN or non-finite are silently dropped so
    callers always receive JSON-safe floats (Starlette serializes with
    allow_nan=False).
    """
    cache_key = (ticker.upper(), period)
    now = time.monotonic()
    cached = _HISTORY_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    try:
        hist = yf.Ticker(ticker).history(period=period)
        results = []
        for date, row in hist.iterrows():
            open_ = float(row["Open"])
            high = float(row["High"])
            low = float(row["Low"])
            close = float(row["Close"])
            volume = float(row["Volume"])
            if not all(math.isfinite(v) for v in (open_, high, low, close, volume)):
                continue
            results.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": int(volume),
            })
        if results:
            _HISTORY_CACHE[cache_key] = (now + _HISTORY_TTL, results)
        return results
    except Exception as exc:
        logger.error("Error fetching historical data; exception_type=%s", type(exc).__name__)
        return []
