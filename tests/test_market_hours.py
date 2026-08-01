"""The market-hours seam: one answer to "is the market open?".

Every case pins an explicit instant rather than reading the wall clock, so the
suite gives the same verdict at 3am as at noon.
"""
from datetime import datetime

from app.services import market_hours


def _et(year, month, day, hour, minute=0):
    return market_hours.EASTERN.localize(datetime(year, month, day, hour, minute))


# 2026-08-03 is a Monday; 2026-08-08 a Saturday; 2026-08-07 a Friday.
MONDAY_OPEN = _et(2026, 8, 3, 10, 0)
MONDAY_PREBELL = _et(2026, 8, 3, 9, 29)
MONDAY_AFTER = _et(2026, 8, 3, 16, 1)
FRIDAY_AFTER = _et(2026, 8, 7, 17, 0)
SATURDAY = _et(2026, 8, 8, 12, 0)


class TestIsOpen:
    def test_midsession_weekday_is_open(self):
        assert market_hours.is_open(MONDAY_OPEN) is True

    def test_the_bells_themselves_are_inclusive(self):
        assert market_hours.is_open(_et(2026, 8, 3, 9, 30)) is True
        assert market_hours.is_open(_et(2026, 8, 3, 16, 0)) is True

    def test_one_minute_either_side_is_closed(self):
        assert market_hours.is_open(MONDAY_PREBELL) is False
        assert market_hours.is_open(MONDAY_AFTER) is False

    def test_weekends_are_closed_all_day(self):
        assert market_hours.is_open(SATURDAY) is False
        assert market_hours.is_open(_et(2026, 8, 9, 12, 0)) is False  # Sunday


class TestNextOpenLabel:
    def test_open_market_has_no_next_bell(self):
        assert market_hours.next_open_label(MONDAY_OPEN) is None

    def test_before_the_weekday_bell_points_at_today(self):
        assert market_hours.next_open_label(MONDAY_PREBELL) == "9:30 AM ET today"

    def test_midweek_after_close_points_at_tomorrow(self):
        assert market_hours.next_open_label(MONDAY_AFTER) == "9:30 AM ET tomorrow"

    def test_friday_evening_and_the_weekend_point_at_monday(self):
        assert market_hours.next_open_label(FRIDAY_AFTER) == "Mon 9:30 AM ET"
        assert market_hours.next_open_label(SATURDAY) == "Mon 9:30 AM ET"


class TestSessionStatus:
    def test_open_payload(self):
        assert market_hours.session_status(MONDAY_OPEN) == {
            "is_open": True,
            "status": "OPEN",
            "eastern_time": "10:00 AM ET",
            "next_open": None,
        }

    def test_closed_payload_carries_the_next_bell(self):
        status = market_hours.session_status(SATURDAY)
        assert status["is_open"] is False
        assert status["status"] == "CLOSED"
        assert status["next_open"] == "Mon 9:30 AM ET"


def test_the_ttl_selectors_and_the_badge_read_the_same_clock():
    """The duplication this module replaced: two answers to one question.

    stock_service picks its cache TTL from `is_open`, and the /market-status
    badge renders `session_status`. Both must agree at every instant, or the app
    caches as if closed while telling the user it is open.
    """
    for moment in (MONDAY_OPEN, MONDAY_PREBELL, MONDAY_AFTER, FRIDAY_AFTER, SATURDAY):
        assert market_hours.session_status(moment)["is_open"] is market_hours.is_open(moment)
