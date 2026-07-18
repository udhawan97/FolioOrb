"""
Dividend payment calendar — WHEN your holdings pay you, month by month.

The income card answers "how much a year?"; this answers "which months?".
Cadence and paying months are read from each payer's real trailing ex-dates
(via the market-data seam); the dollar amounts come from the same forward
annual income the income card already shows. History times the payments, the
forward rate sizes them — so a freshly raised dividend projects at the new
rate, in the months the stock has actually been paying.

Honesty rules: the months are EX-DIVIDEND months (cash usually lands days to
weeks later — the payload says so via ``basis``); a payer whose cadence can't
be read from history is listed as ``unscheduled`` with its annual amount,
never spread across months we invented.

``build_income_calendar`` and ``payment_months`` are pure (history and today
injected — trivially unit-testable). Only ``fetch_dividend_ex_dates`` touches
the network, mirroring timing_signal's day-keyed cache + bounded fan-out.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Iterable

from app.services import market_data

# ~13 months of history: catches an annual payer plus scheduling drift, without
# reaching back to cadences the company may have abandoned.
_LOOKBACK_DAYS = 400
# ≥10 ex-dates in the window → monthly payer (12 minus holiday drift/slack).
_MONTHLY_MIN = 10

# (ticker, YYYY-MM-DD) → trailing ex-dates. Keyed by day, pruned like
# timing_signal's history cache so a long-running desktop process can't hoard
# one dead entry per ticker per day.
_EX_DATES_CACHE: dict[tuple[str, str], list[date]] = {}


def payment_months(ex_dates: Iterable[date], today: date) -> dict | None:
    """Cadence read from trailing ex-dates: payments per year + paying months.

    Returns ``{"per_year": int, "months": set[int]}`` or ``None`` when the
    window holds no history — future declarations and ancient history both
    count for nothing.
    """
    recent = sorted(d for d in ex_dates if 0 <= (today - d).days <= _LOOKBACK_DAYS)
    if not recent:
        return None
    count = len(recent)
    if count >= _MONTHLY_MIN:
        return {"per_year": 12, "months": set(range(1, 13))}
    if count >= 3:
        per_year = 4
    elif count == 2:
        per_year = 2
    else:
        per_year = 1
    # The last full cycle's months are the schedule; a special dividend in an
    # already-paying month collapses in the set rather than inventing a month.
    return {"per_year": per_year, "months": {d.month for d in recent[-per_year:]}}


def _month_slots(today: date) -> list[tuple[int, int]]:
    """Twelve (year, month) pairs starting with today's month."""
    base = today.year * 12 + today.month - 1
    return [((base + i) // 12, (base + i) % 12 + 1) for i in range(12)]


def build_income_calendar(
    payers: list[dict],
    history_by_ticker: dict[str, list[date]],
    today: date,
) -> dict:
    """Project the next 12 months of dividend income from payers + history.

    ``payers``: dicts carrying ``ticker`` and ``annual_income`` (the income
    card's payer rows). ``history_by_ticker``: trailing ex-dates per ticker.
    """
    slots = _month_slots(today)
    months = [
        {"month": f"{y:04d}-{m:02d}", "total": 0.0, "payers": []}
        for y, m in slots
    ]
    unscheduled: list[dict] = []

    for payer in payers:
        ticker = str(payer.get("ticker") or "").upper()
        annual = float(payer.get("annual_income") or 0.0)
        if not ticker or annual <= 0:
            continue
        cadence = payment_months(history_by_ticker.get(ticker) or [], today)
        if cadence is None:
            unscheduled.append({"ticker": ticker, "annual_income": round(annual, 2)})
            continue
        amount = round(annual / cadence["per_year"], 2)
        for slot, (_, month_no) in zip(months, slots):
            if month_no in cadence["months"]:
                slot["payers"].append({"ticker": ticker, "amount": amount})
                slot["total"] += amount

    scheduled_any = False
    for slot in months:
        slot["total"] = round(slot["total"], 2)
        slot["payers"].sort(key=lambda p: p["amount"], reverse=True)
        if slot["total"] > 0:
            scheduled_any = True
    unscheduled.sort(key=lambda u: u["annual_income"], reverse=True)

    return {
        "has_data": scheduled_any,
        "months": months,
        "unscheduled": unscheduled,
        "total_next_12m": round(sum(s["total"] for s in months), 2),
        # Months are ex-dividend months, not pay months — the UI must disclose.
        "basis": "ex_date",
    }


def _fetch_ex_dates(ticker: str) -> list[date]:
    """Trailing ex-dates for one ticker; empty on any provider hiccup.

    The market-data seam already absorbs provider errors and the vendor's
    pandas shape, so all that is left here is the lookback window.
    """
    cutoff_ordinal = date.today().toordinal() - _LOOKBACK_DAYS
    return [d for d in market_data.get_dividend_dates(ticker) if d.toordinal() >= cutoff_ordinal]


def fetch_dividend_ex_dates(tickers: Iterable[str]) -> dict[str, list[date]]:
    """Concurrent, de-duped, same-day cached ex-date fetch for the calendar."""
    symbols = sorted({str(t).upper() for t in tickers if t})
    if not symbols:
        return {}

    today = date.today().isoformat()
    for key in [k for k in _EX_DATES_CACHE if k[1] != today]:
        del _EX_DATES_CACHE[key]

    results: dict[str, list[date]] = {}
    missing: list[str] = []
    for symbol in symbols:
        cached = _EX_DATES_CACHE.get((symbol, today))
        if cached is not None:
            results[symbol] = list(cached)
        else:
            missing.append(symbol)

    if missing:
        with ThreadPoolExecutor(max_workers=min(10, len(missing))) as pool:
            futures = {pool.submit(_fetch_ex_dates, s): s for s in missing}
            for future in as_completed(futures):
                symbol = futures[future]
                dates = future.result()
                _EX_DATES_CACHE[(symbol, today)] = dates
                results[symbol] = list(dates)
    return results
