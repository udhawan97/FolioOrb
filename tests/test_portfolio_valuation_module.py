"""Behavior tests for the Portfolio valuation module interface."""

import pytest
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


@pytest.mark.parametrize("invalid_price", [0, float("nan"), float("inf"), "bad-price"])
def test_invalid_price_is_unavailable_and_never_records_a_snapshot(invalid_price):
    db = _db()
    db.add(Holding(portfolio_id=1, ticker="ZERO", shares=10, avg_cost=100))
    db.commit()

    valuation = portfolio_valuation.evaluate(
        db,
        1,
        quote_loader=lambda _tickers: [_quote("ZERO", invalid_price)],
        record_snapshot=True,
    )

    assert valuation.data_quality == "unavailable"
    assert valuation.missing_tickers == ("ZERO",)
    assert valuation.total_value == 0
    assert valuation.snapshot_recorded is False
    assert db.query(PortfolioSnapshot).count() == 0


def test_total_return_pct_includes_open_and_realized_cost_basis():
    db = _db()
    db.add(Holding(portfolio_id=1, ticker="MIX", shares=5, avg_cost=100))
    db.add(
        RealizedTrade(
            portfolio_id=1,
            ticker="MIX",
            shares_sold=5,
            sale_price=120,
            avg_cost=100,
            realized_gain=100,
            sale_currency="USD",
            sale_price_source="manual_entry",
        )
    )
    db.commit()

    valuation = portfolio_valuation.evaluate(
        db,
        1,
        quote_loader=lambda _tickers: [_quote("MIX", 120)],
    )

    assert valuation.total_unrealized_gain == 100
    assert valuation.realized_gain == 100
    assert valuation.total_return_cost_basis == 1000
    assert valuation.total_return_pct == 20


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
                sale_currency="USD",
                sale_price_source="market_quote",
            ),
            RealizedTrade(
                portfolio_id=1,
                ticker="SOLD",
                shares_sold=3,
                sale_price=110,
                avg_cost=100,
                realized_gain=30,
                sale_currency="USD",
                sale_price_source="manual_entry",
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


def test_foreign_and_ambiguous_sales_never_enter_usd_returns_or_history():
    db = _db()
    db.add(Holding(portfolio_id=1, ticker="MIX", shares=5, avg_cost=100))
    db.add_all(
        [
            RealizedTrade(
                portfolio_id=1, ticker="MIX", shares_sold=5,
                sale_price=120, avg_cost=100, realized_gain=100,
                sale_currency="USD", sale_price_source="market_quote",
            ),
            RealizedTrade(
                portfolio_id=1, ticker="MIX", shares_sold=5,
                sale_price=140, avg_cost=100, realized_gain=200,
                sale_currency="GBp", sale_price_source="market_quote",
            ),
            RealizedTrade(
                portfolio_id=1, ticker="MIX", shares_sold=5,
                sale_price=160, avg_cost=100, realized_gain=300,
            ),
            RealizedTrade(
                portfolio_id=1, ticker="MIX", shares_sold=5,
                sale_price=180, avg_cost=100, realized_gain=400,
                sale_currency="USD", sale_price_source="legacy_unknown",
            ),
            PortfolioSnapshot(
                portfolio_id=1, snapshot_date="2026-07-14", total_value=500,
                total_cost_basis=500, unrealized_gain=100,
                realized_gain=1000, total_return=1100,
            ),
        ]
    )
    db.commit()

    valuation = portfolio_valuation.evaluate(
        db, 1, quote_loader=lambda _tickers: [_quote("MIX", 120)],
        record_snapshot=True,
    )

    assert valuation.realized_gain == 100
    assert valuation.total_return_cost_basis == 1000
    assert valuation.total_return == 200
    assert valuation.total_return_pct == 20
    assert valuation.excluded_realized_trade_count == 3
    assert valuation.realized_data_quality == "partial"
    assert valuation.data_quality == "partial"
    assert valuation.snapshot_recorded is False

    performance = portfolio_valuation.load_performance(db, 1)
    assert performance.realized_gain == 100
    assert [trade["realized_gain"] for trade in performance.trades] == [100]
    assert performance.excluded_realized_trade_count == 3
    assert performance.realized_data_quality == "partial"
    assert not performance.history
    assert portfolio_valuation.snapshot_history(db, 1) == [
        {"date": "2026-07-14", "total_value": 500.0}
    ]
