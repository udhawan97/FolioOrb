# pylint: disable=protected-access
"""Concurrent financial requests must serialize before reading mutable facts."""

from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    DcaContribution,
    DcaPlan,
    Holding,
    Portfolio,
    RealizedTrade,
)
from app.routers import portfolio as portfolio_router
from app.schemas import HoldingRemoval, HoldingUpdate
from app.services import realized_sales
from app.services.dca_ledger import DcaConflictError, DcaLedger


@pytest.fixture(name="session_factory")
def _session_factory(tmp_path):
    """Return independent production-shaped sessions over one WAL database."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'financial-race.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    seed = factory()
    seed.add(Portfolio(id=1, name="Concurrent Test"))
    seed.commit()
    seed.close()
    yield factory
    engine.dispose()


def _seed_contribution(session_factory, *, status: str):
    db = session_factory()
    holding = Holding(
        portfolio_id=1,
        ticker="VOO",
        shares=10.5 if status == "applied" else 10,
        avg_cost=(2050 / 10.5) if status == "applied" else 200,
        is_active=True,
        is_watchlist=False,
    )
    plan = DcaPlan(
        portfolio_id=1,
        ticker="VOO",
        amount=50,
        frequency="weekly",
        start_date="2026-06-12",
        quote_currency="USD",
        quote_currency_source="ticker_validation",
    )
    db.add_all([holding, plan])
    db.flush()
    contribution = DcaContribution(
        plan_id=plan.id,
        scheduled_date="2026-06-12",
        exec_date="2026-06-12",
        price=100,
        shares=0.5,
        amount=50,
        price_currency="USD",
        price_currency_source="validated_plan",
        status=status,
        applied_holding_id=holding.id if status == "applied" else None,
    )
    db.add(contribution)
    db.commit()
    result = (plan.id, contribution.id, holding.id)
    db.close()
    return result


def _pause_bulk_preflight(ledger, locked, release):
    original = ledger._bulk_contributions

    def paused(*args, **kwargs):
        rows = original(*args, **kwargs)
        locked.set()
        assert release.wait(5), "timed out waiting to release financial writer"
        return rows

    ledger._bulk_contributions = paused


def test_bulk_apply_and_single_skip_cannot_overwrite_each_other(session_factory):
    plan_id, contribution_id, holding_id = _seed_contribution(
        session_factory, status="pending"
    )
    session_a = session_factory()
    session_b = session_factory()
    ledger_a = DcaLedger(session_a)
    ledger_b = DcaLedger(session_b)
    writer_locked = threading.Event()
    release_writer = threading.Event()
    second_finished = threading.Event()
    _pause_bulk_preflight(ledger_a, writer_locked, release_writer)

    def skip_in_second_session():
        try:
            return ledger_b.skip_contribution(contribution_id, portfolio_id=1)
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        apply_future = pool.submit(
            ledger_a.apply_all_pending,
            plan_id,
            portfolio_id=1,
            contribution_ids=[contribution_id],
        )
        assert writer_locked.wait(5)
        skip_future = pool.submit(skip_in_second_session)
        assert not second_finished.wait(0.2)
        release_writer.set()
        assert apply_future.result(timeout=5)["applied"] == 1
        with pytest.raises(DcaConflictError, match="already applied"):
            skip_future.result(timeout=5)

    check = session_factory()
    contribution = check.get(DcaContribution, contribution_id)
    holding = check.get(Holding, holding_id)
    assert contribution.status == "applied"
    assert contribution.applied_holding_id == holding_id
    assert holding.shares == pytest.approx(10.5)
    check.close()
    session_a.close()
    session_b.close()


def test_bulk_apply_and_plan_delete_cannot_erase_contribution_trace(
    session_factory,
):
    plan_id, contribution_id, holding_id = _seed_contribution(
        session_factory, status="pending"
    )
    session_a = session_factory()
    session_b = session_factory()
    ledger_a = DcaLedger(session_a)
    ledger_b = DcaLedger(session_b)
    writer_locked = threading.Event()
    release_writer = threading.Event()
    second_finished = threading.Event()
    _pause_bulk_preflight(ledger_a, writer_locked, release_writer)

    def delete_in_second_session():
        try:
            return ledger_b.delete_plan(plan_id, portfolio_id=1)
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        apply_future = pool.submit(
            ledger_a.apply_all_pending,
            plan_id,
            portfolio_id=1,
            contribution_ids=[contribution_id],
        )
        assert writer_locked.wait(5)
        delete_future = pool.submit(delete_in_second_session)
        assert not second_finished.wait(0.2)
        release_writer.set()
        assert apply_future.result(timeout=5)["applied"] == 1
        with pytest.raises(DcaConflictError, match="Undo applied buys"):
            delete_future.result(timeout=5)

    check = session_factory()
    assert check.get(DcaPlan, plan_id) is not None
    contribution = check.get(DcaContribution, contribution_id)
    assert contribution.status == "applied"
    assert contribution.applied_holding_id == holding_id
    assert check.get(Holding, holding_id).shares == pytest.approx(10.5)
    check.close()
    session_a.close()
    session_b.close()


def test_bulk_and_single_undo_cannot_reverse_one_buy_twice(session_factory):
    plan_id, contribution_id, holding_id = _seed_contribution(
        session_factory, status="applied"
    )
    session_a = session_factory()
    session_b = session_factory()
    ledger_a = DcaLedger(session_a)
    ledger_b = DcaLedger(session_b)
    writer_locked = threading.Event()
    release_writer = threading.Event()
    second_finished = threading.Event()
    _pause_bulk_preflight(ledger_a, writer_locked, release_writer)

    def undo_in_second_session():
        try:
            return ledger_b.undo_contribution(contribution_id, portfolio_id=1)
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        bulk_future = pool.submit(
            ledger_a.undo_all_applied,
            plan_id,
            portfolio_id=1,
            contribution_ids=[contribution_id],
        )
        assert writer_locked.wait(5)
        single_future = pool.submit(undo_in_second_session)
        assert not second_finished.wait(0.2)
        release_writer.set()
        assert bulk_future.result(timeout=5)["undone"] == 1
        with pytest.raises(DcaConflictError, match="Only applied"):
            single_future.result(timeout=5)

    check = session_factory()
    contribution = check.get(DcaContribution, contribution_id)
    holding = check.get(Holding, holding_id)
    assert contribution.status == "pending"
    assert contribution.applied_holding_id is None
    assert holding.shares == pytest.approx(10)
    assert holding.avg_cost == pytest.approx(200)
    check.close()
    session_a.close()
    session_b.close()


def test_update_resuming_after_removal_cannot_sell_archived_shares_again(
    session_factory, monkeypatch
):
    seed = session_factory()
    holding = Holding(
        portfolio_id=1,
        ticker="ACME",
        shares=10,
        avg_cost=100,
        is_active=True,
        is_watchlist=False,
    )
    seed.add(holding)
    seed.commit()
    holding_id = holding.id
    seed.close()

    quote_started = threading.Event()
    release_quote = threading.Event()

    def paused_quote(_ticker):
        quote_started.set()
        assert release_quote.wait(5), "timed out waiting to release quote"
        return {
            "current_price": 125,
            "currency": "USD",
            "source_currency": "USD",
        }

    monkeypatch.setattr(portfolio_router, "get_stock_data", paused_quote)
    update_session = session_factory()
    remove_session = session_factory()

    with ThreadPoolExecutor(max_workers=1) as pool:
        update_future = pool.submit(
            portfolio_router.update_holding,
            holding_id,
            HoldingUpdate(shares=5),
            update_session,
            1,
        )
        assert quote_started.wait(5)
        removed = portfolio_router.remove_holding(
            holding_id,
            db=remove_session,
            portfolio_id=1,
            data=HoldingRemoval(
                sale_price=123.45,
                sale_currency="USD",
                sale_price_source="manual_entry",
                sale_date="2026-01-15",
            ),
        )
        assert removed["ticker"] == "ACME"
        release_quote.set()
        with pytest.raises(HTTPException) as exc_info:
            update_future.result(timeout=5)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "holding_archived"

    check = session_factory()
    archived = check.get(Holding, holding_id)
    trade = check.query(RealizedTrade).one()
    assert archived.is_active is False
    assert archived.shares == pytest.approx(10)
    assert trade.shares_sold == pytest.approx(10)
    check.close()
    update_session.close()
    remove_session.close()


def test_two_removals_cannot_record_the_same_sale_twice(
    session_factory, monkeypatch
):
    seed = session_factory()
    holding = Holding(
        portfolio_id=1,
        ticker="ACME",
        shares=10,
        avg_cost=100,
        is_active=True,
        is_watchlist=False,
    )
    seed.add(holding)
    seed.commit()
    holding_id = holding.id
    seed.close()

    writer_locked = threading.Event()
    release_writer = threading.Event()
    second_finished = threading.Event()
    original = realized_sales.RealizedSaleLedger.stage_reduction

    def paused_first_reduction(self, *args, **kwargs):
        trade = original(self, *args, **kwargs)
        if not writer_locked.is_set():
            writer_locked.set()
            assert release_writer.wait(5), "timed out waiting to release removal"
        return trade

    monkeypatch.setattr(
        realized_sales.RealizedSaleLedger,
        "stage_reduction",
        paused_first_reduction,
    )
    removal = HoldingRemoval(
        sale_price=123.45,
        sale_currency="USD",
        sale_price_source="manual_entry",
        sale_date="2026-01-15",
    )
    session_a = session_factory()
    session_b = session_factory()

    def remove(db):
        return portfolio_router.remove_holding(
            holding_id,
            db=db,
            portfolio_id=1,
            data=removal,
        )

    def remove_in_second_session():
        try:
            return remove(session_b)
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(remove, session_a)
        assert writer_locked.wait(5)
        second_future = pool.submit(remove_in_second_session)
        assert not second_finished.wait(0.2)
        release_writer.set()
        assert first_future.result(timeout=5)["ticker"] == "ACME"
        with pytest.raises(HTTPException) as exc_info:
            second_future.result(timeout=5)
        assert exc_info.value.status_code == 404

    check = session_factory()
    assert check.get(Holding, holding_id).is_active is False
    assert check.query(RealizedTrade).count() == 1
    check.close()
    session_a.close()
    session_b.close()


def test_sold_holding_blocks_dca_undo_without_rewriting_sale_history(
    session_factory,
):
    _, contribution_id, holding_id = _seed_contribution(
        session_factory, status="applied"
    )
    db = session_factory()
    removal = HoldingRemoval(
        sale_price=220,
        sale_currency="USD",
        sale_price_source="manual_entry",
        sale_date="2026-01-15",
    )
    portfolio_router.remove_holding(
        holding_id,
        db=db,
        portfolio_id=1,
        data=removal,
    )

    with pytest.raises(DcaConflictError, match="cannot be safely undone"):
        DcaLedger(db).undo_contribution(contribution_id, portfolio_id=1)

    db.expire_all()
    holding = db.get(Holding, holding_id)
    contribution = db.get(DcaContribution, contribution_id)
    trade = db.query(RealizedTrade).one()
    assert holding.is_active is False
    assert holding.shares == pytest.approx(10.5)
    assert contribution.status == "applied"
    assert contribution.applied_holding_id == holding_id
    assert trade.shares_sold == pytest.approx(10.5)
    db.close()


def test_sold_owned_holding_cannot_be_reactivated(session_factory):
    seed = session_factory()
    holding = Holding(
        portfolio_id=1,
        ticker="ACME",
        shares=10,
        avg_cost=100,
        is_active=True,
        is_watchlist=False,
    )
    seed.add(holding)
    seed.commit()
    holding_id = holding.id
    seed.close()
    db = session_factory()
    portfolio_router.remove_holding(
        holding_id,
        db=db,
        portfolio_id=1,
        data=HoldingRemoval(
            sale_price=123.45,
            sale_currency="USD",
            sale_price_source="manual_entry",
            sale_date="2026-01-15",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        portfolio_router.update_holding(
            holding_id,
            HoldingUpdate(is_active=True),
            db,
            portfolio_id=1,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "holding_archived"
    db.expire_all()
    assert db.get(Holding, holding_id).is_active is False
    assert db.query(RealizedTrade).count() == 1
    db.close()
