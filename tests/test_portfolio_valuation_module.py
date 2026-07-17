"""Behavior tests for the Portfolio valuation module interface."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Holding, Portfolio, PortfolioSnapshot, RealizedTrade
from app.services import portfolio_valuation


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(Portfolio(id=1, name="Primary"))
    session.commit()
    return session


def _quote(ticker: str, price: float, day_change: float = 0.0) -> dict:
    return {
        "ticker": ticker,
        "name": ticker,
        "current_price": price,
        "day_change": day_change,
        "day_change_pct": 0.0,
    }


def test_complete_valuation_records_exact_financial_snapshot():
    db = _db()
    db.add_all(
        [
            Holding(portfolio_id=1, ticker="OPEN", shares=10, avg_cost=100),
            Holding(
                portfolio_id=1,
                ticker="WATCH",
                shares=0,
                avg_cost=0,
                is_watchlist=True,
            ),
        ]
    )
    db.commit()

    valuation = portfolio_valuation.evaluate(
        db,
        1,
        quote_loader=lambda _tickers: [
            _quote("OPEN", 115, day_change=2),
            _quote("WATCH", 50),
        ],
        record_snapshot=True,
    )

    assert valuation.data_quality == "complete"
    assert not valuation.missing_tickers
    assert valuation.total_value == 1150.0
    assert valuation.total_cost_basis == 1000.0
    assert valuation.total_daily_change == 20.0
    assert valuation.total_unrealized_gain == 150.0
    assert valuation.realized_gain == 0.0
    assert valuation.total_return == 150.0
    assert valuation.total_return_pct == 15.0
    assert valuation.snapshot_recorded is True
    assert db.query(PortfolioSnapshot).one().total_return == 150.0


def test_performance_history_reports_realized_ledger_and_daily_snapshots():
    db = _db()
    db.add_all(
        [
            RealizedTrade(
                portfolio_id=1,
                ticker="SOLD",
                shares_sold=1,
                sale_price=150,
                avg_cost=100,
                realized_gain=50,
            ),
            RealizedTrade(
                portfolio_id=1,
                ticker="SOLD",
                shares_sold=3,
                sale_price=110,
                avg_cost=100,
                realized_gain=30,
            ),
            PortfolioSnapshot(
                portfolio_id=1,
                snapshot_date="2026-07-15",
                total_value=500,
                total_cost_basis=400,
                unrealized_gain=20,
                realized_gain=80,
                total_return=100,
            ),
        ]
    )
    db.commit()

    performance = portfolio_valuation.load_performance(db, 1)

    assert performance.realized_gain == 80.0
    assert [trade["total_return_pct"] for trade in performance.trades] == [20.0, 20.0]
    assert performance.history == [
        {
            "date": "2026-07-15",
            "total_value": 500.0,
            "total_cost_basis": 400.0,
            "unrealized_gain": 20.0,
            "realized_gain": 80.0,
            "total_return": 100.0,
        }
    ]
