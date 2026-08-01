"""HTTP-level tests for GET /api/portfolio/fee-drag.

Mounts only the portfolio router via the shared `api_client` fixture, so the
full app lifespan never runs. Both quote seams are monkeypatched — the fee math
itself is covered by tests/test_fund_costs.py; this file is about the router:
the quote-metadata merge, query-param validation, and 404s.
"""
# pylint: disable=redefined-outer-name,unused-argument
import pytest

from app.models import Holding
from app.routers import portfolio as portfolio_router
from app.services import portfolio_valuation

_FULL_QUOTES = {
    "VOO": {"quote_type": "ETF", "expense_ratio": 0.003},
    "AAPL": {"quote_type": "EQUITY", "exchange": "NMS"},
}


def _fast_quotes(tickers):
    """What portfolio_valuation prices the book with — no fund metadata on it."""
    return [
        {"ticker": t, "name": t, "current_price": 100.0,
         "day_change": 0.0, "day_change_pct": 0.0}
        for t in tickers
    ]


@pytest.fixture
def client(monkeypatch, db, api_client):
    monkeypatch.setattr(portfolio_valuation, "get_portfolio_quotes", _fast_quotes)
    monkeypatch.setattr(
        portfolio_router,
        "get_all_quotes",
        lambda tickers: [{"ticker": t, **_FULL_QUOTES.get(t, {})} for t in tickers],
    )
    db.add(Holding(portfolio_id=1, ticker="VOO", shares=100, avg_cost=50,
                   is_active=True, is_watchlist=False))
    db.add(Holding(portfolio_id=1, ticker="AAPL", shares=50, avg_cost=50,
                   is_active=True, is_watchlist=False))
    db.commit()
    return api_client(portfolio_router.router)


def test_fee_drag_prices_funds_from_the_merged_quote_metadata(client):
    body = client.get("/api/portfolio/fee-drag").json()

    # 100 × $100 = $10,000 at 30bps
    assert body["annual_fee_cost"] == 30.0
    assert [h["ticker"] for h in body["holdings"]] == ["VOO"]
    assert body["coverage"]["stock_count"] == 1
    assert body["coverage"]["fund_count"] == 1
    assert body["data_quality"] == "complete"


def test_fee_drag_defaults_to_a_ten_year_horizon(client):
    body = client.get("/api/portfolio/fee-drag").json()

    assert body["horizon_years"] == 10
    assert body["horizon_fee_cost"] > body["annual_fee_cost"]
    assert body["assumptions"]["note"]


def test_fee_drag_accepts_a_custom_horizon(client):
    body = client.get("/api/portfolio/fee-drag?horizon_years=1").json()

    assert body["horizon_years"] == 1
    assert body["horizon_fee_cost"] == 30.0


def test_fee_drag_rejects_an_out_of_range_horizon(client):
    assert client.get("/api/portfolio/fee-drag?horizon_years=-1").status_code == 422
    assert client.get("/api/portfolio/fee-drag?horizon_years=41").status_code == 422
    assert client.get("/api/portfolio/fee-drag?horizon_years=bogus").status_code == 422


def test_fee_drag_degrades_honestly_when_quotes_are_unavailable(monkeypatch, client):
    monkeypatch.setattr(
        portfolio_router,
        "get_all_quotes",
        lambda tickers: [{"ticker": t, "error": "Quote data is temporarily unavailable."}
                         for t in tickers],
    )

    body = client.get("/api/portfolio/fee-drag").json()

    # VOO is a known ETF by ticker even with no quote, but its fee is unknown —
    # never silently zero.
    assert body["has_data"] is False
    assert body["annual_fee_cost"] == 0.0
    assert body["coverage"]["uncovered_tickers"] == ["VOO"]
    assert body["data_quality"] == "unavailable"


def test_fee_drag_unknown_portfolio_404s(client):
    assert client.get("/api/portfolio/fee-drag?portfolio_id=999").status_code == 404
