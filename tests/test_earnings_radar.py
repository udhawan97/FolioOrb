"""Tests for the earnings radar service (offline, fully mocked)."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
from datetime import date, timedelta

import pytest

from app.services import earnings_radar as er
from app.services.security_type import SecurityType


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty per-ticker date cache."""
    er._RADAR_CACHE.clear()
    yield
    er._RADAR_CACHE.clear()


def _patch(monkeypatch, *, dates, classify=None, info=None):
    """Wire up the three yfinance-facing calls with in-memory fakes.

    `dates` maps symbol -> date|None|Exception returned by fetch_next_earnings.
    `classify` maps symbol -> SecurityType (defaults to STOCK for everything).
    """
    monkeypatch.setattr(er, "get_ticker_info", lambda s: (info or {}))

    def _classify(symbol, _info):
        return (classify or {}).get(symbol, SecurityType.STOCK)

    def _fetch(symbol):
        value = dates.get(symbol)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(er, "classify_security", _classify)
    monkeypatch.setattr(er, "fetch_next_earnings", _fetch)


def test_window_filter_and_labels(monkeypatch):
    """Past dates drop out; 0..window survive; beyond window drops out."""
    today = date.today()
    _patch(monkeypatch, dates={
        "YEST": today - timedelta(days=1),   # past → excluded (the watch-out)
        "NOW": today,                        # 0 → "Today"
        "SOON": today + timedelta(days=1),   # 1 → "Tomorrow"
        "MID": today + timedelta(days=14),   # 14 → "In 14 days"
        "EDGE": today + timedelta(days=30),  # == window → kept
        "FAR": today + timedelta(days=31),   # > window → excluded
    })
    events = er.get_earnings_events(
        ["YEST", "NOW", "SOON", "MID", "EDGE", "FAR"], window_days=30
    )
    by_ticker = {e["ticker"]: e for e in events}
    assert set(by_ticker) == {"NOW", "SOON", "MID", "EDGE"}
    assert by_ticker["NOW"]["label"] == "Today"
    assert by_ticker["SOON"]["label"] == "Tomorrow"
    assert by_ticker["MID"]["label"] == "In 14 days"
    assert by_ticker["MID"]["days_until"] == 14


def test_non_stocks_skipped(monkeypatch):
    """ETFs/funds are classified out even with a near date."""
    today = date.today()
    _patch(
        monkeypatch,
        dates={"VOO": today + timedelta(days=3), "MSFT": today + timedelta(days=3)},
        classify={"VOO": SecurityType.ETF},
    )
    tickers = [e["ticker"] for e in er.get_earnings_events(["VOO", "MSFT"])]
    assert tickers == ["MSFT"]


def test_unknown_date_excluded(monkeypatch):
    """A ticker with no known earnings date is silently omitted."""
    _patch(monkeypatch, dates={"XYZ": None})
    assert not er.get_earnings_events(["XYZ"])


def test_one_failing_ticker_does_not_break_others(monkeypatch):
    """An exception for one ticker must not sink the whole fan-out."""
    today = date.today()
    _patch(monkeypatch, dates={
        "BAD": RuntimeError("yfinance blew up"),
        "GOOD": today + timedelta(days=5),
    })
    tickers = [e["ticker"] for e in er.get_earnings_events(["BAD", "GOOD"])]
    assert tickers == ["GOOD"]


def test_sorted_soonest_first(monkeypatch):
    """Events come back ordered by (days_until, ticker)."""
    today = date.today()
    _patch(monkeypatch, dates={
        "A": today + timedelta(days=9),
        "B": today + timedelta(days=2),
        "C": today + timedelta(days=2),
    })
    order = [e["ticker"] for e in er.get_earnings_events(["A", "B", "C"])]
    assert order == ["B", "C", "A"]


def test_caches_date_and_recomputes_days(monkeypatch):
    """Within TTL the date is cached (no refetch), yet days_until tracks 'today'."""
    class _Clock:
        t = 1000.0

        def monotonic(self):
            return self.t

    class _FakeDate(date):
        current = date(2026, 1, 1)

        @classmethod
        def today(cls):
            return cls.current

    clock = _Clock()
    monkeypatch.setattr(er, "time", clock)
    monkeypatch.setattr(er, "date", _FakeDate)

    calls = {"n": 0}

    def _fetch(_symbol):
        calls["n"] += 1
        return date(2026, 1, 6)  # fixed earnings date

    monkeypatch.setattr(er, "get_ticker_info", lambda s: {})
    monkeypatch.setattr(er, "classify_security", lambda s, i: SecurityType.STOCK)
    monkeypatch.setattr(er, "fetch_next_earnings", _fetch)

    first = er.get_earnings_events(["MSFT"], window_days=30)
    assert first[0]["days_until"] == 5 and calls["n"] == 1

    # Calendar advances two days; clock stays within TTL → cache hit, no refetch,
    # but the countdown recomputes from the cached date.
    _FakeDate.current = date(2026, 1, 3)
    second = er.get_earnings_events(["MSFT"], window_days=30)
    assert second[0]["days_until"] == 3 and calls["n"] == 1

    # Past the TTL → the ticker is resolved afresh.
    clock.t += er._RADAR_TTL + 1
    er.get_earnings_events(["MSFT"], window_days=30)
    assert calls["n"] == 2
