# pylint: disable=protected-access,redefined-outer-name,unused-argument,too-few-public-methods
"""Verdict report card — grade past calls by return-since vs current price.

Service tests inject a `price_map` so nothing touches the network. Router tests
mount the bare AI router on an in-memory DB and monkeypatch the price fetch, so
the endpoint is exercised end to end without live quotes.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, VerdictSnapshot
from app.routers import ai as ai_router
from app.services import verdict_report
from app.services.verdict_report import build_verdict_report

_NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


class _Snap:
    def __init__(self, ticker, action, price_at_scan, days_ago, tz=timezone.utc):
        self.ticker = ticker
        self.action = action
        self.price_at_scan = price_at_scan
        gen = _NOW - timedelta(days=days_ago)
        self.generated_at = gen if tz else gen.replace(tzinfo=None)


# ── Service: scoring logic ──────────────────────────────────────────────────────


def test_add_that_rose_is_a_hit():
    snaps = [_Snap("AAPL", "add", 100.0, 30)]
    report = build_verdict_report(snaps, now=_NOW, price_map={"AAPL": 120.0})
    assert report["graded_count"] == 1
    assert report["hit_count"] == 1
    assert report["ledger"][0]["return_since_pct"] == 20.0
    assert report["ledger"][0]["hit"] is True


def test_add_that_fell_is_a_miss():
    report = build_verdict_report([_Snap("AAPL", "add", 100.0, 30)], now=_NOW,
                                  price_map={"AAPL": 90.0})
    assert report["hit_count"] == 0
    assert report["ledger"][0]["hit"] is False


def test_trim_that_fell_is_a_hit():
    report = build_verdict_report([_Snap("X", "trim", 100.0, 30)], now=_NOW,
                                  price_map={"X": 80.0})
    assert report["ledger"][0]["hit"] is True


def test_hold_within_band_is_a_hit_outside_is_miss():
    within = build_verdict_report([_Snap("H", "hold", 100.0, 30)], now=_NOW,
                                  price_map={"H": 105.0})
    outside = build_verdict_report([_Snap("H", "hold", 100.0, 30)], now=_NOW,
                                   price_map={"H": 130.0})
    assert within["ledger"][0]["hit"] is True
    assert outside["ledger"][0]["hit"] is False


def test_recent_call_is_pending_not_graded():
    report = build_verdict_report([_Snap("AAPL", "add", 100.0, 1)], now=_NOW,
                                  price_map={"AAPL": 200.0})
    assert report["graded_count"] == 0
    assert report["pending_young"] == 1


def test_unpriced_ticker_is_pending_price():
    report = build_verdict_report([_Snap("DELISTED", "add", 100.0, 30)], now=_NOW,
                                  price_map={})
    assert report["graded_count"] == 0
    assert report["pending_price"] == 1


def test_naive_generated_at_is_treated_as_utc():
    # A DB-default (naive) timestamp must not raise when subtracted from aware now.
    report = build_verdict_report([_Snap("AAPL", "add", 100.0, 30, tz=None)], now=_NOW,
                                  price_map={"AAPL": 120.0})
    assert report["graded_count"] == 1


def test_missing_scan_price_skipped():
    report = build_verdict_report([_Snap("AAPL", "add", None, 30)], now=_NOW,
                                  price_map={"AAPL": 120.0})
    assert report["graded_count"] == 0
    assert report["pending_price"] == 0 and report["pending_young"] == 0


def test_zero_or_negative_scan_price_skipped():
    # A 0/negative price_at_scan is unusable (would divide by zero) — skip silently.
    snaps = [_Snap("A", "add", 0.0, 30), _Snap("B", "add", -5.0, 30)]
    report = build_verdict_report(snaps, now=_NOW, price_map={"A": 120.0, "B": 120.0})
    assert report["graded_count"] == 0
    assert report["pending_price"] == 0 and report["pending_young"] == 0


def test_unknown_action_skipped():
    report = build_verdict_report([_Snap("A", "sell", 100.0, 30)], now=_NOW,
                                  price_map={"A": 120.0})
    assert report["graded_count"] == 0


def test_naive_now_does_not_raise():
    # A naive `now` must be coerced, not TypeError against aware generated_at.
    naive_now = _NOW.replace(tzinfo=None)
    report = build_verdict_report([_Snap("AAPL", "add", 100.0, 30)], now=naive_now,
                                  price_map={"AAPL": 120.0})
    assert report["graded_count"] == 1


def test_by_action_hit_rates_and_overall():
    snaps = [
        _Snap("A", "add", 100.0, 30),   # +20 hit
        _Snap("B", "add", 100.0, 30),   # -10 miss
        _Snap("C", "trim", 100.0, 30),  # -20 hit
    ]
    report = build_verdict_report(snaps, now=_NOW,
                                  price_map={"A": 120.0, "B": 90.0, "C": 80.0})
    assert report["graded_count"] == 3
    assert report["hit_count"] == 2
    assert report["hit_rate"] == round(2 / 3 * 100, 1)
    add = next(b for b in report["by_action"] if b["action"] == "add")
    assert add["total"] == 2 and add["hits"] == 1 and add["hit_rate"] == 50.0


# ── Router ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(VerdictSnapshot(ticker="AAPL", action="add", confidence=70, local_score=70,
                                price_at_scan=100.0,
                                generated_at=datetime.now(timezone.utc) - timedelta(days=30)))
    session.commit()
    # No live quotes in tests: price the fan-out deterministically.
    monkeypatch.setattr(verdict_report, "_fetch_current_prices", lambda tickers: {"AAPL": 120.0})
    app = FastAPI()
    app.include_router(ai_router.router)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def test_endpoint_grades_snapshot(client):
    body = client.get("/api/ai/verdict-report").json()
    assert body["graded_count"] == 1
    assert body["hit_count"] == 1
    assert body["ledger"][0]["ticker"] == "AAPL"


def test_endpoint_empty_when_no_snapshots(monkeypatch):
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(ai_router.router)
    app.dependency_overrides[get_db] = lambda: session
    body = TestClient(app).get("/api/ai/verdict-report").json()
    assert body["graded_count"] == 0
    assert body["hit_rate"] is None
    assert body["ledger"] == []
