"""
app/services/stock_service.py

Quotes, price history, and symbol search — Yahoo's fields as the app reads them.

The vendor is not named in this module. Every read goes through
``market_data``, the one place that imports yfinance. What lives *here* is what
a quote means: which of Yahoo's several price fields to believe, how a dividend
yield and an expense ratio are denominated, which symbols are safe to store or
log, and how long each answer is worth keeping.

Design note — shared `.info` cache:
  Every service that needs Yahoo Finance fundamentals (quotes, analyst recs,
  holding intelligence, ETF profiles) calls `get_ticker_info()` rather than
  reading the seam itself, so the expensive scrape happens at most once per
  ticker per cache window and is reused everywhere — the single biggest source
  of repeated latency on dashboard load.
"""
from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz

from app.config import settings
from app.services import market_data
from app.services.security_type import classify_security
from app.services.ttl_cache import ttl_cache

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

# ── Cache windows ──────────────────────────────────────────────────────────────
# Expiry, storage, and the force_refresh bypass live in `ttl_cache`; each fetcher
# below says only how long its answer is worth keeping.
#
# TTLs in seconds.  Caches live longer while the market is closed because
# prices and fundamentals barely move outside trading hours.
_INFO_TTL = 300             # 5 min while open
_INFO_TTL_CLOSED = 3600     # 1 hr  while closed
_QUOTE_TTL = 60             # 1 min while open
_QUOTE_TTL_CLOSED = 900     # 15 min while closed
_HISTORY_TTL = 300

_EASTERN = pytz.timezone("America/New_York")


class InfoUnavailable(RuntimeError):
    """The `.info` read itself failed — not the same as Yahoo having nothing to say.

    ``market_data`` reports both as absence, but this module has to tell them
    apart: an empty record is an *answer* and is worth remembering for the
    window, while an unreachable Yahoo has to be retried. Raising is what keeps
    the failure out of the store, since ``ttl_cache`` remembers returns and
    never raises. Every caller of `get_ticker_info` already guards it with
    ``except Exception``, so this needs no handling it doesn't already get.
    """


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

@ttl_cache(ttl=_info_ttl, key=normalize_ticker)
def get_ticker_info(ticker: str) -> dict:
    """
    Fetch and cache Yahoo's full `.info` record for a ticker.

    Call this instead of reading `market_data.get_info` directly so the
    expensive Yahoo scrape happens at most once per ticker per cache window.

    An empty record is remembered like any other answer — Yahoo says nothing
    about some symbols, and re-asking every call won't change its mind. A read
    that was *unavailable* raises `InfoUnavailable` instead, so a flaky network
    is never pinned for the window as "this symbol has no data".
    """
    info = market_data.get_info(ticker)
    if info is None:
        raise InfoUnavailable("ticker info read unavailable")
    return info


def _normalized_expense_ratio(info: dict) -> float | None:
    """Expense ratio as a fraction — 0.0003 means 0.03%.

    yfinance reports the same fee in two units, exactly 100x apart: VFIAX comes
    back with annualReportExpenseRatio 0.0086 *and* netExpenseRatio 0.86 for one
    0.86% fund. ETFs generally only carry the percent form. Every consumer here
    (etf_quality's cost tiers, the fee view, the UI) reads decimal, so the two
    are reconciled once, at the chokepoint, rather than guessed at downstream.
    """
    def _number(value) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if math.isnan(number) or number < 0:
            return None
        return number

    already_decimal = _number(info.get("annualReportExpenseRatio"))
    if already_decimal is not None:
        return already_decimal
    as_percent = _number(info.get("netExpenseRatio"))
    if as_percent is not None:
        return as_percent / 100.0
    return None


def _positive_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if math.isnan(number) or number <= 0:
        return None
    return number


def _ex_dividend_date(info: dict) -> str | None:
    """Next ex-dividend date as an ISO string, from yfinance's unix seconds."""
    raw = info.get("exDividendDate")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _normalized_dividend(info: dict, price) -> tuple[float | None, float | None]:
    """Forward dividend as ($/share rate, yield-as-fraction), or (None, None).

    yfinance's `dividendYield` is a PERCENT (0.32 = 0.32%) while
    `trailingAnnualDividendYield` is a FRACTION (0.0031) — the same fact, two
    fields, 100x apart. `dividendRate` ($/share) is unambiguous, so the yield is
    derived from rate/price whenever possible and the treacherous yield fields
    are only a fallback. Everything downstream reads a fraction.
    """
    rate = _positive_number(info.get("dividendRate")) or _positive_number(
        info.get("trailingAnnualDividendRate")
    )
    px = _positive_number(price)

    if rate is not None and px is not None:
        return rate, rate / px

    # No rate: fall back to a yield field, being careful about its units.
    as_percent = _positive_number(info.get("dividendYield"))
    if as_percent is not None:
        yld = as_percent / 100.0
    else:
        yld = _positive_number(info.get("trailingAnnualDividendYield"))  # already a fraction
    if yld is None:
        return None, None
    # Backfill the $/share rate from yield x price when we have a price.
    return (yld * px if px is not None else None), yld


@ttl_cache(
    ttl=_quote_ttl,
    key=normalize_ticker,
    # A quote that failed is never remembered, so the next caller retries
    # instead of staring at an error for the whole window.
    cache_when=lambda quote: not quote.get("error"),
)
def get_stock_data(ticker: str) -> dict:
    """
    Fetch a full live quote for a single ticker from Yahoo (no API key needed).

    Returns a dict with price, change, range, valuation ratios, and metadata.
    On failure returns a dict with an ``"error"`` key so callers never raise.
    Results are cached for `_QUOTE_TTL` seconds.
    """
    ticker = normalize_ticker(ticker)

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

        dividend_rate, dividend_yield = _normalized_dividend(info, current_price)
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
            "expense_ratio": _normalized_expense_ratio(info),
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
            "dividend_yield": _round_or_none(dividend_yield, 5),
            "dividend_rate": _round_or_none(dividend_rate, 4),
            "ex_dividend_date": _ex_dividend_date(info),
            "currency": info.get("currency") or "USD",
            "sector": info.get("sector") or info.get("categoryName") or "N/A",
            "quote_type": info.get("quoteType") or "EQUITY",
            "security_type": security_type,
            "error": None,
        }
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


@ttl_cache(ttl=_quote_ttl, key=normalize_ticker)
def get_fast_quote(ticker: str) -> dict:
    """
    Lightweight quote from the cheap price snapshot — much faster than ``.info``.
    Used for portfolio valuation on dashboard load.
    Falls back to `get_stock_data` when the snapshot carries no usable price.

    Every answer is remembered, the fallback included: a ticker whose snapshot
    never carries a price must not re-run that network call on every dashboard
    valuation refresh.
    """
    ticker = normalize_ticker(ticker)

    try:
        fast = market_data.get_fast_info(ticker)
        if fast is None:
            logger.warning(
                "Fast quote unavailable, falling back to full fetch; ticker=%s", ticker
            )
            return get_stock_data(ticker)

        current_price = _fast_float(fast.get("last_price"))
        prev_close = _fast_float(fast.get("previous_close"))
        if current_price <= 0:
            return get_stock_data(ticker)

        if prev_close > 0:
            day_change = current_price - prev_close
            day_change_pct = (day_change / prev_close) * 100
        else:
            day_change = 0.0
            day_change_pct = 0.0

        year_high = _fast_float(fast.get("year_high"))
        year_low = _fast_float(fast.get("year_low"))
        security_type = classify_security(ticker, None).value

        result = {
            "ticker": ticker,
            "name": ticker,
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "day_change": round(day_change, 2),
            "day_change_pct": round(day_change_pct, 2),
            "day_high": round(_fast_float(fast.get("day_high"), current_price), 2),
            "day_low": round(_fast_float(fast.get("day_low"), current_price), 2),
            "fifty_two_week_high": round(year_high, 2) if year_high > 0 else 0,
            "fifty_two_week_low": round(year_low, 2) if year_low > 0 else 0,
            # Fields unavailable from fast_info; callers should upgrade to get_stock_data
            # if they need these ratios.
            "fifty_day_average": None,
            "two_hundred_day_average": None,
            "volume": int(_fast_float(fast.get("last_volume"))),
            "average_volume": 0,
            "market_cap": int(_fast_float(fast.get("market_cap"))),
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
            "dividend_rate": None,
            "ex_dividend_date": None,
            "currency": str(fast.get("currency") or "USD"),
            "sector": "N/A",
            "quote_type": "ETF" if security_type == "ETF" else "EQUITY",
            "security_type": security_type,
            "error": None,
        }
        return result

    except Exception as exc:
        logger.warning(
            "Fast quote failed, falling back to full fetch; ticker=%s exception_type=%s",
            ticker,
            type(exc).__name__,
        )
        return get_stock_data(ticker)


# ── Search and validation ──────────────────────────────────────────────────────

def suggest_tickers(query: str, limit: int = 3) -> list[dict]:
    """Return likely ticker matches from Yahoo Finance search (used for autocomplete)."""
    query = _clean_suggestion_query(query)
    if not query:
        return []

    try:
        suggestions = []
        seen: set[str] = set()
        for item in market_data.search(query, limit=max(limit, 3)):
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
        # Fast quotes first: they are what the holdings table and hero cards
        # need, so warming them first is what shortens time-to-first-paint. The
        # phases are sequential, and `.info` is the slower of the two.
        get_portfolio_quotes(targets)
        # get_all_quotes warms both the quote cache and the `.info` cache (via
        # get_ticker_info), so analyst recs and holding intelligence benefit too
        # — all of which load in the dashboard's idle phase, after first paint.
        get_all_quotes(targets)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Cache warmup failed; exception_type=%s", type(exc).__name__)


# ── Historical price data ──────────────────────────────────────────────────────

@ttl_cache(
    ttl=_HISTORY_TTL,
    key=lambda ticker, period: (ticker.upper(), period),
    # An empty series means the fetch failed or the symbol has no history;
    # neither is worth pinning for the window.
    cache_when=bool,
)
def get_historical_prices(ticker: str, period: str = "1mo") -> list[dict]:
    """
    Return daily OHLCV data for a ticker.

    Accepted period strings: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y",
    "5y", "10y", "ytd", "max".  Returns [] on fetch failure.

    Bars where any OHLCV field is missing are silently dropped so callers always
    receive JSON-safe floats (Starlette serializes with allow_nan=False); the
    seam has already turned NaN and Inf into None by the time they arrive.
    """
    results = []
    for session in market_data.get_history(ticker, period=period):
        open_, high, low, close, volume = (
            session["open"], session["high"], session["low"],
            session["close"], session["volume"],
        )
        if None in (open_, high, low, close, volume):
            continue
        results.append({
            "date": session["date"],
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": int(volume),
        })
    return results


@ttl_cache(ttl=_HISTORY_TTL, key=lambda ticker, start, end: (ticker.upper(), start, end))
def get_daily_closes(ticker: str, start: str, end: str) -> dict[str, float]:
    """
    Return ``{"YYYY-MM-DD": close}`` for trading days in ``[start, end]``
    (both inclusive). ``start``/``end`` are ISO date strings.

    Cached on the exact window, like the other history fetchers. Daily DCA plans
    re-ask for the same span on every page load — their cadence is the trading
    calendar, so unlike weekly and monthly they can't tell whether a buy is due
    without it — and the span runs from the plan's start date, so it grows for
    the life of the plan.

    Used by the DCA engine to price historical buys on the exact days they would
    have executed. Missing or non-positive closes are dropped; returns ``{}``
    on an unparseable window so callers can degrade gracefully.
    """
    try:
        # ``end`` names the first day *not* included, so push it out a day.
        end_excl = (
            datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
    except ValueError as exc:
        logger.error("Error fetching daily closes; exception_type=%s", type(exc).__name__)
        return {}

    return {
        session["date"]: round(session["close"], 2)
        for session in market_data.get_history(ticker, start=start, end=end_excl)
        if session["close"] is not None and session["close"] > 0
    }
