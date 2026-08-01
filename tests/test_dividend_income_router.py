"""HTTP-level tests for GET /api/portfolio/income.

Same shape as tests/test_fund_costs_router.py: mount only the portfolio router
via the shared `api_client` fixture, monkeypatch both quote seams. The income
math is covered by tests/test_dividend_income.py; this is about the router —
the quote-metadata merge and the non-filer 404.
"""
# pylint: disable=redefined-outer-name,unused-argument
import pytest

from app.models import Holding
from app.routers import portfolio as portfolio_router
from app.services import portfolio_valuation

# VZ pays $3/share; TSLA pays nothing. Prices come from the fast-quote seam ($100).
_FULL_QUOTES = {
    "VZ": {"quote_type": "EQUITY", "dividend_rate": 3.0, "dividend_yield": 0.03},
    "TSLA": {"quote_type": "EQUITY", "dividend_rate": None, "dividend_yield": None},
}


def _fast_quotes(tickers):
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
    db.add(Holding(portfolio_id=1, ticker="VZ", shares=100, avg_cost=40,
                   is_active=True, is_watchlist=False))
    db.add(Holding(portfolio_id=1, ticker="TSLA", shares=10, avg_cost=200,
                   is_active=True, is_watchlist=False))
    db.commit()
    return api_client(portfolio_router.router)


def test_income_is_priced_from_merged_quote_metadata(client):
    body = client.get("/api/portfolio/income").json()

    # VZ: 100 shares × $3 = $300/yr; TSLA pays nothing.
    assert body["total_annual_income"] == 300.0
    assert [p["ticker"] for p in body["payers"]] == ["VZ"]
    assert "TSLA" in body["coverage"]["non_payers"]


def test_income_reports_portfolio_yield(client):
    body = client.get("/api/portfolio/income").json()
    # $300 income / $11,000 total value ≈ 2.7%.
    assert 0.02 < body["portfolio_yield"] < 0.03


def test_income_unknown_portfolio_404s(client):
    assert client.get("/api/portfolio/income?portfolio_id=999").status_code == 404


def test_income_degrades_when_quotes_unavailable(monkeypatch, client):
    monkeypatch.setattr(
        portfolio_router,
        "get_all_quotes",
        lambda tickers: [{"ticker": t, "error": "unavailable"} for t in tickers],
    )
    body = client.get("/api/portfolio/income").json()
    # No dividend metadata reachable → no payers, honest empty.
    assert body["has_data"] is False
    assert body["total_annual_income"] == 0.0
