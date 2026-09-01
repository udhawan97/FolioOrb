"""Direct contracts for the average-cost realized-sale facts ledger."""
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Holding, Portfolio, PortfolioSnapshot, RealizedTrade
from app.services.realized_sales import (
    RealizedSaleLedger,
    RealizedSaleNotFound,
    SaleCorrection,
)


def make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # Match app.database.SessionLocal so the tests cannot rely on implicit
    # flushes that production explicitly disables.
    db = sessionmaker(bind=engine, autoflush=False)()
    db.add(Portfolio(id=1, name="Test"))
    db.commit()
    return db


def add_holding(db, *, watchlist=False):
    holding = Holding(
        portfolio_id=1,
        ticker="AAPL",
        shares=10,
        avg_cost=100,
        is_active=True,
        is_watchlist=watchlist,
    )
    db.add(holding)
    db.commit()
    return holding


def complete_quotes(_tickers):
    return [
        {
            "ticker": "AAPL",
            "current_price": 125.0,
            "previous_close": 120.0,
            "day_change": 5.0,
            "currency": "USD",
        }
    ]


def test_reduction_stages_average_cost_facts_without_committing():
    db = make_db()
    holding = add_holding(db)
    ledger = RealizedSaleLedger(
        db, 1, quote_loader=lambda _ticker: {"current_price": 130.0}
    )

    trade = ledger.stage_reduction(
        holding, 6, sale_price=120.0, sale_date="2025-12-15"
    )

    assert trade in db.new
    assert trade.shares_sold == 4.0
    assert trade.sale_price == 120.0
    assert trade.avg_cost == 100.0
    assert trade.realized_gain == 80.0
    assert trade.sale_currency == "USD"
    assert trade.sale_price_source == "manual_entry"
    assert trade.created_at == datetime(2025, 12, 15, 12, 0)
    db.rollback()
    assert db.query(RealizedTrade).count() == 0


@pytest.mark.parametrize(
    ("quote", "currency", "source"),
    [
        ({"current_price": 130.0, "currency": "USD"}, "USD", "market_quote"),
        ({"current_price": 130.0, "currency": "GBp"}, "GBp", "market_quote"),
        ({"current_price": 130.0}, None, "market_quote"),
        ({"current_price": 0.0, "currency": "USD"}, None, "cost_basis_fallback"),
    ],
)
def test_automatic_sale_persists_exact_currency_and_price_provenance(
    quote, currency, source
):
    db = make_db()
    holding = add_holding(db)

    trade = RealizedSaleLedger(
        db, 1, quote_loader=lambda _ticker: quote
    ).stage_reduction(holding, 9)

    assert trade.sale_currency == currency
    assert trade.sale_price_source == source


def test_watchlist_reduction_never_creates_a_sale_fact():
    db = make_db()
    holding = add_holding(db, watchlist=True)

    trade = RealizedSaleLedger(db, 1).stage_reduction(holding, 5)

    assert trade is None
    assert db.query(RealizedTrade).count() == 0


def test_holding_and_sale_roll_back_together_when_the_commit_fails(monkeypatch):
    db = make_db()
    holding = add_holding(db)
    ledger = RealizedSaleLedger(
        db, 1, quote_loader=lambda _ticker: {"current_price": 120.0}
    )
    ledger.stage_reduction(holding, 5)
    holding.shares = 5

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failed"):
        db.commit()
    db.rollback()

    assert db.query(RealizedTrade).count() == 0
    assert db.query(Holding).one().shares == 10


def test_correction_and_today_snapshot_commit_as_one_consistent_unit():
    db = make_db()
    add_holding(db)
    trade = RealizedTrade(
        portfolio_id=1,
        ticker="AAPL",
        shares_sold=2,
        sale_price=150,
        avg_cost=100,
        realized_gain=100,
        created_at=datetime(2026, 1, 1, 12, 0),
    )
    db.add(trade)
    db.commit()

    result = RealizedSaleLedger(
        db, 1, valuation_quote_loader=complete_quotes
    ).correct(
        trade.id,
        SaleCorrection(sale_price=160, sale_date="2025-12-28"),
    )

    snapshot = db.query(PortfolioSnapshot).filter_by(
        portfolio_id=1, snapshot_date=date.today().isoformat()
    ).one()
    assert result.realized_gain == 120.0
    assert result.created_at == datetime(2025, 12, 28, 12, 0)
    assert result.sale_currency == "USD"
    assert result.sale_price_source == "manual_entry"
    assert snapshot.realized_gain == 120.0


def test_non_price_correction_does_not_upgrade_ambiguous_legacy_provenance():
    db = make_db()
    trade = RealizedTrade(
        portfolio_id=1,
        ticker="AAPL",
        shares_sold=2,
        sale_price=150,
        avg_cost=100,
        realized_gain=100,
    )
    db.add(trade)
    db.commit()

    result = RealizedSaleLedger(
        db, 1, valuation_quote_loader=lambda _tickers: []
    ).correct(trade.id, SaleCorrection(shares_sold=3))

    assert result.sale_currency is None
    assert result.sale_price_source == "legacy_unknown"


def test_unpriceable_correction_removes_stale_today_snapshot_atomically():
    db = make_db()
    add_holding(db)
    trade = RealizedTrade(
        portfolio_id=1,
        ticker="AAPL",
        shares_sold=1,
        sale_price=150,
        avg_cost=100,
        realized_gain=50,
    )
    db.add_all(
        [
            trade,
            PortfolioSnapshot(
                portfolio_id=1,
                snapshot_date=date.today().isoformat(),
                total_value=1000,
                total_cost_basis=1000,
                unrealized_gain=0,
                realized_gain=50,
                total_return=50,
            ),
        ]
    )
    db.commit()

    RealizedSaleLedger(
        db,
        1,
        valuation_quote_loader=lambda _tickers: [],
    ).correct(trade.id, SaleCorrection(sale_price=160))

    assert db.query(RealizedTrade).one().realized_gain == 60.0
    assert db.query(PortfolioSnapshot).count() == 0


def test_removal_and_today_snapshot_commit_as_one_consistent_unit():
    db = make_db()
    add_holding(db)
    trade = RealizedTrade(
        portfolio_id=1,
        ticker="AAPL",
        shares_sold=2,
        sale_price=150,
        avg_cost=100,
        realized_gain=100,
    )
    db.add(trade)
    db.commit()

    RealizedSaleLedger(
        db, 1, valuation_quote_loader=complete_quotes
    ).remove(trade.id)

    snapshot = db.query(PortfolioSnapshot).filter_by(
        portfolio_id=1, snapshot_date=date.today().isoformat()
    ).one()
    assert db.query(RealizedTrade).count() == 0
    assert snapshot.realized_gain == 0.0


def test_new_sale_gain_reconciles_to_the_rounded_stored_values():
    db = make_db()
    holding = add_holding(db)
    holding.avg_cost = 100.004

    trade = RealizedSaleLedger(db, 1).stage_reduction(
        holding, 9, sale_price=100.006
    )

    assert trade.sale_price == 100.01
    assert trade.avg_cost == 100.0
    assert trade.realized_gain == 0.01


def test_cross_portfolio_trade_is_not_found_and_untouched():
    db = make_db()
    db.add(Portfolio(id=2, name="Other"))
    trade = RealizedTrade(
        portfolio_id=2,
        ticker="MSFT",
        shares_sold=1,
        sale_price=200,
        avg_cost=100,
        realized_gain=100,
    )
    db.add(trade)
    db.commit()

    with pytest.raises(RealizedSaleNotFound):
        RealizedSaleLedger(db, 1).remove(trade.id)

    assert db.query(RealizedTrade).one().realized_gain == 100
