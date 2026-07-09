"""
Earnings radar — surface upcoming earnings dates for a set of tickers.

Reuses ``event_calendar``'s date fetching/parsing and ``stock_service``'s
cached yfinance info. Each ticker's next earnings date is cached as an ISO
string (or None) so the days-until countdown recomputes correctly on every
read — a date cached yesterday still reports the right "in N days" today.

Fully useful without any AI dependency; this is deterministic on-device data.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from app.services.event_calendar import fetch_next_earnings
from app.services.log_safety import sanitize_for_log
from app.services.security_type import SecurityType, classify_security
from app.services.stock_service import (
    get_ticker_info,
    normalize_ticker,
    ticker_shape_is_safe,
)

logger = logging.getLogger(__name__)

_MAX_WORKERS = 8
_FETCH_TIMEOUT = 15.0             # seconds for the concurrent fan-out
_RADAR_TTL = 6 * 60 * 60         # 6 h — earnings dates move quarterly, not intraday
_DEFAULT_WINDOW_DAYS = 30

# symbol → (expiry_monotonic, iso_date_str | None). We cache the *date*, not the
# days-until, so an entry stays correct as the calendar advances.
_RADAR_CACHE: dict[str, tuple[float, str | None]] = {}


def _label(days_until: int) -> str:
    """Human-readable countdown for a non-negative day delta."""
    if days_until == 0:
        return "Today"
    if days_until == 1:
        return "Tomorrow"
    return f"In {days_until} days"


def _resolve_earnings_iso(symbol: str) -> str | None:
    """Next earnings date (ISO str) for one already-normalized symbol, or None.

    Cached for ``_RADAR_TTL``. Non-stocks (ETFs/funds/cash/crypto) and tickers
    with no known date cache as None, so a flaky or irrelevant ticker isn't
    re-classified or re-scraped on every call.
    """
    now = time.monotonic()
    cached = _RADAR_CACHE.get(symbol)
    if cached and cached[0] > now:
        return cached[1]

    iso: str | None = None
    try:
        info = get_ticker_info(symbol)
        if classify_security(symbol, info) == SecurityType.STOCK:
            earnings = fetch_next_earnings(symbol)
            if earnings is not None:
                iso = earnings.isoformat()
    except Exception as exc:  # pylint: disable=broad-except
        # One bad ticker must never break the fan-out. Cache None below so it
        # isn't retried on every call until the TTL lapses.
        logger.debug(
            "earnings_radar: resolve failed; ticker=%s exception_type=%s",
            sanitize_for_log(symbol), type(exc).__name__,
        )
    _RADAR_CACHE[symbol] = (now + _RADAR_TTL, iso)
    return iso


def get_earnings_events(
    tickers: list[str], window_days: int = _DEFAULT_WINDOW_DAYS
) -> list[dict]:
    """Upcoming-earnings events within ``window_days``, soonest first.

    Each event is ``{ticker, date (ISO), days_until, label}``. A ticker is
    omitted when it is not a stock, has no known earnings date, or its next
    date falls outside ``[0, window_days]`` — the lower bound intentionally
    drops the *past* dates that yfinance's ``mostRecentQuarter`` fallback can
    return. One bad ticker never blocks or crashes the others.
    """
    seen: set[str] = set()
    symbols: list[str] = []
    for raw in tickers:
        if not ticker_shape_is_safe(raw):
            continue
        symbol = normalize_ticker(raw)
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    if not symbols:
        return []

    resolved: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(symbols))) as pool:
        futures = {pool.submit(_resolve_earnings_iso, s): s for s in symbols}
        try:
            for future in as_completed(futures, timeout=_FETCH_TIMEOUT):
                symbol = futures[future]
                try:
                    resolved[symbol] = future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug(
                        "earnings_radar: future exception; ticker=%s exception_type=%s",
                        sanitize_for_log(symbol), type(exc).__name__,
                    )
                    resolved[symbol] = None
        except TimeoutError:
            logger.warning(
                "earnings_radar: fan-out timed out after %ss; %d/%d tickers completed",
                _FETCH_TIMEOUT, len(resolved), len(symbols),
            )

    today = date.today()
    events: list[dict] = []
    for symbol in symbols:
        iso = resolved.get(symbol)
        if not iso:
            continue
        try:
            earnings_date = date.fromisoformat(iso)
        except ValueError:
            continue
        days_until = (earnings_date - today).days
        if days_until < 0 or days_until > window_days:
            continue
        events.append({
            "ticker": symbol,
            "date": iso,
            "days_until": days_until,
            "label": _label(days_until),
        })

    events.sort(key=lambda event: (event["days_until"], event["ticker"]))
    return events
