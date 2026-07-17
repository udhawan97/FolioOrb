"""Behavior tests for the Portfolio lifecycle module interface."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.models import (
    AISummary,
    Base,
    DcaContribution,
    DcaPlan,
    Holding,
    Portfolio,
    PortfolioSnapshot,
    RealizedTrade,
    VerdictSnapshot,
)
from app.services import portfolio_lifecycle


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_owned_records(db, portfolio_id: int, ticker: str) -> None:
    db.add(Holding(portfolio_id=portfolio_id, ticker=ticker, shares=1, avg_cost=100))
    db.add(
        RealizedTrade(
            portfolio_id=portfolio_id,
            ticker=ticker,
            shares_sold=1,
            sale_price=110,
            avg_cost=100,
            realized_gain=10,
        )
    )
    db.add(
        PortfolioSnapshot(
            portfolio_id=portfolio_id,
            snapshot_date="2026-07-16",
            total_value=110,
            total_cost_basis=100,
            unrealized_gain=10,
            realized_gain=10,
            total_return=20,
        )
    )
    db.add(
        VerdictSnapshot(
            portfolio_id=portfolio_id,
            ticker=ticker,
            action="hold",
            confidence=70,
        )
    )
    db.add(AISummary(ticker=f"BOOK:{portfolio_id}", summary_type="briefing", summary_text="{}"))
    db.flush()
    plan = DcaPlan(
        portfolio_id=portfolio_id,
        ticker=ticker,
        amount=50,
        frequency="weekly",
        start_date="2026-07-01",
    )
    db.add(plan)
    db.flush()
    db.add(
        DcaContribution(
            plan_id=plan.id,
            scheduled_date="2026-07-01",
            exec_date="2026-07-01",
            price=100,
            shares=0.5,
            amount=50,
        )
    )


def test_delete_portfolio_removes_all_owned_records_and_preserves_other_portfolios():
    db = _db()
    db.add_all([Portfolio(id=1, name="Primary"), Portfolio(id=2, name="IRA")])
    db.flush()
    _seed_owned_records(db, 1, "KEEP")
    _seed_owned_records(db, 2, "DROP")
    db.commit()

    deleted_name = portfolio_lifecycle.delete_portfolio(db, 2)

    assert deleted_name == "IRA"
    assert [p.id for p in portfolio_lifecycle.list_portfolios(db)] == [1]
    assert db.query(Holding).filter_by(portfolio_id=2).count() == 0
    assert db.query(RealizedTrade).filter_by(portfolio_id=2).count() == 0
    assert db.query(PortfolioSnapshot).filter_by(portfolio_id=2).count() == 0
    assert db.query(VerdictSnapshot).filter_by(portfolio_id=2).count() == 0
    assert db.query(DcaPlan).filter_by(portfolio_id=2).count() == 0
    assert db.query(DcaContribution).count() == 1
    assert db.query(AISummary).filter_by(ticker="BOOK:2").count() == 0
    assert db.query(Holding).filter_by(portfolio_id=1).count() == 1
    assert db.query(VerdictSnapshot).filter_by(portfolio_id=1).count() == 1
    assert db.query(AISummary).filter_by(ticker="BOOK:1").count() == 1


def test_require_portfolio_seeds_only_the_default_portfolio(monkeypatch):
    db = _db()
    monkeypatch.setattr(portfolio_lifecycle.settings, "DEFAULT_HOLDINGS", ["VOO", "QQQ"])

    default = portfolio_lifecycle.require_portfolio(db, 1)

    assert default.name == "My Portfolio"
    assert [h.ticker for h in default.holdings] == ["VOO", "QQQ"]
    with pytest.raises(portfolio_lifecycle.PortfolioNotFoundError):
        portfolio_lifecycle.require_portfolio(db, 2)


def test_create_and_rename_portfolio_through_lifecycle_interface():
    db = _db()
    portfolio_lifecycle.require_portfolio(db, 1)

    created = portfolio_lifecycle.create_portfolio(db, "Retirement", "Long term")
    renamed = portfolio_lifecycle.rename_portfolio(db, created.id, "IRA", None)

    assert renamed.name == "IRA"
    assert renamed.description == "Long term"
    assert [(p.id, p.name) for p in portfolio_lifecycle.list_portfolios(db)] == [
        (1, "My Portfolio"),
        (created.id, "IRA"),
    ]
