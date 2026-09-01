"""Interface tests for the DCA plan ledger module."""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, DcaContribution, DcaPlan, Holding, Portfolio
from app.services.dca_ledger import (
    DcaConflictError,
    DcaLedger,
    DcaValidationError,
)


TODAY = date(2026, 6, 12)


def make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    db.add(Portfolio(id=1, name="Test"))
    db.add(
        Holding(
            portfolio_id=1,
            ticker="VOO",
            shares=10,
            avg_cost=200,
            is_active=True,
            is_watchlist=False,
        )
    )
    db.commit()
    return db


def closes(_ticker: str, start: str, end: str) -> dict[str, float]:
    rows = {}
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while cursor <= stop:
        if cursor.weekday() < 5:
            rows[cursor.isoformat()] = 100.0
        cursor += timedelta(days=1)
    return rows


def usd_validation(ticker: str) -> dict:
    return {
        "valid": True,
        "ticker": ticker,
        "quote": {"currency": "USD", "source_currency": "USD"},
        "suggestions": [],
    }


def test_ledger_catchup_apply_and_undo_are_traceable_and_idempotent():
    db = make_db()
    ledger = DcaLedger(
        db,
        ticker_validator=usd_validation,
        price_history_loader=closes,
        today=lambda: TODAY,
    )

    created = ledger.create_plan(
        portfolio_id=1,
        ticker="VOO",
        amount=50,
        frequency="weekly",
        start_date="2026-06-05",
    )
    assert created["buys_added"] == 2
    assert ledger.run_catchup(1)["buys_added"] == 0

    contribution = ledger.list_contributions(1)[0]
    applied = ledger.apply_contribution(contribution["id"], portfolio_id=1)
    assert applied["holding"]["shares"] == pytest.approx(10.5)
    assert applied["holding"]["avg_cost"] == pytest.approx(2050 / 10.5)

    undone = ledger.undo_contribution(contribution["id"], portfolio_id=1)
    assert undone["contribution"]["status"] == "pending"
    holding = db.query(Holding).filter_by(portfolio_id=1, ticker="VOO").one()
    assert holding.shares == pytest.approx(10)
    assert holding.avg_cost == pytest.approx(200)
    assert holding.is_active is True


def test_applied_contributions_block_plan_deletion_until_undone():
    db = make_db()
    ledger = DcaLedger(
        db,
        ticker_validator=usd_validation,
        price_history_loader=closes,
        today=lambda: TODAY,
    )
    created = ledger.create_plan(
        portfolio_id=1,
        ticker="VOO",
        amount=50,
        frequency="weekly",
        start_date=TODAY.isoformat(),
    )
    contribution_id = ledger.list_contributions(1)[0]["id"]
    ledger.apply_contribution(contribution_id, portfolio_id=1)

    with pytest.raises(DcaConflictError, match="Undo applied buys"):
        ledger.delete_plan(created["plan"]["id"], portfolio_id=1)

    assert ledger.list_contributions(1, "applied")[0]["id"] == contribution_id
    ledger.undo_contribution(contribution_id, portfolio_id=1)
    assert "deleted" in ledger.delete_plan(
        created["plan"]["id"], portfolio_id=1
    )


def test_foreign_currency_plan_is_rejected_before_any_persistence():
    db = make_db()

    def prices_must_not_load(*_args):
        raise AssertionError("foreign DCA must stop before contribution pricing")

    ledger = DcaLedger(
        db,
        ticker_validator=lambda ticker: {
            "valid": True,
            "ticker": ticker,
            "quote": {"currency": "GBp", "source_currency": "GBp"},
            "suggestions": [],
        },
        price_history_loader=prices_must_not_load,
        today=lambda: TODAY,
    )

    with pytest.raises(DcaValidationError, match="USD quotes only"):
        ledger.create_plan(
            portfolio_id=1,
            ticker="VOD.L",
            amount=50,
            frequency="weekly",
            start_date=TODAY.isoformat(),
        )

    assert db.query(DcaPlan).count() == 0
    assert db.query(DcaContribution).count() == 0


def test_missing_source_currency_is_rejected_before_any_persistence():
    db = make_db()

    def prices_must_not_load(*_args):
        raise AssertionError("ambiguous DCA must stop before contribution pricing")

    ledger = DcaLedger(
        db,
        ticker_validator=lambda ticker: {
            "valid": True,
            "ticker": ticker,
            # The display boundary may retain USD, but the provider supplied no
            # currency. DCA must use the source fact and fail closed.
            "quote": {"currency": "USD", "source_currency": None},
            "suggestions": [],
        },
        price_history_loader=prices_must_not_load,
        today=lambda: TODAY,
    )

    with pytest.raises(DcaValidationError, match="missing currency"):
        ledger.create_plan(
            portfolio_id=1,
            ticker="UNKNOWN",
            amount=50,
            frequency="weekly",
            start_date=TODAY.isoformat(),
        )

    assert db.query(DcaPlan).count() == 0
    assert db.query(DcaContribution).count() == 0


def test_explicit_usd_plan_preserves_domestic_creation_behavior():
    db = make_db()
    ledger = DcaLedger(
        db,
        ticker_validator=lambda ticker: {
            "valid": True,
            "ticker": ticker,
            "quote": {"currency": "USD", "source_currency": "USD"},
            "suggestions": [],
        },
        price_history_loader=closes,
        today=lambda: TODAY,
    )

    result = ledger.create_plan(
        portfolio_id=1,
        ticker="VOO",
        amount=50,
        frequency="weekly",
        start_date=TODAY.isoformat(),
    )

    assert result["buys_added"] == 1
    plan = db.query(DcaPlan).one()
    contribution = db.query(DcaContribution).one()
    assert (plan.quote_currency, plan.quote_currency_source) == (
        "USD", "ticker_validation"
    )
    assert (contribution.price_currency, contribution.price_currency_source) == (
        "USD", "validated_plan"
    )


def test_unsafe_undo_preserves_holding_contribution_link_and_totals():
    db = make_db()
    db.delete(db.query(Holding).one())
    db.commit()
    ledger = _ledger_for(db, closes)
    ledger.create_plan(
        portfolio_id=1, ticker="VOO", amount=50, frequency="weekly",
        start_date=TODAY.isoformat(),
    )
    contribution_id = ledger.list_contributions(1)[0]["id"]
    ledger.apply_contribution(contribution_id, portfolio_id=1)
    contribution = db.get(DcaContribution, contribution_id)
    holding = db.get(Holding, contribution.applied_holding_id)
    holding.shares = 0.25
    holding.avg_cost = 100.0
    db.commit()
    before_summary = ledger.list_plans(1)[0]
    holding_id = holding.id

    with pytest.raises(DcaConflictError, match="left unchanged"):
        ledger.undo_contribution(contribution_id, portfolio_id=1)

    db.refresh(holding)
    db.refresh(contribution)
    assert (holding.shares, holding.avg_cost, holding.is_active) == (0.25, 100.0, True)
    assert contribution.status == "applied"
    assert contribution.applied_holding_id == holding_id
    assert ledger.list_plans(1)[0] == before_summary


def test_bulk_unsafe_undo_rolls_back_earlier_staged_reversals():
    db = make_db()
    db.delete(db.query(Holding).one())
    db.commit()
    ledger = _ledger_for(db, closes)
    plan_id = ledger.create_plan(
        portfolio_id=1, ticker="VOO", amount=50, frequency="weekly",
        start_date="2026-06-05",
    )["plan"]["id"]
    pending = ledger.list_contributions(plan_id)
    for contribution in pending:
        ledger.apply_contribution(contribution["id"], portfolio_id=1)
    applied = db.query(DcaContribution).filter_by(plan_id=plan_id).all()
    holding = db.get(Holding, applied[0].applied_holding_id)
    holding.shares = 0.75
    holding.avg_cost = 100.0
    db.commit()
    before_summary = ledger.list_plans(1)[0]

    with pytest.raises(DcaConflictError, match="left unchanged"):
        ledger.undo_all_applied(plan_id, portfolio_id=1)

    db.refresh(holding)
    assert (holding.shares, holding.avg_cost, holding.is_active) == (0.75, 100.0, True)
    refreshed = db.query(DcaContribution).filter_by(plan_id=plan_id).all()
    assert {row.status for row in refreshed} == {"applied"}
    assert {row.applied_holding_id for row in refreshed} == {holding.id}
    assert ledger.list_plans(1)[0] == before_summary


def test_apply_reuses_one_legacy_formatted_active_holding():
    db = make_db()
    original = db.query(Holding).filter_by(portfolio_id=1, ticker="VOO").one()
    db.execute(
        text("UPDATE holdings SET ticker = ' voo ' WHERE id = :holding_id"),
        {"holding_id": original.id},
    )
    db.commit()
    ledger = DcaLedger(
        db,
        ticker_validator=usd_validation,
        price_history_loader=closes,
        today=lambda: TODAY,
    )
    ledger.create_plan(
        portfolio_id=1,
        ticker="VOO",
        amount=50,
        frequency="weekly",
        start_date=TODAY.isoformat(),
    )
    contribution = ledger.list_contributions(1)[0]

    result = ledger.apply_contribution(contribution["id"], portfolio_id=1)

    holdings = db.query(Holding).filter_by(portfolio_id=1, is_active=True).all()
    assert len(holdings) == 1
    assert holdings[0].id == original.id
    assert holdings[0].shares == pytest.approx(10.5)
    assert result["contribution"]["status"] == "applied"


# ── Catch-up cost ─────────────────────────────────────────────────────────────
#
# The dashboard fires POST /api/dca/run on every page load, and the steady state
# is that nothing is due. Pricing that non-event meant refetching the plan's
# whole start_date..today window each time — years of daily bars, per plan.

def _counting_loader():
    """Wrap the stub close loader so a test can see whether it was called."""
    calls: list[tuple[str, str, str]] = []

    def load(ticker: str, start: str, end: str) -> dict[str, float]:
        calls.append((ticker, start, end))
        return closes(ticker, start, end)

    return load, calls


def _ledger_for(db, loader, today=TODAY):
    return DcaLedger(
        db,
        ticker_validator=usd_validation,
        price_history_loader=loader,
        today=lambda: today,
    )


@pytest.mark.parametrize(
    ("currency", "source"),
    [(None, "legacy_unknown"), ("GBp", "ticker_validation")],
    ids=["legacy-ambiguous", "foreign"],
)
def test_single_apply_blocks_untrusted_pending_rows_without_mutation(currency, source):
    db = make_db()
    plan = DcaPlan(
        portfolio_id=1, ticker="VOO", amount=50, frequency="weekly",
        start_date=TODAY.isoformat(), quote_currency=currency,
        quote_currency_source=source,
    )
    db.add(plan)
    db.flush()
    contribution = DcaContribution(
        plan_id=plan.id, scheduled_date=TODAY.isoformat(),
        exec_date=TODAY.isoformat(), price=100, shares=0.5, amount=50,
        price_currency=currency,
        price_currency_source=("legacy_unknown" if currency is None else "validated_plan"),
    )
    db.add(contribution)
    db.commit()
    holding = db.query(Holding).filter_by(portfolio_id=1, ticker="VOO").one()
    before = (holding.shares, holding.avg_cost, holding.is_active)

    with pytest.raises(DcaConflictError, match="left unchanged|No contributions"):
        DcaLedger(db).apply_contribution(contribution.id, portfolio_id=1)

    db.refresh(holding)
    db.refresh(contribution)
    assert (holding.shares, holding.avg_cost, holding.is_active) == before
    assert contribution.status == "pending"
    assert contribution.applied_holding_id is None


def test_bulk_apply_preflights_every_currency_fact_before_holding_mutation():
    db = make_db()
    plan = DcaPlan(
        portfolio_id=1, ticker="VOO", amount=50, frequency="weekly",
        start_date="2026-06-05", quote_currency="USD",
        quote_currency_source="ticker_validation",
    )
    db.add(plan)
    db.flush()
    good = DcaContribution(
        plan_id=plan.id, scheduled_date="2026-06-05", exec_date="2026-06-05",
        price=100, shares=0.5, amount=50, price_currency="USD",
        price_currency_source="validated_plan",
    )
    ambiguous = DcaContribution(
        plan_id=plan.id, scheduled_date=TODAY.isoformat(),
        exec_date=TODAY.isoformat(), price=100, shares=0.5, amount=50,
        price_currency=None, price_currency_source="legacy_unknown",
    )
    db.add_all([good, ambiguous])
    db.commit()
    holding = db.query(Holding).filter_by(portfolio_id=1, ticker="VOO").one()
    before = (holding.shares, holding.avg_cost, holding.is_active)

    with pytest.raises(DcaConflictError, match="left unchanged"):
        DcaLedger(db).apply_all_pending(plan.id, portfolio_id=1)

    db.refresh(holding)
    assert (holding.shares, holding.avg_cost, holding.is_active) == before
    assert {row.status for row in db.query(DcaContribution).all()} == {"pending"}
    assert all(row.applied_holding_id is None for row in db.query(DcaContribution).all())


def test_ambiguous_plan_does_not_block_trusted_plan_catchup():
    db = make_db()
    ambiguous = DcaPlan(
        portfolio_id=1, ticker="LEGACY", amount=50, frequency="weekly",
        start_date=TODAY.isoformat(), quote_currency=None,
        quote_currency_source="legacy_unknown",
    )
    trusted = DcaPlan(
        portfolio_id=1, ticker="VOO", amount=50, frequency="weekly",
        start_date=TODAY.isoformat(), quote_currency="USD",
        quote_currency_source="ticker_validation",
    )
    # Insert the ambiguous row first to prove catch-up does not rely on a trusted
    # plan happening to precede it in query order.
    db.add_all([ambiguous, trusted])
    db.commit()
    loaded = []

    def load_prices(ticker, start, end):
        loaded.append(ticker)
        return closes(ticker, start, end)

    result = DcaLedger(
        db, price_history_loader=load_prices, today=lambda: TODAY
    ).run_catchup(1)

    assert result["buys_added"] == 1
    assert result["plans_checked"] == 2
    assert result["plans_blocked"] == 1
    by_ticker = {row["ticker"]: row for row in result["plans"]}
    assert by_ticker["LEGACY"] == {
        "plan_id": ambiguous.id,
        "ticker": "LEGACY",
        "buys_added": 0,
        "price_data": None,
        "status": "needs_currency",
        "message": (
            "This DCA plan has no explicit trusted USD currency provenance. "
            "No contributions or holdings were changed; recreate it after "
            "FolioOrb verifies an explicit USD quote."
        ),
    }
    assert by_ticker["VOO"]["status"] == "ready"
    assert by_ticker["VOO"]["buys_added"] == 1
    assert loaded == ["VOO"]
    assert [row.plan_id for row in db.query(DcaContribution).all()] == [trusted.id]

    summary = {row["ticker"]: row for row in DcaLedger(db).list_plans(1)}["LEGACY"]
    assert summary["is_active"] is True
    assert summary["currency_status"] == "needs_currency"
    assert summary["next_date"] is None
    assert "Undo applied buys if needed, then delete this plan" in summary["currency_message"]
    assert "only after FolioOrb verifies an explicit USD quote" in summary["currency_message"]


@pytest.mark.parametrize(
    ("currency", "source"),
    [(None, "legacy_unknown"), ("GBp", "ticker_validation")],
    ids=["legacy-ambiguous", "foreign"],
)
def test_catchup_blocks_untrusted_plan_without_prices_or_rows(currency, source):
    db = make_db()
    db.add(
        DcaPlan(
            portfolio_id=1, ticker="BAD", amount=50, frequency="weekly",
            start_date=TODAY.isoformat(), quote_currency=currency,
            quote_currency_source=source,
        )
    )
    db.commit()

    def prices_must_not_load(*_args):
        raise AssertionError("blocked plan must not read prices")

    result = DcaLedger(
        db, price_history_loader=prices_must_not_load, today=lambda: TODAY
    ).run_catchup(1)

    assert result["buys_added"] == 0
    assert result["plans_blocked"] == 1
    assert result["plans"][0]["status"] == "needs_currency"
    assert db.query(DcaContribution).count() == 0


def test_catchup_skips_the_price_fetch_when_every_buy_is_already_booked():
    db = make_db()
    loader, calls = _counting_loader()
    ledger = _ledger_for(db, loader)
    ledger.create_plan(
        portfolio_id=1, ticker="VOO", amount=50, frequency="weekly",
        start_date="2026-06-05",
    )
    assert calls, "the initial backfill genuinely needs prices"
    calls.clear()

    assert ledger.run_catchup(1)["buys_added"] == 0
    assert not calls, "nothing was due, so no history should have been fetched"


def test_catchup_still_fetches_once_a_buy_comes_due():
    db = make_db()
    loader, calls = _counting_loader()
    ledger = _ledger_for(db, loader)
    ledger.create_plan(
        portfolio_id=1, ticker="VOO", amount=50, frequency="weekly",
        start_date="2026-06-05",
    )
    calls.clear()

    # A week later the next weekly buy is due, so the skip must not apply.
    later = _ledger_for(db, loader, today=TODAY + timedelta(days=7))
    assert later.run_catchup(1)["buys_added"] == 1
    assert calls, "a due buy has to be priced"


def test_catchup_still_fetches_for_daily_plans():
    # A daily schedule *is* the trading calendar, so whether a buy is due can't
    # be answered without market data. Those plans keep paying for the fetch.
    db = make_db()
    loader, calls = _counting_loader()
    ledger = _ledger_for(db, loader)
    ledger.create_plan(
        portfolio_id=1, ticker="VOO", amount=50, frequency="daily",
        start_date="2026-06-08",
    )
    calls.clear()

    ledger.run_catchup(1)
    assert calls, "daily plans need the calendar to know what is due"
