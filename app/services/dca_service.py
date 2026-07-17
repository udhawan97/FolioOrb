"""Dollar-cost-averaging (DCA) plan engine — pure, DB-free, network-free.

Mirrors a brokerage auto-invest locally: given a fixed dollar amount, a cadence,
and real historical closing prices, it computes the individual buys (a
"simulated bucket") the user reviews and can then apply to a real holding.

Every function here is pure so it unit-tests without a database or network.
Database orchestration and price fetching live in ``app/services/dca_ledger.py``.
"""
from __future__ import annotations

from bisect import bisect_left
from calendar import monthrange
from datetime import date, timedelta

# Supported cadences. "daily" books one buy per *trading* day; "weekly" and
# "monthly" step from the start date and execute on the first trading day on or
# after each step (mirroring how a broker fills on the next market open).
FREQUENCIES = ("daily", "weekly", "monthly")


def add_months(d: date, n: int) -> date:
    """Return ``d`` shifted by ``n`` months, clamping the day to the target
    month's length (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def scheduled_dates(
    frequency: str, start: date, today: date, trading_days: list[date]
) -> list[date]:
    """Return the list of *intended* contribution dates from ``start``..``today``.

    ``trading_days`` is the sorted list of market days available in range; it is
    used directly as the schedule for "daily" and ignored for weekly/monthly
    stepping (those step by calendar date and snap to a trading day later).
    """
    if start > today:
        return []
    if frequency == "daily":
        return [d for d in trading_days if start <= d <= today]
    dates: list[date] = []
    if frequency == "weekly":
        step = timedelta(days=7)
        d = start
        while d <= today:
            dates.append(d)
            d += step
    elif frequency == "monthly":
        k = 0
        d = start
        while d <= today:
            dates.append(d)
            k += 1
            d = add_months(start, k)
    else:
        raise ValueError(f"unknown frequency: {frequency}")
    return dates


def next_scheduled_date(frequency: str, start: date, today: date) -> date | None:
    """Return the next intended buy date strictly after ``today`` (for display).

    For "daily" this is simply tomorrow; the caller is responsible for snapping to
    an actual trading day when it fills.
    """
    if frequency == "daily":
        return today + timedelta(days=1)
    if frequency == "weekly":
        d = start
        while d <= today:
            d += timedelta(days=7)
        return d
    if frequency == "monthly":
        k = 0
        d = start
        while d <= today:
            k += 1
            d = add_months(start, k)
        return d
    raise ValueError(f"unknown frequency: {frequency}")


def _first_trading_on_or_after(
    target: date, trading_days: list[date], closes_by_date: dict[date, float]
) -> tuple[date, float] | None:
    """Return ``(exec_date, close)`` for the first trading day >= ``target``."""
    i = bisect_left(trading_days, target)
    if i >= len(trading_days):
        return None
    d = trading_days[i]
    return d, closes_by_date[d]


def plan_contributions(
    frequency: str,
    amount: float,
    start: date,
    today: date,
    closes: list[tuple[date, float]],
) -> list[dict]:
    """Compute every buy a plan should have booked between ``start`` and ``today``.

    ``closes`` is the sorted list of ``(trading_day, close_price)`` covering at
    least ``[start, today]``. Returns one dict per intended buy::

        {"scheduled_date", "exec_date", "price", "shares", "amount"}

    ``scheduled_date`` is the cadence's intended date; ``exec_date`` is the
    trading day actually priced. Intended dates with no trading day on or after
    them (e.g. beyond the available history) are skipped.
    """
    if amount <= 0 or start > today or not closes:
        return []
    trading_days = [d for d, _ in closes]
    closes_by_date = dict(closes)
    out: list[dict] = []
    for sched in scheduled_dates(frequency, start, today, trading_days):
        hit = _first_trading_on_or_after(sched, trading_days, closes_by_date)
        if hit is None:
            continue
        exec_date, price = hit
        if exec_date > today or price <= 0:
            continue
        out.append(
            {
                "scheduled_date": sched,
                "exec_date": exec_date,
                "price": price,
                "shares": amount / price,
                "amount": amount,
            }
        )
    return out


def apply_to_holding(
    old_shares: float, old_avg: float, buy_shares: float, buy_amount: float
) -> tuple[float, float]:
    """Return ``(new_shares, new_avg_cost)`` after adding a fixed-dollar buy.

    Because each buy invests exactly ``buy_amount`` dollars, the cost basis grows
    by that amount and the new average is basis / shares.
    """
    new_shares = old_shares + buy_shares
    if new_shares <= 0:
        return 0.0, 0.0
    old_basis = old_shares * (old_avg or 0.0)
    return new_shares, (old_basis + buy_amount) / new_shares


def undo_from_holding(
    old_shares: float,
    old_avg: float,
    buy_shares: float,
    buy_amount: float,
    eps: float = 1e-9,
) -> tuple[float, float]:
    """Return ``(new_shares, new_avg_cost)`` after reversing a previously applied
    buy — the exact inverse of :func:`apply_to_holding`.

    The reversal is arithmetic on the cost basis, so it stays correct even if
    other buys were applied to the same holding in between.
    """
    new_shares = old_shares - buy_shares
    if new_shares <= eps:
        return 0.0, 0.0
    old_basis = old_shares * (old_avg or 0.0)
    new_basis = old_basis - buy_amount
    if new_basis < 0:
        new_basis = 0.0
    return new_shares, new_basis / new_shares
