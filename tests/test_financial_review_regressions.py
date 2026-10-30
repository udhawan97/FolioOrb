"""Financial facts keep their identity, units and availability through failure."""
from datetime import date, datetime, timedelta
import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Holding, PortfolioSnapshot, RealizedTrade
from app.routers import portfolio
from app.services import (
    dividend_income, fund_costs, portfolio_projection, portfolio_review, portfolio_valuation,
)


def _quote(ticker, price=100.0, currency="USD", **metadata):
    return {
        "ticker": ticker, "current_price": price, "currency": currency,
        "day_change": 1.0, "day_change_pct": 1.0, **metadata,
    }


def _positions(db):
    db.add_all([
        Holding(id=1, portfolio_id=1, ticker="VTI", shares=10, avg_cost=90),
        Holding(id=2, portfolio_id=1, ticker="VOD.L", shares=20, avg_cost=50),
        Holding(id=3, portfolio_id=1, ticker="IDEA", shares=0, is_watchlist=True),
    ])
    db.commit()


def test_unavailable_rows_retain_identity_and_recover_without_snapshot(db, api_client, monkeypatch):
    _positions(db)
    monkeypatch.setattr(portfolio_valuation, "get_portfolio_quotes", lambda _tickers: [])
    client = api_client(portfolio.router)
    unavailable = client.get("/api/portfolio/value").json()
    assert {row["id"] for row in unavailable["holdings"]} == {1, 2, 3}
    assert unavailable["best_performer"] is None
    assert unavailable["worst_performer"] is None
    assert unavailable["expected_position_count"] == 2
    for row in unavailable["holdings"]:
        assert row["quote_available"] is False
        assert row["reporting_eligible"] is False
        for key in ("current_price", "current_value", "unrealized_gain", "allocation_pct"):
            assert row[key] is None
    assert db.query(PortfolioSnapshot).count() == 0

    monkeypatch.setattr(portfolio_valuation, "get_portfolio_quotes", lambda _tickers: [
        _quote("VTI"), _quote("VOD.L", currency="GBp"),
    ])
    recovered = client.get("/api/portfolio/value").json()
    assert {row["id"] for row in recovered["holdings"]} == {1, 2, 3}
    assert recovered["total_value"] == 1000
    assert recovered["data_quality"] == "partial"
    assert recovered["foreign_currency_tickers"] == ["VOD.L"]
    assert recovered["best_performer"]["ticker"] == "VTI"
    foreign = next(row for row in recovered["holdings"] if row["ticker"] == "VOD.L")
    assert foreign["current_value"] == 2000
    assert foreign["unrealized_gain"] is None
    assert foreign["allocation_pct"] is None
    assert db.query(Holding).count() == 3
    assert db.query(PortfolioSnapshot).count() == 0


def test_finite_operand_overflow_is_unavailable_not_nonfinite(db):
    db.add(Holding(portfolio_id=1, ticker="BIG", shares=1e308, avg_cost=1.0))
    db.commit()
    valued = portfolio_valuation.evaluate(
        db, 1, quote_loader=lambda _tickers: [_quote("BIG", 1e308)], record_snapshot=True,
    )
    assert valued.data_quality == "unavailable"
    assert valued.holdings[0]["current_value"] is None
    assert valued.holdings[0]["quote_available"] is False
    assert db.query(PortfolioSnapshot).count() == 0
    json.dumps(valued.holdings, allow_nan=False)

@pytest.mark.parametrize("quotes", [[], [_quote("VTI")], [_quote("VOD.L", currency="GBp")]])
def test_review_unavailable_comparison_is_not_a_false_loss(db, quotes):
    _positions(db)
    db.add(PortfolioSnapshot(
        portfolio_id=1, snapshot_date=(date.today() - timedelta(days=31)).isoformat(),
        total_value=2000, total_cost_basis=1500, unrealized_gain=500,
        realized_gain=0, total_return=500,
    ))
    db.commit()
    report = portfolio_review.build_review_report(db, 1, "month", quote_loader=lambda _t: quotes)
    assert report["period_activity"]["value_change"] is None
    assert report["current"]["total_value"] is None
    assert report["current"]["total_return"] is None
    assert report["current"]["total_return_pct"] is None
    assert report["current"]["realized_gain_all_time"] == 0
    expected_subtotal = 1000 if quotes and quotes[0]["ticker"] == "VTI" else 0
    assert report["current"]["known_value"] == expected_subtotal
    assert all(row["ticker"] != "VOD.L" for row in report["movers"])
    html = portfolio_review.report_html(report)
    assert "$Unavailable" not in html
    assert "Known USD subtotal" in html
    values = list(csv.reader(io.StringIO(portfolio_review.report_csv(report).lstrip("\ufeff"))))
    assert ["period_activity", "value_change", ""] in values
    assert ["current", "total_value", ""] in values


def test_period_accounting_uses_all_trusted_sales_but_display_is_bounded(db):
    now = datetime.now()
    facts = {
        "portfolio_id": 1, "ticker": "VTI", "shares_sold": 1, "sale_price": 2, "avg_cost": 1,
        "realized_gain": 1, "sale_currency": "USD", "sale_price_source": "manual_entry",
    }
    db.add_all([RealizedTrade(**facts, created_at=now) for _ in range(101)])
    db.add(RealizedTrade(**facts, created_at=now - timedelta(days=100)))
    db.add(RealizedTrade(**{**facts, "sale_currency": "CAD"}, created_at=now))
    db.commit()
    report = portfolio_review.build_review_report(db, 1, "month", quote_loader=lambda _t: [])
    assert report["period_activity"]["realized_gain"] == 101
    assert report["period_activity"]["realized_trade_count"] == 101
    assert len(portfolio_valuation.load_performance(db, 1).trades) == 100


def test_foreign_native_values_never_enter_usd_fees_income_or_projection(monkeypatch):
    usd = {
        "ticker": "VTI", "currency": "USD", "current_value": 1000, "shares": 10,
        "dividend_rate": 2, "expense_ratio": 0.01, "quote_type": "ETF",
    }
    foreign = {**usd, "ticker": "VOD.L", "currency": "GBp", "current_value": 1_000_000}
    missing = {**usd, "ticker": "MISS", "current_value": None, "quote_available": False}
    fee = fund_costs.compute_fee_drag([usd, foreign, missing])
    assert fee["annual_fee_cost"] == 10
    assert fee["covered_value"] == 1000
    assert fee["data_quality"] == "partial"
    income = dividend_income.compute_portfolio_income([usd, foreign, missing])
    assert income["total_annual_income"] == 20
    assert income["covered_value"] == 1000
    assert income["coverage"]["excluded_tickers"] == ["VOD.L", "MISS"]
    fetched = []
    monkeypatch.setattr(
        portfolio_projection, "_fetch_closes", lambda ticker: fetched.append(ticker) or []
    )
    projected = portfolio_projection.compute_portfolio_projection([usd, foreign, missing], 1000)
    assert projected["current_value"] == 1000
    assert set(fetched) == {"VTI", "SPY"}


@pytest.fixture(name="real_client")
def _real_client(db, monkeypatch):
    from app.main import app

    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db)
    monkeypatch.setattr(portfolio, "validate_ticker_symbol", lambda ticker: {
        "valid": True, "quote": _quote(ticker),
    })
    return TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)


@pytest.mark.parametrize("number", ["1e400", "NaN", "Infinity"])
def test_nonfinite_requests_return_json_safe_422_without_writes(db, real_client, number):
    response = real_client.post(
        "/api/portfolio/holdings", content='{"ticker":"VTI","shares":' + number + '}',
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "shares"]
    assert db.query(Holding).count() == 0


def test_finite_product_overflow_is_rejected_before_create_and_update(db, real_client):
    response = real_client.post(
        "/api/portfolio/holdings", json={"ticker": "VTI", "shares": 1e308, "avg_cost": 1e308},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 422
    assert db.query(Holding).count() == 0
    db.add(Holding(id=1, portfolio_id=1, ticker="VTI", shares=10, avg_cost=100))
    db.commit()
    response = real_client.put(
        "/api/portfolio/holdings/1", json={"avg_cost": 1e308},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 422
    assert db.get(Holding, 1).avg_cost == 100
    assert db.query(RealizedTrade).count() == 0
    assert db.query(PortfolioSnapshot).count() == 0


def test_overflow_sale_rejection_preserves_owned_position(db, real_client):
    db.add(Holding(id=1, portfolio_id=1, ticker="VTI", shares=10, avg_cost=100))
    db.commit()
    response = real_client.request(
        "DELETE", "/api/portfolio/holdings/1", json={
            "sale_price": 1e308, "sale_currency": "USD", "sale_price_source": "manual_entry",
        }, headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 422
    assert db.get(Holding, 1).is_active is True
    assert db.get(Holding, 1).shares == 10
    assert db.query(RealizedTrade).count() == 0


def test_overflow_sale_correction_rolls_back_and_fractional_purchase_stays_exact(db, real_client):
    created = real_client.post(
        "/api/portfolio/holdings", json={"ticker": "VTI", "shares": 0.125, "avg_cost": 3.125},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert created.status_code == 200
    holding = db.query(Holding).one()
    assert holding.shares == 0.125
    assert holding.avg_cost == 3.125
    db.add(RealizedTrade(
        id=1, portfolio_id=1, ticker="VTI", shares_sold=10, sale_price=100,
        avg_cost=90, realized_gain=100, sale_currency="USD", sale_price_source="manual_entry",
    ))
    db.commit()
    corrected = real_client.patch(
        "/api/portfolio/trades/1", json={"sale_price": 1e308},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert corrected.status_code == 422
    trade = db.get(RealizedTrade, 1)
    assert trade.sale_price == 100
    assert trade.realized_gain == 100
    assert db.query(PortfolioSnapshot).count() == 0


@pytest.mark.parametrize("second_ticker", ["VTI", "OTHER"])
def test_finite_sale_facts_with_overflowing_aggregates_refuse_snapshots_and_return_422(
    db, real_client, second_ticker
):
    db.add_all([
        RealizedTrade(
            portfolio_id=1, ticker=ticker, shares_sold=1, sale_price=1e308,
            avg_cost=1, realized_gain=1e308, sale_currency="USD", sale_price_source="manual_entry",
        )
        for ticker in ("VTI", second_ticker)
    ])
    db.commit()
    with pytest.raises(portfolio_valuation.FinancialArithmeticError, match="finite"):
        portfolio_valuation.evaluate(db, 1, quote_loader=lambda _t: [], record_snapshot=True)
    assert db.query(PortfolioSnapshot).count() == 0
    for route in ("/api/portfolio/value", "/api/portfolio/pnl", "/api/review/report"):
        response = real_client.get(route, headers={"Origin": "http://127.0.0.1:8000"})
        assert response.status_code == 422, response.text
        assert "finite numeric arithmetic" in response.json()["detail"]
        json.dumps(response.json(), allow_nan=False)
    assert db.query(RealizedTrade).count() == 2
    assert db.query(PortfolioSnapshot).count() == 0


def test_aggregate_sale_overflow_is_rejected_before_holding_or_ledger_change(db, real_client):
    db.add(Holding(id=1, portfolio_id=1, ticker="VTI", shares=1, avg_cost=1))
    db.add(RealizedTrade(
        portfolio_id=1, ticker="OLD", shares_sold=1, sale_price=1e308,
        avg_cost=1, realized_gain=1e308, sale_currency="USD", sale_price_source="manual_entry",
    ))
    db.commit()
    response = real_client.request(
        "DELETE", "/api/portfolio/holdings/1", json={
            "sale_price": 1e308, "sale_currency": "USD", "sale_price_source": "manual_entry",
        }, headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 422
    assert db.get(Holding, 1).is_active is True
    assert db.get(Holding, 1).shares == 1
    assert db.query(RealizedTrade).count() == 1
    assert db.query(PortfolioSnapshot).count() == 0


def test_total_cost_overflow_rejects_add_and_update_without_new_facts(db, real_client):
    db.add(Holding(id=1, portfolio_id=1, ticker="VTI", shares=1, avg_cost=1e308))
    db.add(Holding(id=2, portfolio_id=1, ticker="OTHER", shares=1, avg_cost=1))
    db.commit()
    added = real_client.post(
        "/api/portfolio/holdings", json={"ticker": "NEW", "shares": 1, "avg_cost": 1e308},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert added.status_code == 422
    assert db.query(Holding).count() == 2
    updated = real_client.put(
        "/api/portfolio/holdings/2", json={"avg_cost": 1e308},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert updated.status_code == 422
    assert db.get(Holding, 2).avg_cost == 1
    assert db.query(PortfolioSnapshot).count() == 0
