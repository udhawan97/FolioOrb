"""Tests for portfolio create / rename / delete (multi-portfolio management).

Endpoints are plain async funcs, so they're called directly with an in-memory
SQLite DB (fixture style from tests/test_portfolio_total_pct.py).
"""
# pylint: disable=protected-access
import asyncio

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
from app.schemas import PortfolioCreate


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
    res = asyncio.run(pr.create_portfolio(PortfolioCreate(name="IRA"), db))
    assert res["name"] == "IRA"
    listing = asyncio.run(pr.get_portfolios(db))
    assert {p["name"] for p in listing} == {"My Portfolio", "IRA"}


def test_rename_portfolio():
    db = _db()
    new = asyncio.run(pr.create_portfolio(PortfolioCreate(name="Old"), db))
    asyncio.run(pr.rename_portfolio(new["id"], PortfolioCreate(name="Taxable"), db))
    assert db.query(Portfolio).filter(Portfolio.id == new["id"]).one().name == "Taxable"


def test_delete_portfolio_cascades_all_scoped_rows():
    db = _db()
    pid = asyncio.run(pr.create_portfolio(PortfolioCreate(name="Scratch"), db))["id"]
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

    asyncio.run(pr.delete_portfolio(pid, db))

    assert db.query(Portfolio).filter(Portfolio.id == pid).first() is None
    assert db.query(Holding).filter(Holding.portfolio_id == pid).count() == 0
    assert db.query(RealizedTrade).filter(RealizedTrade.portfolio_id == pid).count() == 0
    assert db.query(PortfolioSnapshot).filter(PortfolioSnapshot.portfolio_id == pid).count() == 0
    assert db.query(DcaPlan).filter(DcaPlan.portfolio_id == pid).count() == 0
    assert db.query(DcaContribution).count() == 0
    assert db.query(AISummary).filter(AISummary.ticker == f"BOOK:{pid}").count() == 0


def test_cannot_delete_default_portfolio():
    db = _db()
    asyncio.run(pr.create_portfolio(PortfolioCreate(name="Other"), db))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(pr.delete_portfolio(1, db))
    assert exc.value.status_code == 400


def test_cannot_delete_only_portfolio():
    db = _db()
    pid = asyncio.run(pr.create_portfolio(PortfolioCreate(name="Solo"), db))["id"]
    # Remove the default so only this one remains, then it must refuse deletion.
    db.query(Portfolio).filter(Portfolio.id == 1).delete()
    db.commit()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(pr.delete_portfolio(pid, db))
    assert exc.value.status_code == 400


def test_delete_missing_portfolio_404():
    db = _db()
    asyncio.run(pr.create_portfolio(PortfolioCreate(name="A"), db))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(pr.delete_portfolio(999, db))
    assert exc.value.status_code == 404
