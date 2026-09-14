"""HTTP-level tests for GET /api/portfolio/income-calendar.

Same shape as tests/test_dividend_income_router.py: mount only the portfolio
router on a bare app with an in-memory DB, monkeypatch the quote seams plus the
ex-date fetch. Projection math is covered by tests/test_dividend_calendar.py;
this is about composition — payers feed the calendar, non-payers never trigger
a history fetch.
"""
# pylint: disable=redefined-outer-name,unused-argument
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, Holding, Portfolio
from app.routers import portfolio as portfolio_router
from app.services import dividend_calendar, portfolio_valuation

_FULL_QUOTES = {
    "VZ": {"quote_type": "EQUITY", "dividend_rate": 3.0, "dividend_yield": 0.03},
    "TSLA": {"quote_type": "EQUITY", "dividend_rate": None, "dividend_yield": None},
}

_FETCHED: list[list[str]] = []


def _trailing_quarterly_dates(today: date) -> list[date]:
    month_index = today.year * 12 + today.month - 1
    return [
        date((month_index - offset) // 12, (month_index - offset) % 12 + 1, 1)
        for offset in (9, 6, 3, 0)
    ]


def _make_db(payers_only: bool = False):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)  # pylint: disable=invalid-name
    db = Session()
    db.add(Portfolio(id=1, name="Test"))
    db.add(Holding(portfolio_id=1, ticker="VZ", shares=100, avg_cost=40,
                   is_active=True, is_watchlist=False))
    if not payers_only:
        db.add(Holding(portfolio_id=1, ticker="TSLA", shares=10, avg_cost=200,
                       is_active=True, is_watchlist=False))
    db.commit()
    return db


def _fast_quotes(tickers):
    return [
        {"ticker": t, "name": t, "current_price": 100.0,
         "day_change": 0.0, "day_change_pct": 0.0}
        for t in tickers
    ]


def _fake_ex_dates(tickers):
    _FETCHED.append(sorted(tickers))
    dates = _trailing_quarterly_dates(date.today())
    return {t: list(dates) for t in tickers}


@pytest.fixture
def client(monkeypatch):
    _FETCHED.clear()
    monkeypatch.setattr(portfolio_valuation, "get_portfolio_quotes", _fast_quotes)
    monkeypatch.setattr(
        portfolio_router,
        "get_all_quotes",
        lambda tickers: [{"ticker": t, **_FULL_QUOTES.get(t, {})} for t in tickers],
    )
    monkeypatch.setattr(dividend_calendar, "fetch_dividend_ex_dates", _fake_ex_dates)
    db = _make_db()
    app = FastAPI()
    app.include_router(portfolio_router.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_calendar_projects_only_the_payers(client):
    body = client.get("/api/portfolio/income-calendar").json()
    assert body["has_data"] is True
    assert body["basis"] == "ex_date"
    # VZ pays $3/share on 100 shares = $300/yr → $75 per quarter-month.
    totals = [m["total"] for m in body["months"] if m["total"] > 0]
    assert totals == [75.0, 75.0, 75.0, 75.0]
    # Only the payer's history was fetched — TSLA pays nothing, so its ex-date
    # history is not worth a network call.
    assert _FETCHED == [["VZ"]]


def test_no_payers_is_an_honest_empty_not_an_error(monkeypatch):
    monkeypatch.setattr(portfolio_valuation, "get_portfolio_quotes", _fast_quotes)
    monkeypatch.setattr(
        portfolio_router, "get_all_quotes",
        lambda tickers: [{"ticker": t, "quote_type": "EQUITY",
                          "dividend_rate": None} for t in tickers],
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(dividend_calendar, "fetch_dividend_ex_dates",
                        lambda tickers: calls.append(list(tickers)) or {})
    db = _make_db(payers_only=True)
    app = FastAPI()
    app.include_router(portfolio_router.router)
    app.dependency_overrides[get_db] = lambda: db
    body = TestClient(app).get("/api/portfolio/income-calendar").json()
    assert body["has_data"] is False
    assert body["months"] == []
    assert not calls  # nothing to fetch for a payerless portfolio
