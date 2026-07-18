"""Thesis notes reach the frontend — the stored ``Holding.notes`` text must ride
along on both holdings payloads so the dashboard can show and edit it.

The write path (PUT /holdings/{id} with ``notes``) is already covered by
tests/test_portfolio_management.py; these tests pin the read path, which
previously dropped the field on the floor.
"""
# pylint: disable=redefined-outer-name
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, Holding, Portfolio
from app.routers import portfolio as portfolio_router
from app.services import portfolio_valuation


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
    db.add(Holding(portfolio_id=1, ticker="VOO", shares=10, avg_cost=400,
                   is_active=True, is_watchlist=False,
                   notes="Core index position — never trim on vibes."))
    db.add(Holding(portfolio_id=1, ticker="TSLA", shares=5, avg_cost=200,
                   is_active=True, is_watchlist=False))
    db.commit()
    return db


def _fast_quotes(tickers):
    return [
        {"ticker": t, "name": t, "current_price": 100.0,
         "day_change": 0.0, "day_change_pct": 0.0}
        for t in tickers
    ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(portfolio_valuation, "get_portfolio_quotes", _fast_quotes)
    db = _make_db()
    app = FastAPI()
    app.include_router(portfolio_router.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _holding(body: dict, ticker: str) -> dict:
    return next(h for h in body["holdings"] if h["ticker"] == ticker)


def test_holdings_endpoint_returns_notes(client):
    body = client.get("/api/portfolio/holdings").json()
    assert _holding(body, "VOO")["notes"] == "Core index position — never trim on vibes."


def test_holdings_endpoint_returns_none_when_no_notes(client):
    body = client.get("/api/portfolio/holdings").json()
    assert _holding(body, "TSLA")["notes"] is None


def test_value_payload_rows_carry_notes(client):
    body = client.get("/api/portfolio/value").json()
    assert _holding(body, "VOO")["notes"] == "Core index position — never trim on vibes."
    assert _holding(body, "TSLA")["notes"] is None
