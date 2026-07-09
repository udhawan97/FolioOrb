"""HTTP-level tests for GET /api/portfolio/earnings.

Mounts only the portfolio router on a bare FastAPI app (the pattern in
tests/test_system_router.py) with an in-memory SQLite DB (the pattern in
tests/test_action_plan.py), so the full app lifespan never runs. Earnings
resolution itself is monkeypatched — the service is covered by
tests/test_earnings_radar.py; this file is about the router: query-param
validation, the is_watchlist merge, active-holding scoping, and 404s.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, Holding, Portfolio
from app.routers import portfolio as portfolio_router


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)  # pylint: disable=invalid-name
    db = Session()
    db.add(Portfolio(id=1, name="Test"))
    db.add(Holding(portfolio_id=1, ticker="MSFT", shares=10, avg_cost=100,
                    is_active=True, is_watchlist=False))
    db.add(Holding(portfolio_id=1, ticker="NVDA", shares=5, avg_cost=50,
                    is_active=True, is_watchlist=True))
    db.add(Holding(portfolio_id=1, ticker="OLD", shares=1, avg_cost=1,
                    is_active=False, is_watchlist=False))  # soft-deleted
    db.commit()
    return db


@pytest.fixture
def client():
    db = _make_db()
    app = FastAPI()
    app.include_router(portfolio_router.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_window_out_of_bounds_rejected(client):
    assert client.get("/api/portfolio/earnings?window=0").status_code == 422
    assert client.get("/api/portfolio/earnings?window=61").status_code == 422


def test_window_in_bounds_accepted(monkeypatch, client):
    monkeypatch.setattr(portfolio_router, "get_earnings_events", lambda tickers, window_days=30: [])
    assert client.get("/api/portfolio/earnings?window=60").status_code == 200


def test_is_watchlist_merged_onto_events(monkeypatch, client):
    def fake_events(tickers, window_days=30):
        return [
            {"ticker": "MSFT", "date": "2026-08-01", "days_until": 5, "label": "In 5 days"},
            {"ticker": "NVDA", "date": "2026-08-02", "days_until": 6, "label": "In 6 days"},
        ]
    monkeypatch.setattr(portfolio_router, "get_earnings_events", fake_events)

    body = client.get("/api/portfolio/earnings").json()
    by_ticker = {e["ticker"]: e for e in body["events"]}
    assert by_ticker["MSFT"]["is_watchlist"] is False
    assert by_ticker["NVDA"]["is_watchlist"] is True
    assert body["count"] == 2
    assert body["portfolio_id"] == 1
    assert body["window_days"] == 30


def test_inactive_holdings_excluded_from_ticker_scan(monkeypatch, client):
    seen = {}

    def fake_events(tickers, window_days=30):
        seen["tickers"] = tickers
        return []

    monkeypatch.setattr(portfolio_router, "get_earnings_events", fake_events)
    client.get("/api/portfolio/earnings")
    assert "OLD" not in seen["tickers"]
    assert set(seen["tickers"]) == {"MSFT", "NVDA"}


def test_unknown_portfolio_404s(client):
    assert client.get("/api/portfolio/earnings?portfolio_id=999").status_code == 404
