"""The one seam between FolioOrb and Yahoo Finance (yfinance).

Every read of vendor data goes through the module-level accessors here, so the
vendor is named in exactly one implementation. That is what makes this a seam:
``set_adapter()`` / ``use_adapter()`` swap the entire vendor surface without
editing a single caller, and tests inject ``FakeMarketData`` instead of
monkeypatching ``yfinance.Ticker`` through a different module path per test file.

Interface — nine accessors, keyed by ticker (or, for ``search``, by query):

    get_info                full Yahoo ``.info`` record       dict | None
    get_fast_info           cheap price snapshot              dict | None
    get_history             daily OHLCV bars, oldest first    list[dict]
    get_closes              usable closes from those bars     list[float]
    get_news                raw article payloads              list[dict]
    get_earnings_estimates  one row per quarter               list[dict]
    get_earnings_calendar   upcoming earnings dates           list[date]
    get_dividend_dates      trailing ex-dividend dates        list[date]
    get_fund_holdings       a fund's largest positions        list[dict]
    search                  symbol lookup for autocomplete    list[dict]

Contract — absence, never an exception:
    No accessor raises. A vendor exception, a missing yfinance package, an
    unknown symbol, and an empty vendor payload all read the same way: the empty
    value of the return type — ``None`` for the two record-shaped reads, ``[]``
    for the seven list-shaped ones. The record reads keep "the read failed"
    (``None``) distinct from "Yahoo had nothing to say" (``{}``), because an
    unavailable quote and a blank quote are different facts to a caller.

Contract — plain Python, never vendor types:
    DataFrames, ``FastInfo`` attribute bags, numpy scalars, and NaN all stay
    behind this seam. Numbers come back as ``float | None`` with NaN and Inf read
    as ``None``; dates come back as ``datetime.date`` or an ISO ``YYYY-MM-DD``
    string. Symbols are stripped and upper-cased before any adapter sees them.

Deliberately absent: caching. Each caller owns its own TTL policy, so this
module stays a pure read-through that a cache can be layered on top of.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date
from math import isfinite
from typing import Any, Iterator, Mapping, Protocol

try:  # The desktop build may ship without the vendor package.
    import yfinance as _yfinance
except ImportError:  # pragma: no cover - only reachable in a vendor-less build
    _yfinance = None

from app.services.log_safety import sanitize_for_log

logger = logging.getLogger(__name__)

# Vendor knobs that never vary by caller, kept here so no call site repeats them.
_SEARCH_TIMEOUT_SEC = 5
_DEFAULT_SEARCH_LIMIT = 8
_DEFAULT_EARNINGS_LIMIT = 8

# The `fast_info` fields any caller in the app needs. Reading an attribute is a
# lazy network call, so the set is deliberately narrow: widening it is an edit
# here, which is the seam doing its job.
_FAST_INFO_FIELDS = (
    "day_high",
    "day_low",
    "last_price",
    "last_volume",
    "market_cap",
    "previous_close",
)


# ── Shaping helpers ───────────────────────────────────────────────────────────

def _symbol(ticker: str) -> str:
    """Adapters are guaranteed a stripped, upper-cased symbol."""
    return (ticker or "").strip().upper()


def _number(value: Any) -> float | None:
    """Vendor scalars are numpy floats, NaN, None, or junk; this yields float | None."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _text(value: Any) -> str | None:
    """Vendor text cells arrive as NaN when Yahoo has nothing; only real text survives."""
    if value is None or (isinstance(value, float) and not isfinite(value)):
        return None
    text = str(value).strip()
    return text or None


def _raw(row: Any, column: str) -> Any:
    """One cell of a vendor row, tolerating rows that lack the column entirely."""
    try:
        return row.get(column)
    except Exception:  # pylint: disable=broad-except
        return None


def _cell(row: Any, column: str) -> float | None:
    """One numeric cell of a vendor row, as float | None."""
    return _number(_raw(row, column))


def _attr(obj: Any, name: str) -> Any:
    """Read a lazy vendor attribute; any single one of them can raise."""
    try:
        return getattr(obj, name, None)
    except Exception:  # pylint: disable=broad-except
        return None


def _as_date(value: Any) -> date | None:
    """A pandas Timestamp, a datetime, or a date — all read back as a plain date."""
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    try:
        converted = value.date()
    except (AttributeError, TypeError, ValueError):
        return None
    return converted if isinstance(converted, date) else None


def _iso_day(value: Any) -> str | None:
    """A row's index stamp as ``YYYY-MM-DD``, or None when it carries no usable day."""
    day = _as_date(value)
    return day.isoformat() if day is not None else None


def _rows_of(frame: Any) -> list[tuple[Any, Any]]:
    """(index, row) pairs of a vendor frame; an absent or empty frame yields none."""
    if frame is None:
        return []
    try:
        if bool(getattr(frame, "empty", False)):
            return []
        return list(frame.iterrows())
    except Exception:  # pylint: disable=broad-except
        return []


def _keyed_by_symbol(mapping: Mapping[str, Any] | None) -> dict[str, Any]:
    """Preloaded tables are keyed the way adapters are called: stripped, upper-cased."""
    return {_symbol(key): value for key, value in (mapping or {}).items()}


def _log_unavailable(surface: str, key: str, exc: BaseException) -> None:
    """One line per failed vendor read — never the message, which can echo input."""
    logger.debug(
        "market_data: %s unavailable; key=%s exception_type=%s",
        surface,
        sanitize_for_log(key),
        type(exc).__name__,
    )


# ── The interface an adapter must satisfy ─────────────────────────────────────

class MarketDataAdapter(Protocol):
    """Everything an implementation must provide to stand in for the vendor.

    Implementations receive normalised symbols, return plain Python, and never
    raise — the module-level accessors add nothing beyond delegation.
    """

    def get_info(self, symbol: str) -> dict | None:
        ...

    def get_fast_info(self, symbol: str) -> dict | None:
        ...

    def get_history(
        self,
        symbol: str,
        *,
        period: str | None = None,
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = True,
    ) -> list[dict]:
        ...

    def get_news(self, symbol: str) -> list[dict]:
        ...

    def get_earnings_estimates(
        self, symbol: str, *, limit: int = _DEFAULT_EARNINGS_LIMIT
    ) -> list[dict]:
        ...

    def get_earnings_calendar(self, symbol: str) -> list[date]:
        ...

    def get_dividend_dates(self, symbol: str) -> list[date]:
        ...

    def get_fund_holdings(self, symbol: str) -> list[dict]:
        ...

    def search(self, query: str, *, limit: int = _DEFAULT_SEARCH_LIMIT) -> list[dict]:
        ...


# ── Production implementation ─────────────────────────────────────────────────

class YFinanceAdapter:
    """yfinance in, plain Python out — the only place the vendor is named.

    Every vendor call is wrapped exactly once here, which is what lets the rest
    of the app stop guarding against assorted vendor exceptions, empty frames,
    and NaN sentinels. ``vendor`` exists so the normalisation itself is testable
    without a network or a monkeypatched global.
    """

    def __init__(self, vendor: Any = None) -> None:
        self._vendor = vendor if vendor is not None else _yfinance

    def _ticker(self, symbol: str) -> Any:
        """The vendor handle for a symbol, or None when it cannot be built."""
        if self._vendor is None:
            return None
        try:
            return self._vendor.Ticker(symbol)
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("ticker", symbol, exc)
            return None

    def get_info(self, symbol: str) -> dict | None:
        stock = self._ticker(symbol)
        if stock is None:
            return None
        try:
            return dict(stock.info or {})
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("info", symbol, exc)
            return None

    def get_fast_info(self, symbol: str) -> dict | None:
        stock = self._ticker(symbol)
        if stock is None:
            return None
        try:
            fast = stock.fast_info
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("fast_info", symbol, exc)
            return None
        if fast is None:
            return None
        snapshot: dict[str, Any] = {
            field: _number(_attr(fast, field)) for field in _FAST_INFO_FIELDS
        }
        # Older yfinance spelled the 52-week extremes differently; one name wins.
        snapshot["year_high"] = _number(
            _attr(fast, "year_high") or _attr(fast, "fifty_two_week_high")
        )
        snapshot["year_low"] = _number(
            _attr(fast, "year_low") or _attr(fast, "fifty_two_week_low")
        )
        snapshot["currency"] = _text(_attr(fast, "currency"))
        return snapshot

    def get_history(
        self,
        symbol: str,
        *,
        period: str | None = None,
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = True,
    ) -> list[dict]:
        stock = self._ticker(symbol)
        if stock is None:
            return []
        # Omit period entirely when a window is given; yfinance treats the two as
        # alternatives, and `end` is exclusive of the day it names.
        options: dict[str, Any] = {"interval": interval, "auto_adjust": auto_adjust}
        if period is not None:
            options["period"] = period
        if start is not None:
            options["start"] = start
        if end is not None:
            options["end"] = end
        try:
            frame = stock.history(**options)
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("history", symbol, exc)
            return []
        bars: list[dict] = []
        for stamp, row in _rows_of(frame):
            day = _iso_day(stamp)
            if day is None:
                continue
            bars.append({
                "date": day,
                "open": _cell(row, "Open"),
                "high": _cell(row, "High"),
                "low": _cell(row, "Low"),
                "close": _cell(row, "Close"),
                "volume": _cell(row, "Volume"),
            })
        return bars

    def get_news(self, symbol: str) -> list[dict]:
        stock = self._ticker(symbol)
        if stock is None:
            return []
        try:
            return list(stock.news or [])
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("news", symbol, exc)
            return []

    def get_earnings_estimates(
        self, symbol: str, *, limit: int = _DEFAULT_EARNINGS_LIMIT
    ) -> list[dict]:
        stock = self._ticker(symbol)
        if stock is None:
            return []
        try:
            table = stock.get_earnings_dates(limit=limit)
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("earnings_estimates", symbol, exc)
            return []
        quarters: list[dict] = []
        for stamp, row in _rows_of(table):
            day = _as_date(stamp)
            if day is None:
                continue
            quarters.append({
                "date": day,
                "eps_estimate": _cell(row, "EPS Estimate"),
                "surprise_pct": _cell(row, "Surprise(%)"),
            })
        return quarters

    def get_earnings_calendar(self, symbol: str) -> list[date]:
        stock = self._ticker(symbol)
        if stock is None:
            return []
        try:
            calendar = stock.calendar
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("earnings_calendar", symbol, exc)
            return []
        return _calendar_dates(calendar)

    def get_dividend_dates(self, symbol: str) -> list[date]:
        stock = self._ticker(symbol)
        if stock is None:
            return []
        try:
            series = stock.dividends
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("dividend_dates", symbol, exc)
            return []
        if series is None or getattr(series, "empty", True):
            return []
        try:
            return sorted(stamp.date() for stamp in series.index)
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("dividend_dates", symbol, exc)
            return []

    def get_fund_holdings(self, symbol: str) -> list[dict]:
        stock = self._ticker(symbol)
        if stock is None:
            return []
        try:
            frame = stock.funds_data.top_holdings
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("fund_holdings", symbol, exc)
            return []
        holdings: list[dict] = []
        for holding_symbol, row in _rows_of(frame):
            holdings.append({
                "symbol": str(holding_symbol),
                "name": _text(_raw(row, "Name")) or str(holding_symbol),
                # Yahoo publishes fractions (0.072); the app speaks percentage points.
                "weight": (_cell(row, "Holding Percent") or 0.0) * 100,
            })
        return holdings

    def search(self, query: str, *, limit: int = _DEFAULT_SEARCH_LIMIT) -> list[dict]:
        if self._vendor is None:
            return []
        try:
            found = self._vendor.Search(
                query,
                max_results=limit,
                news_count=0,
                lists_count=0,
                include_research=False,
                raise_errors=False,
                timeout=_SEARCH_TIMEOUT_SEC,
            )
            return list(found.quotes or [])
        except Exception as exc:  # pylint: disable=broad-except
            _log_unavailable("search", query, exc)
            return []


def _calendar_dates(calendar: Any) -> list[date]:
    """Earnings dates out of a vendor calendar, which is a dict or an older frame."""
    if calendar is None:
        return []
    try:
        if hasattr(calendar, "loc"):
            raw = calendar.loc["Earnings Date"]
        elif isinstance(calendar, dict):
            raw = calendar.get("Earnings Date")
        else:
            return []
    except Exception:  # pylint: disable=broad-except
        return []
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)) or not hasattr(raw, "__iter__"):
        candidates = [raw]
    else:
        candidates = list(raw)
    return [day for day in (_as_date(value) for value in candidates) if day is not None]


# ── Test implementation ───────────────────────────────────────────────────────

class FakeMarketData:
    """Preloaded plain dicts in, the same contract out — the adapter tests inject.

    Only the data a test cares about needs preloading; anything else reads as
    unavailable. Bars and rows may be partial (``{"close": 101.0}`` is a valid
    bar), because every consumer already treats missing fields as absent.

    ``calls`` records ``(accessor, key)`` in order, so a test can prove a read
    happened exactly once — or never.
    """

    def __init__(  # pylint: disable=redefined-outer-name
        self,
        *,
        info: Mapping[str, dict] | None = None,
        fast_info: Mapping[str, dict] | None = None,
        history: Mapping[str, list[dict]] | None = None,
        news: Mapping[str, list[dict]] | None = None,
        earnings_estimates: Mapping[str, list[dict]] | None = None,
        earnings_calendar: Mapping[str, list[date]] | None = None,
        dividend_dates: Mapping[str, list[date]] | None = None,
        fund_holdings: Mapping[str, list[dict]] | None = None,
        search: Mapping[str, list[dict]] | None = None,
    ) -> None:
        # One table per accessor, so adding an accessor never grows the fake's state.
        self._tables: dict[str, dict[str, Any]] = {
            "get_info": _keyed_by_symbol(info),
            "get_fast_info": _keyed_by_symbol(fast_info),
            "get_history": _keyed_by_symbol(history),
            "get_news": _keyed_by_symbol(news),
            "get_earnings_estimates": _keyed_by_symbol(earnings_estimates),
            "get_earnings_calendar": _keyed_by_symbol(earnings_calendar),
            "get_dividend_dates": _keyed_by_symbol(dividend_dates),
            "get_fund_holdings": _keyed_by_symbol(fund_holdings),
            # Queries are free text, so they match case- and space-insensitively.
            "search": _keyed_by_symbol(search),
        }
        self.calls: list[tuple[str, str]] = []

    def _lookup(self, accessor: str, key: str) -> Any:
        self.calls.append((accessor, key))
        return self._tables[accessor].get(key)

    def get_info(self, symbol: str) -> dict | None:
        found = self._lookup("get_info", symbol)
        return dict(found) if found is not None else None

    def get_fast_info(self, symbol: str) -> dict | None:
        found = self._lookup("get_fast_info", symbol)
        return dict(found) if found is not None else None

    def get_history(  # pylint: disable=unused-argument
        self,
        symbol: str,
        *,
        period: str | None = None,
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
        auto_adjust: bool = True,
    ) -> list[dict]:
        found = self._lookup("get_history", symbol)
        return [dict(row) for row in (found or [])]

    def get_news(self, symbol: str) -> list[dict]:
        found = self._lookup("get_news", symbol)
        return [dict(item) for item in (found or [])]

    def get_earnings_estimates(  # pylint: disable=unused-argument
        self, symbol: str, *, limit: int = _DEFAULT_EARNINGS_LIMIT
    ) -> list[dict]:
        found = self._lookup("get_earnings_estimates", symbol)
        return [dict(row) for row in (found or [])]

    def get_earnings_calendar(self, symbol: str) -> list[date]:
        found = self._lookup("get_earnings_calendar", symbol)
        return list(found or [])

    def get_dividend_dates(self, symbol: str) -> list[date]:
        found = self._lookup("get_dividend_dates", symbol)
        return list(found or [])

    def get_fund_holdings(self, symbol: str) -> list[dict]:
        found = self._lookup("get_fund_holdings", symbol)
        return [dict(row) for row in (found or [])]

    def search(  # pylint: disable=unused-argument
        self, query: str, *, limit: int = _DEFAULT_SEARCH_LIMIT
    ) -> list[dict]:
        found = self._lookup("search", _symbol(query))
        return [dict(row) for row in (found or [])]


# ── The seam ──────────────────────────────────────────────────────────────────

_DEFAULT_ADAPTER: MarketDataAdapter = YFinanceAdapter()
_ACTIVE_ADAPTER: MarketDataAdapter = _DEFAULT_ADAPTER


def get_adapter() -> MarketDataAdapter:
    """The adapter every read currently goes through."""
    return _ACTIVE_ADAPTER


def set_adapter(adapter: MarketDataAdapter | None) -> MarketDataAdapter:
    """Install `adapter` (None restores yfinance) and return the one replaced."""
    global _ACTIVE_ADAPTER  # pylint: disable=global-statement
    previous = _ACTIVE_ADAPTER
    _ACTIVE_ADAPTER = adapter if adapter is not None else _DEFAULT_ADAPTER
    return previous


@contextmanager
def use_adapter(adapter: MarketDataAdapter | None) -> Iterator[MarketDataAdapter]:
    """Swap the adapter for the duration of a block, then restore the previous one."""
    previous = set_adapter(adapter)
    try:
        yield get_adapter()
    finally:
        set_adapter(previous)


# ── Accessors ─────────────────────────────────────────────────────────────────

def get_info(ticker: str) -> dict | None:
    """Yahoo's full record for a symbol; None when the read was unavailable."""
    return _ACTIVE_ADAPTER.get_info(_symbol(ticker))


def get_fast_info(ticker: str) -> dict | None:
    """Cheap price snapshot: last_price, previous_close, day/year extremes, currency.

    Far quicker than `get_info` and enough to value a position. None when the
    read was unavailable; individual fields are ``float | None``.
    """
    return _ACTIVE_ADAPTER.get_fast_info(_symbol(ticker))


def get_history(
    ticker: str,
    *,
    period: str | None = None,
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = True,
) -> list[dict]:
    """Daily bars, oldest first: ``{date, open, high, low, close, volume}``.

    ``date`` is an ISO ``YYYY-MM-DD`` string; every other field is
    ``float | None``. Pass either ``period`` or a ``start``/``end`` window —
    ``end`` names the first day *not* included, as yfinance defines it.
    """
    return _ACTIVE_ADAPTER.get_history(
        _symbol(ticker),
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
    )


def get_closes(
    ticker: str,
    *,
    period: str | None = None,
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
    auto_adjust: bool = True,
) -> list[float]:
    """Usable closes from `get_history`, oldest first.

    "Usable" means finite and positive: a NaN or zero close is missing data, not
    a price, and every caller in the app was filtering it out by hand.
    """
    closes: list[float] = []
    for row in get_history(
        ticker,
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
    ):
        close = _number(row.get("close"))
        if close is not None and close > 0:
            closes.append(close)
    return closes


def get_news(ticker: str) -> list[dict]:
    """Raw article payloads for a symbol, in Yahoo's order."""
    return _ACTIVE_ADAPTER.get_news(_symbol(ticker))


def get_earnings_estimates(
    ticker: str, *, limit: int = _DEFAULT_EARNINGS_LIMIT
) -> list[dict]:
    """One row per quarter, newest first: ``{date, eps_estimate, surprise_pct}``.

    ``date`` is a plain ``date``; the two numbers are ``float | None`` — a quarter
    that has not reported yet carries no surprise.
    """
    return _ACTIVE_ADAPTER.get_earnings_estimates(_symbol(ticker), limit=limit)


def get_earnings_calendar(ticker: str) -> list[date]:
    """Upcoming earnings dates for a symbol, as plain dates."""
    return _ACTIVE_ADAPTER.get_earnings_calendar(_symbol(ticker))


def get_dividend_dates(ticker: str) -> list[date]:
    """Trailing ex-dividend dates for a symbol, oldest first, as plain dates.

    The vendor hands back a pandas Series indexed by timestamp; that shape is
    normalised away here so callers never import pandas to read a dividend.
    """
    return _ACTIVE_ADAPTER.get_dividend_dates(_symbol(ticker))


def get_fund_holdings(ticker: str) -> list[dict]:
    """A fund's largest positions: ``{symbol, name, weight}``, weight in points.

    Yahoo publishes only the top ten, so this is a floor on what a fund holds.
    """
    return _ACTIVE_ADAPTER.get_fund_holdings(_symbol(ticker))


def search(query: str, *, limit: int = _DEFAULT_SEARCH_LIMIT) -> list[dict]:
    """Raw symbol matches for a free-text query; the caller decides what is usable."""
    return _ACTIVE_ADAPTER.search(query, limit=limit)
