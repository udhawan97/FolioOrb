"""Removal must create a truthful sale or leave every financial fact unchanged."""
from datetime import datetime

import pytest

from app.models import Holding, RealizedTrade
from app.routers import portfolio as portfolio_router


def _holding(db, *, watchlist=False):
    holding = Holding(
        portfolio_id=1,
        ticker="ACME",
        shares=10,
        avg_cost=100,
        is_active=True,
        is_watchlist=watchlist,
    )
    db.add(holding)
    db.commit()
    return holding


def _assert_no_removal_mutation(db, holding_id):
    db.expire_all()
    holding = db.query(Holding).filter_by(id=holding_id).one()
    assert holding.is_active is True
    assert holding.shares == 10
    assert db.query(RealizedTrade).count() == 0
    assert not db.new
    assert not db.dirty


def test_missing_quote_returns_actionable_conflict_with_zero_mutation(
    db, api_client, monkeypatch
):
    holding = _holding(db)
    monkeypatch.setattr(
        portfolio_router,
        "get_stock_data",
        lambda _ticker: {"current_price": 0, "currency": "USD"},
    )

    response = api_client(portfolio_router.router).delete(
        f"/api/portfolio/holdings/{holding.id}"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sale_price_required"
    _assert_no_removal_mutation(db, holding.id)


@pytest.mark.parametrize(
    "quote",
    [
        {"current_price": 125, "currency": "GBP"},
        {"current_price": 125},
        {"current_price": float("nan"), "currency": "USD"},
        {"current_price": float("inf"), "currency": "USD"},
    ],
)
def test_foreign_ambiguous_or_nonfinite_quote_cannot_remove(
    db, api_client, monkeypatch, quote
):
    holding = _holding(db)
    monkeypatch.setattr(portfolio_router, "get_stock_data", lambda _ticker: quote)

    response = api_client(portfolio_router.router).delete(
        f"/api/portfolio/holdings/{holding.id}"
    )

    assert response.status_code == 409
    _assert_no_removal_mutation(db, holding.id)


def test_explicit_usd_price_locks_manual_provenance_without_loading_a_quote(
    db, api_client, monkeypatch
):
    holding = _holding(db)

    def quote_must_not_run(_ticker):
        raise AssertionError("explicit sale must not load a quote")

    monkeypatch.setattr(portfolio_router, "get_stock_data", quote_must_not_run)
    response = api_client(portfolio_router.router).request(
        "DELETE",
        f"/api/portfolio/holdings/{holding.id}",
        json={
            "sale_price": 123.45,
            "sale_currency": "USD",
            "sale_price_source": "manual_entry",
            "sale_date": "2026-01-15",
        },
    )

    assert response.status_code == 200
    db.expire_all()
    assert db.query(Holding).filter_by(id=holding.id).one().is_active is False
    trade = db.query(RealizedTrade).one()
    assert trade.sale_price == 123.45
    assert trade.sale_currency == "USD"
    assert trade.sale_price_source == "manual_entry"
    assert trade.created_at == datetime(2026, 1, 15, 12, 0)


def test_valid_explicit_usd_market_quote_records_market_provenance(
    db, api_client, monkeypatch
):
    holding = _holding(db)
    monkeypatch.setattr(
        portfolio_router,
        "get_stock_data",
        lambda _ticker: {"current_price": 126.5, "currency": "USD"},
    )

    response = api_client(portfolio_router.router).delete(
        f"/api/portfolio/holdings/{holding.id}"
    )

    assert response.status_code == 200
    trade = db.query(RealizedTrade).one()
    assert trade.sale_price == 126.5
    assert trade.sale_currency == "USD"
    assert trade.sale_price_source == "market_quote"


@pytest.mark.parametrize(
    "payload",
    [
        {"sale_price": 123, "sale_currency": "GBP", "sale_price_source": "manual_entry"},
        {"sale_price": 123, "sale_currency": "USD", "sale_price_source": "market_quote"},
        {"sale_price": 123, "sale_currency": "USD"},
        {"sale_price": 123, "sale_price_source": "manual_entry"},
        {"sale_currency": "USD", "sale_price_source": "manual_entry"},
    ],
)
def test_arbitrary_or_partial_explicit_provenance_is_rejected_before_mutation(
    db, api_client, payload
):
    holding = _holding(db)

    response = api_client(portfolio_router.router).request(
        "DELETE", f"/api/portfolio/holdings/{holding.id}", json=payload
    )

    assert response.status_code == 422
    _assert_no_removal_mutation(db, holding.id)


def test_watchlist_removal_never_loads_a_quote_or_records_a_sale(
    db, api_client, monkeypatch
):
    holding = _holding(db, watchlist=True)

    def quote_must_not_run(_ticker):
        raise AssertionError("watchlist discard must not load a quote")

    monkeypatch.setattr(portfolio_router, "get_stock_data", quote_must_not_run)

    response = api_client(portfolio_router.router).delete(
        f"/api/portfolio/holdings/{holding.id}"
    )

    assert response.status_code == 200
    db.expire_all()
    assert db.query(Holding).filter_by(id=holding.id).one().is_active is False
    assert db.query(RealizedTrade).count() == 0


def test_unpriceable_partial_reduction_also_leaves_shares_and_ledger_unchanged(
    db, api_client, monkeypatch
):
    holding = _holding(db)
    monkeypatch.setattr(
        portfolio_router,
        "get_stock_data",
        lambda _ticker: {"current_price": 140, "currency": "CAD"},
    )

    response = api_client(portfolio_router.router).put(
        f"/api/portfolio/holdings/{holding.id}", json={"shares": 5}
    )

    assert response.status_code == 409
    _assert_no_removal_mutation(db, holding.id)
