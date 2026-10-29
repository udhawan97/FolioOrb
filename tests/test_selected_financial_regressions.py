"""Selected audit regressions at financial consumer and write boundaries."""
from datetime import date, datetime, timedelta
import csv
import io
import json
import math
from zipfile import ZipFile

import pytest

from app.models import (
    DcaContribution, DcaPlan, Holding, Portfolio, PortfolioSnapshot, RealizedTrade,
)
from app.routers import dca as dca_router
from app.routers import portfolio as portfolio_router
from app.services import dca_service, portfolio_review, portfolio_valuation, review_bundle
from app.services.dca_ledger import DcaConflictError, DcaLedger


@pytest.mark.parametrize("currency", ["USD", "CAD", "GBp", "GBP"])
def test_compare_prices_retain_native_currency_without_converting(db, monkeypatch, currency):
    db.add_all([
        Holding(portfolio_id=1, ticker=ticker, is_watchlist=True)
        for ticker in ("LEFT", "RIGHT")
    ])
    db.commit()
    monkeypatch.setattr(portfolio_review, "get_holding_intelligence", lambda *_args: {})
    monkeypatch.setattr(portfolio_review, "intelligence_to_dict", lambda value: value)
    result = portfolio_review.compare_watchlist(
        db, 1, ["LEFT", "RIGHT"], quote_loader=lambda ticker: {
            "ticker": ticker, "quote_type": "EQUITY", "current_price": 70,
            "fifty_two_week_high": 90, "fifty_two_week_low": 50, "currency": currency,
        },
    )
    assert [item["currency"] for item in result["items"]] == [currency, currency]
    assert all(item["current_price"] == 70 for item in result["items"])


@pytest.mark.parametrize("sale_count", [0, 100, 101, 1000])
def test_full_period_receipts_and_bundle_retain_portfolio_isolation(db, sale_count):
    today = datetime.now()
    facts = {
        "portfolio_id": 1, "ticker": "SOLD", "shares_sold": 1, "sale_price": 2,
        "avg_cost": 1, "realized_gain": 1, "sale_currency": "USD",
        "sale_price_source": "manual_entry", "created_at": today,
    }
    db.add(Portfolio(id=2, name="Other"))
    db.add_all([RealizedTrade(**facts) for _ in range(sale_count)])
    db.add_all([
        RealizedTrade(**{**facts, "portfolio_id": 2, "realized_gain": 99}),
        RealizedTrade(**{**facts, "created_at": today - timedelta(days=100)}),
        RealizedTrade(**{**facts, "sale_currency": "CAD"}),
    ])
    db.commit()
    report = portfolio_review.build_review_report(db, 1, "month", quote_loader=lambda _t: [])
    assert report["period_activity"]["realized_gain"] == sale_count
    assert report["period_activity"]["realized_trade_count"] == sale_count
    assert len(portfolio_valuation.load_performance(db, 1).trades) == min(100, sale_count + 1)
    payload = review_bundle.build_review_bundle(db, 1, "month", quote_loader=lambda _t: [])
    with ZipFile(io.BytesIO(payload)) as archive:
        rows = list(csv.reader(io.StringIO(archive.read("review-pack.csv").decode("utf-8-sig"))))
        assert ["period_activity", "realized_trade_count", str(sale_count)] in rows
        exported_gain = next(
            row[2] for row in rows if row[:2] == ["period_activity", "realized_gain"]
        )
        assert float(exported_gain) == sale_count
        assert "Period realized P&amp;L" in archive.read("review-pack.html").decode()


@pytest.mark.parametrize("quotes,quality,known", [
    ([], "unavailable", 0),
    ([{"ticker": "USD", "current_price": 100, "currency": "USD"}], "partial", 100),
    ([{"ticker": "CAD", "current_price": 50, "currency": "CAD"}], "unavailable", 0),
])
def test_incomplete_bundle_retains_unknown_vs_zero_and_named_exclusions(db, quotes, quality, known):
    db.add_all([
        Holding(portfolio_id=1, ticker="USD", shares=1, avg_cost=90),
        Holding(portfolio_id=1, ticker="CAD", shares=1, avg_cost=40),
        PortfolioSnapshot(
            portfolio_id=1, snapshot_date=(date.today() - timedelta(days=31)).isoformat(),
            total_value=1000, total_cost_basis=900, unrealized_gain=100,
            realized_gain=0, total_return=100,
        ),
    ])
    db.commit()
    payload = review_bundle.build_review_bundle(db, 1, "month", quote_loader=lambda _t: quotes)
    with ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["data_quality"]["review_valuation"] == quality
        rows = list(csv.reader(io.StringIO(archive.read("review-pack.csv").decode("utf-8-sig"))))
        assert ["current", "total_value", ""] in rows
        assert ["current", "known_value", str(float(known))] in rows
        assert ["period_activity", "value_change", ""] in rows
        text = archive.read("review-pack.html").decode()
        assert "Current value<b>Unavailable" in text
        assert "$Unavailable" not in text
        if quotes and quotes[0]["ticker"] == "CAD":
            assert manifest["foreign_currency_tickers"] == ["CAD"]
    assert db.query(PortfolioSnapshot).count() == 1


def _ledger(db, amount=1e308, price=0.1):
    today = date(2026, 6, 12)
    ledger = DcaLedger(
        db, today=lambda: today,
        ticker_validator=lambda _ticker: {
            "valid": True, "quote": {"source_currency": "USD"},
        },
        price_history_loader=lambda *_args: {today.isoformat(): price},
    )
    return ledger, {
        "portfolio_id": 1, "ticker": "BIG", "amount": amount, "frequency": "daily",
        "start_date": today.isoformat(),
    }


def _null_overflow_sum(db):
    """Model SQLite versions that return NULL rather than infinity on SUM overflow."""
    class NullOverflowSum:
        def __init__(self):
            self.total = 0.0

        def step(self, value):
            if value is not None:
                self.total += value

        def finalize(self):
            return self.total if math.isfinite(self.total) else None

    connection = db.connection().connection.driver_connection
    connection.create_aggregate("sum", 1, NullOverflowSum)
    assert connection.execute(
        "SELECT sum(value), coalesce(sum(value), 0) "
        "FROM (SELECT 1e308 value UNION ALL SELECT 1e308)"
    ).fetchone() == (None, 0)


def test_dca_create_refuses_finite_division_overflow_before_any_write(db):
    ledger, arguments = _ledger(db)
    with pytest.raises(DcaConflictError, match="finite"):
        ledger.create_plan(**arguments)
    assert db.query(DcaPlan).count() == 0
    assert db.query(DcaContribution).count() == 0
    assert db.query(Holding).count() == 0


def test_dca_http_overflow_returns_actionable_400_without_writes(db, api_client, monkeypatch):
    today = date.today().isoformat()
    monkeypatch.setattr(dca_router, "validate_ticker_symbol", lambda _ticker: {
        "valid": True, "quote": {"source_currency": "USD"},
    })
    monkeypatch.setattr(dca_router, "get_daily_closes", lambda *_args: {today: 0.1})
    response = api_client(dca_router.router).post("/api/dca/plans?portfolio_id=1", json={
        "ticker": "BIG", "amount": 1e308, "frequency": "daily", "start_date": today,
    })
    assert response.status_code == 400
    assert "finite" in response.json()["detail"]
    assert db.query(DcaPlan).count() == 0
    assert db.query(DcaContribution).count() == 0


def test_dca_apply_refuses_aggregate_basis_overflow_without_mutation(db):
    ledger, arguments = _ledger(db, amount=1e308, price=1e308)
    ledger.create_plan(**arguments)
    db.add(Holding(portfolio_id=1, ticker="OTHER", shares=1, avg_cost=1e308))
    db.commit()
    contribution = db.query(DcaContribution).one()
    with pytest.raises(DcaConflictError, match="finite"):
        ledger.apply_contribution(contribution.id, portfolio_id=1)
    assert db.query(Holding).count() == 1
    assert db.query(Holding).one().ticker == "OTHER"
    assert db.get(DcaContribution, contribution.id).status == "pending"
    assert db.get(DcaContribution, contribution.id).applied_holding_id is None
    assert db.query(PortfolioSnapshot).count() == 0


def test_dca_catchup_aggregate_overflow_rolls_back_new_contributions(db):
    ledger, arguments = _ledger(db, amount=1e308, price=1e308)
    ledger.create_plan(**arguments)
    tomorrow = date.fromisoformat(arguments["start_date"]) + timedelta(days=1)
    catchup = DcaLedger(
        db, today=lambda: tomorrow,
        price_history_loader=lambda *_args: {tomorrow.isoformat(): 1e308},
    )
    with pytest.raises(DcaConflictError, match="finite"):
        catchup.run_catchup(1)
    assert db.query(DcaPlan).count() == 1
    assert db.query(DcaContribution).count() == 1
    assert db.query(Holding).count() == 0


def test_dca_catchup_null_overflow_rolls_back_new_contributions(db):
    _null_overflow_sum(db)
    test_dca_catchup_aggregate_overflow_rolls_back_new_contributions(db)


def test_existing_dca_null_overflow_does_not_become_zero_in_summary(db):
    _null_overflow_sum(db)
    ledger, arguments = _ledger(db, amount=1e308, price=1e308)
    ledger.create_plan(**arguments)
    first = db.query(DcaContribution).one()
    db.add(DcaContribution(
        plan_id=first.plan_id, scheduled_date="2026-06-13", exec_date="2026-06-13",
        amount=1e308, price=1e308, shares=1, status="pending", price_currency="USD",
        price_currency_source="validated_plan",
    ))
    db.commit()
    with pytest.raises(DcaConflictError, match="finite"):
        ledger.list_plans(1)
    assert db.query(DcaContribution).count() == 2


def test_realized_null_overflow_is_not_reported_as_zero_and_empty_stays_zero(db):
    _null_overflow_sum(db)
    assert portfolio_valuation.load_performance(db, 1).realized_gain == 0
    db.add_all([
        RealizedTrade(
            portfolio_id=1, ticker=ticker, shares_sold=1, sale_price=1.5e308,
            avg_cost=5e307, realized_gain=1e308, sale_currency="USD",
            sale_price_source="manual_entry",
        )
        for ticker in ("LEFT", "RIGHT")
    ])
    db.commit()
    with pytest.raises(portfolio_valuation.FinancialArithmeticError, match="finite"):
        portfolio_valuation.load_performance(db, 1)
    assert db.query(RealizedTrade).count() == 2
    assert db.query(PortfolioSnapshot).count() == 0


def test_dca_bulk_apply_overflow_rolls_back_earlier_safe_apply(db):
    ledger, arguments = _ledger(db, amount=5e307, price=5e307)
    plan_id = ledger.create_plan(**arguments)["plan"]["id"]
    second_date = date.fromisoformat(arguments["start_date"]) + timedelta(days=1)
    db.add(DcaContribution(
        plan_id=plan_id, scheduled_date=second_date.isoformat(), exec_date=second_date.isoformat(),
        amount=5e307, shares=1, price=5e307, price_currency="USD",
        price_currency_source="validated_plan", status="pending",
    ))
    db.add(Holding(portfolio_id=1, ticker="OTHER", shares=1, avg_cost=1e308))
    db.commit()
    ids = [row.id for row in db.query(DcaContribution).all()]
    with pytest.raises(DcaConflictError, match="finite"):
        ledger.apply_all_pending(plan_id, portfolio_id=1, contribution_ids=ids)
    assert db.query(Holding).count() == 1
    assert all(row.status == "pending" and row.applied_holding_id is None
               for row in db.query(DcaContribution).all())
    assert db.query(PortfolioSnapshot).count() == 0


def test_dca_existing_nonfinite_contribution_returns_domain_error(db, api_client):
    ledger, arguments = _ledger(db, amount=50, price=100)
    ledger.create_plan(**arguments)
    row = db.query(DcaContribution).one()
    row.shares = float("inf")
    db.commit()
    with pytest.raises(DcaConflictError, match="finite"):
        ledger.list_contributions(1)
    response = api_client(dca_router.router).get("/api/dca/contributions?portfolio_id=1")
    assert response.status_code == 400
    assert "finite" in response.json()["detail"]


@pytest.mark.parametrize("operation,args", [
    (dca_service.apply_to_holding, (1e308, 1, 1e308, 1)),
    (dca_service.apply_to_holding, (1e308, 1e308, 1, 1)),
    (dca_service.undo_from_holding, (1e308, 1e308, 1, 1)),
])
def test_dca_pure_arithmetic_refuses_overflow(operation, args):
    with pytest.raises(ValueError, match="finite"):
        operation(*args)


@pytest.mark.parametrize("precondition", [
    {"expected_shares": 9}, {"expected_avg_cost": 99},
])
def test_stale_edit_precondition_rejects_before_sale_or_mutation(db, api_client, precondition):
    db.add(Holding(id=1, portfolio_id=1, ticker="TEST", shares=10, avg_cost=100))
    db.commit()
    response = api_client(portfolio_router.router).put("/api/portfolio/holdings/1", json={
        "shares": 8, "avg_cost": 120, "sale_price": 150, "notes": "Must not save",
        **precondition,
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "holding_changed"
    holding = db.get(Holding, 1)
    assert (holding.shares, holding.avg_cost, holding.notes) == (10, 100, None)
    assert db.query(RealizedTrade).count() == 0
    assert db.query(PortfolioSnapshot).count() == 0


@pytest.mark.parametrize("first,second", [(110, 120), (120, 110)])
def test_guarded_cost_edits_cannot_overwrite_changed_state_in_either_arrival_order(
    db, api_client, first, second
):
    db.add(Holding(id=1, portfolio_id=1, ticker="TEST", shares=10, avg_cost=100))
    db.commit()
    client = api_client(portfolio_router.router)
    baseline = {"expected_shares": 10, "expected_avg_cost": 100}
    assert client.put("/api/portfolio/holdings/1", json={
        **baseline, "avg_cost": first,
    }).status_code == 200
    late = client.put("/api/portfolio/holdings/1", json={**baseline, "avg_cost": second})
    assert late.status_code == 409
    assert late.json()["detail"]["code"] == "holding_changed"
    assert db.get(Holding, 1).avg_cost == first
    assert db.query(RealizedTrade).count() == 0


def test_matching_preconditions_and_legacy_omission_keep_existing_edit_behavior(db, api_client):
    db.add(Holding(id=1, portfolio_id=1, ticker="TEST", shares=10, avg_cost=3.125))
    db.commit()
    client = api_client(portfolio_router.router)
    exact = client.put("/api/portfolio/holdings/1", json={
        "expected_shares": 10, "expected_avg_cost": 3.125, "avg_cost": 4.125,
    })
    assert exact.status_code == 200
    legacy = client.put("/api/portfolio/holdings/1", json={"avg_cost": 5.125})
    assert legacy.status_code == 200
    assert db.get(Holding, 1).avg_cost == 5.125


def test_zero_research_baselines_keep_guarded_state_only_archive_and_restore(db, api_client):
    db.add(Holding(id=1, portfolio_id=1, ticker="IDEA", shares=0, avg_cost=0, is_watchlist=True))
    db.commit()
    client = api_client(portfolio_router.router)
    for active in (False, True):
        result = client.put("/api/portfolio/holdings/1", json={
            "is_active": active, "expected_shares": 0, "expected_avg_cost": 0,
        })
        assert result.status_code == 200
        assert db.get(Holding, 1).is_active is active
    assert db.query(RealizedTrade).count() == 0


@pytest.mark.parametrize("field", ["expected_shares", "expected_avg_cost"])
@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1])
def test_edit_preconditions_require_finite_nonnegative_facts(field, value):
    from pydantic import ValidationError
    from app.schemas import HoldingUpdate

    with pytest.raises(ValidationError):
        HoldingUpdate(**{field: value})


def _removal_payload(**overrides):
    return {
        "sale_price": 150, "sale_currency": "USD", "sale_price_source": "manual_entry",
        **overrides,
    }


def test_late_put_before_guarded_removal_rejects_sale_against_stale_consent(db, api_client):
    db.add(Holding(id=1, portfolio_id=1, ticker="TEST", shares=10, avg_cost=100))
    db.commit()
    client = api_client(portfolio_router.router)
    baseline = {"expected_shares": 10, "expected_avg_cost": 100}
    late_put = client.put("/api/portfolio/holdings/1", json={**baseline, "shares": 12})
    assert late_put.status_code == 200
    removal = client.request(
        "DELETE", "/api/portfolio/holdings/1", json=_removal_payload(**baseline),
    )
    assert removal.status_code == 409
    assert removal.json()["detail"]["code"] == "holding_changed"
    holding = db.get(Holding, 1)
    assert (holding.shares, holding.avg_cost, holding.is_active) == (12, 100, True)
    assert db.query(RealizedTrade).count() == 0


def test_guarded_removal_before_late_put_preserves_sale_and_archived_position(db, api_client):
    db.add(Holding(id=1, portfolio_id=1, ticker="TEST", shares=10, avg_cost=100))
    db.commit()
    client = api_client(portfolio_router.router)
    baseline = {"expected_shares": 10, "expected_avg_cost": 100}
    removal = client.request(
        "DELETE", "/api/portfolio/holdings/1", json=_removal_payload(**baseline),
    )
    assert removal.status_code == 200
    late_put = client.put("/api/portfolio/holdings/1", json={**baseline, "shares": 12})
    assert late_put.status_code == 409
    assert late_put.json()["detail"]["code"] == "holding_archived"
    holding = db.get(Holding, 1)
    assert (holding.shares, holding.avg_cost, holding.is_active) == (10, 100, False)
    assert db.query(RealizedTrade).count() == 1
    assert db.query(RealizedTrade).one().shares_sold == 10


def test_stale_exact_basis_removal_has_no_financial_side_effect(db, api_client):
    db.add(Holding(id=1, portfolio_id=1, ticker="TEST", shares=10, avg_cost=3.125))
    db.commit()
    result = api_client(portfolio_router.router).request(
        "DELETE", "/api/portfolio/holdings/1", json=_removal_payload(
            expected_shares=10, expected_avg_cost=3.12,
        ),
    )
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "holding_changed"
    assert db.get(Holding, 1).is_active is True
    assert db.get(Holding, 1).avg_cost == 3.125
    assert db.query(RealizedTrade).count() == 0
    assert db.query(PortfolioSnapshot).count() == 0


@pytest.mark.parametrize("guarded", [True, False])
def test_matching_or_omitted_removal_guards_preserve_sale_behavior(db, api_client, guarded):
    db.add(Holding(id=1, portfolio_id=1, ticker="TEST", shares=10, avg_cost=3.125))
    db.commit()
    baseline = {"expected_shares": 10, "expected_avg_cost": 3.125} if guarded else {}
    response = api_client(portfolio_router.router).request(
        "DELETE", "/api/portfolio/holdings/1", json=_removal_payload(**baseline),
    )
    assert response.status_code == 200
    assert db.get(Holding, 1).is_active is False
    assert db.query(RealizedTrade).count() == 1
    trade = db.query(RealizedTrade).one()
    assert trade.shares_sold == 10
    assert trade.avg_cost == round(3.125, 2)  # Existing sale storage policy is unchanged.


@pytest.mark.parametrize("field", ["expected_shares", "expected_avg_cost"])
@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1])
def test_removal_preconditions_require_finite_nonnegative_facts(field, value):
    from pydantic import ValidationError
    from app.schemas import HoldingRemoval

    with pytest.raises(ValidationError):
        HoldingRemoval(**{field: value})
