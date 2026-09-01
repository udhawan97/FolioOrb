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


def test_ledger_catchup_apply_and_undo_are_traceable_and_idempotent():
    db = make_db()
    ledger = DcaLedger(
        db,
        ticker_validator=lambda ticker: {
            "valid": True,
            "ticker": ticker,
            "suggestions": [],
        },
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
    applied = ledger.apply_contribution(contribution["id"])
    assert applied["holding"]["shares"] == pytest.approx(10.5)
    assert applied["holding"]["avg_cost"] == pytest.approx(2050 / 10.5)

    undone = ledger.undo_contribution(contribution["id"])
    assert undone["contribution"]["status"] == "pending"
    holding = db.query(Holding).filter_by(portfolio_id=1, ticker="VOO").one()
    assert holding.shares == pytest.approx(10)
    assert holding.avg_cost == pytest.approx(200)
    assert holding.is_active is True


def test_applied_contributions_block_plan_deletion_until_undone():
    db = make_db()
    ledger = DcaLedger(
        db,
        ticker_validator=lambda ticker: {"valid": True, "ticker": ticker, "suggestions": []},
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
    ledger.apply_contribution(contribution_id)

    with pytest.raises(DcaConflictError, match="Undo applied buys"):
        ledger.delete_plan(created["plan"]["id"])

    assert ledger.list_contributions(1, "applied")[0]["id"] == contribution_id
    ledger.undo_contribution(contribution_id)
    assert "deleted" in ledger.delete_plan(created["plan"]["id"])


def test_foreign_currency_plan_is_rejected_before_any_persistence():
    db = make_db()

    def prices_must_not_load(*_args):
        raise AssertionError("foreign DCA must stop before contribution pricing")

    ledger = DcaLedger(
        db,
        ticker_validator=lambda ticker: {
            "valid": True,
            "ticker": ticker,
            "quote": {"currency": "GBp"},
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


def test_explicit_usd_plan_preserves_domestic_creation_behavior():
    db = make_db()
    ledger = DcaLedger(
        db,
        ticker_validator=lambda ticker: {
            "valid": True,
            "ticker": ticker,
            "quote": {"currency": "USD"},
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
    assert db.query(DcaPlan).count() == 1
    assert db.query(DcaContribution).count() == 1


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
    ledger.apply_contribution(contribution_id)
    contribution = db.get(DcaContribution, contribution_id)
    holding = db.get(Holding, contribution.applied_holding_id)
    holding.shares = 0.25
    holding.avg_cost = 100.0
    db.commit()
    before_summary = ledger.list_plans(1)[0]
    holding_id = holding.id

    with pytest.raises(DcaConflictError, match="left unchanged"):
        ledger.undo_contribution(contribution_id)

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
        ledger.apply_contribution(contribution["id"])
    applied = db.query(DcaContribution).filter_by(plan_id=plan_id).all()
    holding = db.get(Holding, applied[0].applied_holding_id)
    holding.shares = 0.75
    holding.avg_cost = 100.0
    db.commit()
    before_summary = ledger.list_plans(1)[0]

    with pytest.raises(DcaConflictError, match="left unchanged"):
        ledger.undo_all_applied(plan_id)

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
        ticker_validator=lambda ticker: {
            "valid": True,
            "ticker": ticker,
            "suggestions": [],
        },
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

    result = ledger.apply_contribution(contribution["id"])

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
        ticker_validator=lambda ticker: {
            "valid": True,
            "ticker": ticker,
            "suggestions": [],
        },
        price_history_loader=loader,
        today=lambda: today,
    )


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
