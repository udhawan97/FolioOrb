"""Interface tests for the DCA plan ledger module."""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Holding, Portfolio
from app.services.dca_ledger import DcaLedger


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
