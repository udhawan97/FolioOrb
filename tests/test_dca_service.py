"""Unit tests for the pure DCA engine (no DB, no network).

Covers cadence scheduling (daily/weekly/monthly), month-end clamping,
weekend/holiday snapping to the next trading day, backfill computation, and
the apply/undo cost-basis arithmetic being exact inverses.
"""
from datetime import date

import pytest

from app.services import dca_service


# ── add_months ────────────────────────────────────────────────────────────────

def test_add_months_simple():
    assert dca_service.add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)


def test_add_months_clamps_to_month_end():
    # Jan 31 + 1 month lands on Feb 28 (2026 is not a leap year)
    assert dca_service.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_add_months_leap_year():
    assert dca_service.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_add_months_year_rollover():
    assert dca_service.add_months(date(2025, 11, 30), 3) == date(2026, 2, 28)


# ── scheduled_dates ───────────────────────────────────────────────────────────

WEEK = [date(2026, 6, d) for d in (1, 2, 3, 4, 5)]  # Mon–Fri


def test_daily_schedule_is_trading_days():
    got = dca_service.scheduled_dates("daily", date(2026, 6, 2), date(2026, 6, 4), WEEK)
    assert got == [date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 4)]


def test_weekly_schedule_steps_seven_days():
    got = dca_service.scheduled_dates("weekly", date(2026, 6, 1), date(2026, 6, 20), [])
    assert got == [date(2026, 6, 1), date(2026, 6, 8), date(2026, 6, 15)]


def test_monthly_schedule_steps_from_start():
    got = dca_service.scheduled_dates("monthly", date(2026, 1, 31), date(2026, 4, 15), [])
    assert got == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]


def test_start_after_today_yields_nothing():
    assert dca_service.scheduled_dates("weekly", date(2027, 1, 1), date(2026, 6, 1), []) == []


def test_unknown_frequency_raises():
    with pytest.raises(ValueError):
        dca_service.scheduled_dates("hourly", date(2026, 1, 1), date(2026, 2, 1), [])


# ── next_scheduled_date ───────────────────────────────────────────────────────

def test_next_date_daily_is_tomorrow():
    assert dca_service.next_scheduled_date(
        "daily", date(2026, 1, 1), date(2026, 6, 10)
    ) == date(2026, 6, 11)


def test_next_date_weekly_lands_after_today():
    nxt = dca_service.next_scheduled_date("weekly", date(2026, 6, 1), date(2026, 6, 10))
    assert nxt == date(2026, 6, 15)


def test_next_date_monthly_lands_after_today():
    nxt = dca_service.next_scheduled_date("monthly", date(2026, 1, 31), date(2026, 3, 31))
    assert nxt == date(2026, 4, 30)


# ── plan_contributions ────────────────────────────────────────────────────────

# Trading week around a weekend: Fri Jun 5, then Mon Jun 8.
CLOSES = [
    (date(2026, 6, 4), 100.0),   # Thu
    (date(2026, 6, 5), 102.0),   # Fri
    (date(2026, 6, 8), 104.0),   # Mon
    (date(2026, 6, 9), 98.0),    # Tue
]


def test_daily_backfill_buys_every_trading_day():
    out = dca_service.plan_contributions(
        "daily", 50.0, date(2026, 6, 4), date(2026, 6, 9), CLOSES
    )
    assert [c["exec_date"] for c in out] == [d for d, _ in CLOSES]
    assert out[0]["shares"] == pytest.approx(50.0 / 100.0)
    assert all(c["amount"] == 50.0 for c in out)


def test_weekend_scheduled_buy_snaps_to_next_trading_day():
    # Weekly plan starting Saturday Jun 6 → executes Monday Jun 8 at Monday's close.
    out = dca_service.plan_contributions(
        "weekly", 50.0, date(2026, 6, 6), date(2026, 6, 9), CLOSES
    )
    assert len(out) == 1
    assert out[0]["scheduled_date"] == date(2026, 6, 6)
    assert out[0]["exec_date"] == date(2026, 6, 8)
    assert out[0]["price"] == 104.0


def test_scheduled_date_beyond_history_is_skipped():
    # Second weekly buy (Jun 11) has no trading day on/after it in CLOSES → skipped.
    out = dca_service.plan_contributions(
        "weekly", 50.0, date(2026, 6, 4), date(2026, 6, 12), CLOSES
    )
    assert [c["scheduled_date"] for c in out] == [date(2026, 6, 4)]


def test_zero_or_negative_amount_yields_nothing():
    assert not dca_service.plan_contributions(
        "daily", 0.0, date(2026, 6, 4), date(2026, 6, 9), CLOSES
    )


def test_empty_closes_yields_nothing():
    assert not dca_service.plan_contributions(
        "daily", 50.0, date(2026, 6, 4), date(2026, 6, 9), []
    )


# ── apply / undo cost-basis math ─────────────────────────────────────────────

def test_apply_updates_shares_and_average():
    # 10 sh @ $100 basis $1000; buy $50 worth at $104 → 0.480769 sh.
    new_shares, new_avg = dca_service.apply_to_holding(10.0, 100.0, 50.0 / 104.0, 50.0)
    assert new_shares == pytest.approx(10.480769, abs=1e-6)
    assert new_avg == pytest.approx(1050.0 / new_shares)


def test_apply_to_empty_holding_sets_price_as_average():
    new_shares, new_avg = dca_service.apply_to_holding(0.0, 0.0, 0.5, 50.0)
    assert new_shares == 0.5
    assert new_avg == pytest.approx(100.0)


def test_undo_is_exact_inverse_of_apply():
    shares, avg = 10.0, 100.0
    buy_shares, buy_amount = 50.0 / 104.0, 50.0
    s2, a2 = dca_service.apply_to_holding(shares, avg, buy_shares, buy_amount)
    s3, a3 = dca_service.undo_from_holding(s2, a2, buy_shares, buy_amount)
    assert s3 == pytest.approx(shares)
    assert a3 == pytest.approx(avg)


def test_undo_survives_interleaved_buys():
    # Apply buy A, then buy B, then undo A — B's contribution must remain intact.
    s, a = dca_service.apply_to_holding(0.0, 0.0, 1.0, 100.0)       # A: 1 sh @ $100
    s, a = dca_service.apply_to_holding(s, a, 2.0, 150.0)           # B: 2 sh, $150
    s, a = dca_service.undo_from_holding(s, a, 1.0, 100.0)          # undo A
    assert s == pytest.approx(2.0)
    assert a == pytest.approx(75.0)  # only B remains: $150 / 2 sh


def test_undo_last_buy_zeroes_out():
    s, a = dca_service.apply_to_holding(0.0, 0.0, 0.5, 50.0)
    s2, a2 = dca_service.undo_from_holding(s, a, 0.5, 50.0)
    assert s2 == 0.0
    assert a2 == 0.0
