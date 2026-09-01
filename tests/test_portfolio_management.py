"""Tests for portfolio create / rename / delete (multi-portfolio management).

Endpoints are plain async funcs, so they're called directly with an in-memory
SQLite DB (fixture style from tests/test_portfolio_total_pct.py).
"""
# pylint: disable=protected-access
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base, Portfolio, Holding, RealizedTrade, PortfolioSnapshot,
    DcaPlan, DcaContribution, AISummary,
)
from app.routers import portfolio as pr
from app.schemas import HoldingUpdate, PortfolioCreate


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(Portfolio(id=1, name="My Portfolio"))
    session.commit()
    return session


def test_create_and_list_portfolios():
    db = _db()
    res = pr.create_portfolio(PortfolioCreate(name="IRA"), db)
    assert res["name"] == "IRA"
    listing = pr.get_portfolios(db)
    assert {p["name"] for p in listing} == {"My Portfolio", "IRA"}


def test_rename_portfolio():
    db = _db()
    new = pr.create_portfolio(PortfolioCreate(name="Old"), db)
    pr.rename_portfolio(new["id"], PortfolioCreate(name="Taxable"), db)
    assert db.query(Portfolio).filter(Portfolio.id == new["id"]).one().name == "Taxable"


def test_delete_portfolio_cascades_all_scoped_rows():
    db = _db()
    pid = pr.create_portfolio(PortfolioCreate(name="Scratch"), db)["id"]
    # Populate every portfolio-scoped table for this portfolio.
    db.add(Holding(portfolio_id=pid, ticker="AAPL", shares=5, avg_cost=100))
    db.add(RealizedTrade(portfolio_id=pid, ticker="AAPL", shares_sold=1,
                         sale_price=110, avg_cost=100, realized_gain=10))
    db.add(PortfolioSnapshot(portfolio_id=pid, snapshot_date="2026-07-11",
                            total_value=1, total_cost_basis=1, unrealized_gain=0,
                            realized_gain=0, total_return=0))
    db.add(AISummary(ticker=f"BOOK:{pid}", summary_type="briefing", summary_text="x"))
    db.commit()
    plan = DcaPlan(portfolio_id=pid, ticker="AAPL", amount=50, frequency="weekly",
                   start_date="2026-06-01")
    db.add(plan)
    db.flush()
    db.add(DcaContribution(plan_id=plan.id, scheduled_date="2026-06-01",
                          exec_date="2026-06-01", price=100, shares=0.5, amount=50))
    db.commit()

    pr.delete_portfolio(pid, db)

    assert db.query(Portfolio).filter(Portfolio.id == pid).first() is None
    assert db.query(Holding).filter(Holding.portfolio_id == pid).count() == 0
    assert db.query(RealizedTrade).filter(RealizedTrade.portfolio_id == pid).count() == 0
    assert db.query(PortfolioSnapshot).filter(PortfolioSnapshot.portfolio_id == pid).count() == 0
    assert db.query(DcaPlan).filter(DcaPlan.portfolio_id == pid).count() == 0
    assert db.query(DcaContribution).count() == 0
    assert db.query(AISummary).filter(AISummary.ticker == f"BOOK:{pid}").count() == 0


def test_cannot_delete_default_portfolio():
    db = _db()
    pr.create_portfolio(PortfolioCreate(name="Other"), db)
    with pytest.raises(HTTPException) as exc:
        pr.delete_portfolio(1, db)
    assert exc.value.status_code == 400


def test_cannot_delete_only_portfolio():
    db = _db()
    pid = pr.create_portfolio(PortfolioCreate(name="Solo"), db)["id"]
    # Remove the default so only this one remains, then it must refuse deletion.
    db.query(Portfolio).filter(Portfolio.id == 1).delete()
    db.commit()
    with pytest.raises(HTTPException) as exc:
        pr.delete_portfolio(pid, db)
    assert exc.value.status_code == 400


def test_delete_missing_portfolio_404():
    db = _db()
    pr.create_portfolio(PortfolioCreate(name="A"), db)
    with pytest.raises(HTTPException) as exc:
        pr.delete_portfolio(999, db)
    assert exc.value.status_code == 404


def test_reactivating_a_duplicate_holding_is_a_user_safe_conflict():
    db = _db()
    active = Holding(
        portfolio_id=1,
        ticker="AAPL",
        shares=1,
        avg_cost=100,
        is_watchlist=True,
    )
    archived = Holding(
        portfolio_id=1,
        ticker="AAPL",
        shares=2,
        avg_cost=90,
        is_active=False,
        is_watchlist=True,
    )
    db.add_all([active, archived])
    db.commit()

    with pytest.raises(HTTPException) as exc:
        pr.update_holding(
            archived.id,
            HoldingUpdate(is_active=True),
            db,
            portfolio_id=1,
        )

    assert exc.value.status_code == 400
    assert "already in portfolio" in str(exc.value.detail)
    db.refresh(archived)
    assert archived.is_active is False


def test_concurrent_reactivations_serialize_to_one_active_holding(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'portfolio.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        db.add(Portfolio(id=1, name="My Portfolio"))
        first = Holding(
            portfolio_id=1,
            ticker="RACE",
            shares=1,
            is_active=False,
            is_watchlist=True,
        )
        second = Holding(
            portfolio_id=1,
            ticker="RACE",
            shares=2,
            is_active=False,
            is_watchlist=True,
        )
        db.add_all([first, second])
        db.commit()
        holding_ids = (first.id, second.id)

    first_at_commit = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()
    original_commit = pr._commit_holding_update

    def paused_commit(db, holding):
        if not first_at_commit.is_set():
            first_at_commit.set()
            assert release_first.wait(5), "timed out waiting to release reactivation"
        return original_commit(db, holding)

    monkeypatch.setattr(pr, "_commit_holding_update", paused_commit)

    def reactivate(holding_id):
        with sessions() as db:
            try:
                pr.update_holding(
                    holding_id,
                    HoldingUpdate(is_active=True),
                    db,
                    portfolio_id=1,
                )
                return 200
            except HTTPException as exc:
                assert exc.detail == "RACE already in portfolio"
                return exc.status_code

    def second_reactivation():
        try:
            return reactivate(holding_ids[1])
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(reactivate, holding_ids[0])
        assert first_at_commit.wait(5)
        second_future = pool.submit(second_reactivation)
        assert not second_finished.wait(0.2)
        release_first.set()
        statuses = [first_future.result(timeout=5), second_future.result(timeout=5)]

    with sessions() as db:
        active = (
            db.query(Holding)
            .filter(Holding.portfolio_id == 1, Holding.is_active.is_(True))
            .all()
        )
    engine.dispose()

    assert sorted(statuses) == [200, 400]
    assert len(active) == 1
    assert active[0].ticker == "RACE"
