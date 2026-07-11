# pylint: disable=protected-access,redefined-outer-name,unused-argument,too-few-public-methods,too-many-positional-arguments,too-many-arguments
"""Year-end realized-gains recap — service aggregation + the HTTP endpoint.

Service tests drive the pure `build_realized_recap` with lightweight trade
stand-ins. Router tests mount the bare portfolio router on an in-memory DB
(the tests/test_earnings_radar_router.py pattern) to cover year selection,
active-portfolio scoping, and the 404 path.
"""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, Portfolio, RealizedTrade
from app.routers import portfolio as portfolio_router
from app.services.realized_recap import build_realized_recap


class _Trade:
    """Minimal stand-in for a RealizedTrade row."""

    def __init__(self, ticker, shares, sale, cost, gain, created):
        self.ticker = ticker
        self.shares_sold = shares
        self.sale_price = sale
        self.avg_cost = cost
        self.realized_gain = gain
        self.created_at = created


# ── Service: aggregation, year bucketing, best/worst ────────────────────────────


def test_empty_when_no_trades():
    recap = build_realized_recap([])
    assert recap["years"] == []
    assert recap["year"] is None
    assert recap["summary"]["realized_gain"] == 0.0
    assert recap["best"] is None and recap["worst"] is None


def test_groups_by_year_and_defaults_to_latest():
    trades = [
        _Trade("AAPL", 10, 110, 100, 100.0, datetime(2025, 6, 1)),
        _Trade("MSFT", 5, 90, 100, -50.0, datetime(2026, 3, 1)),
    ]
    recap = build_realized_recap(trades)
    assert recap["years"] == [2026, 2025]
    assert recap["year"] == 2026  # most recent by default
    assert recap["summary"]["trade_count"] == 1
    assert recap["summary"]["realized_gain"] == -50.0


def test_explicit_year_selects_that_bucket():
    trades = [
        _Trade("AAPL", 10, 110, 100, 100.0, datetime(2025, 6, 1)),
        _Trade("MSFT", 5, 90, 100, -50.0, datetime(2026, 3, 1)),
    ]
    recap = build_realized_recap(trades, year=2025)
    assert recap["year"] == 2025
    assert recap["summary"]["realized_gain"] == 100.0
    assert recap["best"]["ticker"] == "AAPL"
    assert recap["worst"] is None  # no losers in 2025


def test_unknown_year_falls_back_to_latest():
    trades = [_Trade("AAPL", 10, 110, 100, 100.0, datetime(2025, 6, 1))]
    recap = build_realized_recap(trades, year=1999)
    assert recap["year"] == 2025


def test_best_and_worst_and_winner_loser_counts():
    trades = [
        _Trade("WIN", 10, 150, 100, 500.0, datetime(2026, 2, 1)),
        _Trade("LOSE", 10, 80, 100, -200.0, datetime(2026, 4, 1)),
        _Trade("FLAT", 10, 100, 100, 0.0, datetime(2026, 5, 1)),
    ]
    recap = build_realized_recap(trades, year=2026)
    assert recap["best"]["ticker"] == "WIN"
    assert recap["worst"]["ticker"] == "LOSE"
    assert recap["summary"]["winners"] == 1
    assert recap["summary"]["losers"] == 1  # FLAT (0.0) is neither
    assert recap["summary"]["tickers"] == 3


def test_same_ticker_multiple_sales_aggregate():
    trades = [
        _Trade("AAPL", 10, 110, 100, 100.0, datetime(2026, 2, 1)),
        _Trade("AAPL", 5, 120, 100, 100.0, datetime(2026, 6, 1)),
    ]
    recap = build_realized_recap(trades, year=2026)
    assert recap["summary"]["tickers"] == 1
    row = recap["by_ticker"][0]
    assert row["trade_count"] == 2
    assert row["shares_sold"] == 15.0
    assert row["realized_gain"] == 200.0


def test_trade_without_date_is_skipped():
    trades = [
        _Trade("AAPL", 10, 110, 100, 100.0, None),
        _Trade("MSFT", 5, 120, 100, 100.0, datetime(2026, 6, 1)),
    ]
    recap = build_realized_recap(trades)
    assert recap["years"] == [2026]
    assert recap["summary"]["tickers"] == 1


def test_zero_cost_basis_return_pct_is_none():
    # avg_cost 0 → cost_basis 0 must yield return_pct None, never a ZeroDivisionError.
    trades = [_Trade("FREE", 10, 50, 0, 500.0, datetime(2026, 3, 1))]
    recap = build_realized_recap(trades, year=2026)
    assert recap["summary"]["return_pct"] is None
    assert recap["by_ticker"][0]["return_pct"] is None
    assert recap["summary"]["realized_gain"] == 500.0


# ── Router: scoping, year param, 404 ────────────────────────────────────────────


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(Portfolio(id=1, name="Test"))
    session.add(RealizedTrade(portfolio_id=1, ticker="AAPL", shares_sold=10, sale_price=110,
                              avg_cost=100, realized_gain=100.0, created_at=datetime(2026, 3, 1)))
    session.add(RealizedTrade(portfolio_id=1, ticker="MSFT", shares_sold=5, sale_price=90,
                              avg_cost=100, realized_gain=-50.0, created_at=datetime(2025, 8, 1)))
    session.commit()
    app = FastAPI()
    app.include_router(portfolio_router.router)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def test_endpoint_defaults_to_latest_year(client):
    body = client.get("/api/portfolio/realized-summary").json()
    assert body["portfolio_id"] == 1
    assert body["year"] == 2026
    assert body["years"] == [2026, 2025]
    assert body["summary"]["realized_gain"] == 100.0


def test_endpoint_year_param(client):
    body = client.get("/api/portfolio/realized-summary?year=2025").json()
    assert body["year"] == 2025
    assert body["summary"]["realized_gain"] == -50.0


def test_endpoint_unknown_portfolio_404s(client):
    assert client.get("/api/portfolio/realized-summary?portfolio_id=999").status_code == 404
