"""Single owner of the question "is the US market open right now?".

That question used to be answered twice: `stock_service` computed it privately
to pick its cache TTLs, and the stocks router recomputed the same weekday and
9:30–16:00 comparison inline to render the status badge.  Two answers to one
question drift — a holiday calendar added to one would have left the other
saying OPEN on Thanksgiving while quotes cached as if closed.

The interface is two names.  `is_open()` is the predicate every TTL selector
wants; `session_status()` is the full badge payload, which additionally
absorbs the eastern-time formatting and the next-open prose.  The timezone,
the session bounds, and the weekday rule stay behind both.

Known ceiling: no holiday calendar, so half-days and market holidays read as
open.  Fixing that is now a one-function edit rather than a two-file sweep,
which is the whole point of the move.
"""
from __future__ import annotations

from datetime import datetime

import pytz

EASTERN = pytz.timezone("America/New_York")

_OPEN_HOUR, _OPEN_MINUTE = 9, 30
_CLOSE_HOUR, _CLOSE_MINUTE = 16, 0


def _session_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return today's (open, close) instants in the same tz as `now`."""
    return (
        now.replace(hour=_OPEN_HOUR, minute=_OPEN_MINUTE, second=0, microsecond=0),
        now.replace(hour=_CLOSE_HOUR, minute=_CLOSE_MINUTE, second=0, microsecond=0),
    )


def is_open(now: datetime | None = None) -> bool:
    """Best-effort US market-hours check (no holiday calendar).

    `now` is injectable so callers and tests can ask about a specific instant;
    it defaults to the current Eastern time.
    """
    now = now or datetime.now(EASTERN)
    if now.weekday() >= 5:  # Saturday / Sunday
        return False
    open_t, close_t = _session_bounds(now)
    return open_t <= now <= close_t


def next_open_label(now: datetime | None = None) -> str | None:
    """Human phrasing for the next bell, or None while the market is open."""
    now = now or datetime.now(EASTERN)
    if is_open(now):
        return None
    open_t, _ = _session_bounds(now)
    if now.weekday() < 5 and now < open_t:
        return "9:30 AM ET today"        # weekday, before the bell
    if now.weekday() >= 4:
        return "Mon 9:30 AM ET"          # Fri after close, or the weekend
    return "9:30 AM ET tomorrow"         # Mon–Thu after close


def session_status(now: datetime | None = None) -> dict:
    """The market-status payload: open flag, label, local time, next bell."""
    now = now or datetime.now(EASTERN)
    open_now = is_open(now)
    return {
        "is_open": open_now,
        "status": "OPEN" if open_now else "CLOSED",
        "eastern_time": now.strftime("%I:%M %p ET"),
        "next_open": next_open_label(now),
    }
