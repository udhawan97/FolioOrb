"""A recorded sale can be corrected in place, and its gain always follows.

A realized sale could be deleted but never edited. Correcting a mistyped price
meant deleting the trade and redoing the share reduction that created it —
which re-derives the cost basis from the holding as it stands *now*, not as it
stood at the sale, so the correction could quietly change more than the typo did.

``realized_gain`` is not an input. It is ``(sale_price - avg_cost) *
shares_sold``, so every edit recomputes it rather than trusting a caller to keep
it consistent — the one thing a hand-editable gain field would guarantee is a
ledger that disagrees with its own arithmetic.
"""
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Portfolio, RealizedTrade
from app.routers import portfolio as portfolio_router
from app.schemas import RealizedTradeUpdate


def make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(Portfolio(id=1, name="Test Portfolio"))
    session.commit()
    return session


def add_trade(db, **overrides):
    fields = {
        "portfolio_id": 1,
        "ticker": "AAPL",
        "shares_sold": 10.0,
        "sale_price": 150.0,
        "avg_cost": 100.0,
        "realized_gain": 500.0,
    }
    fields.update(overrides)
    trade = RealizedTrade(**fields)
    db.add(trade)
    db.commit()
    return trade


def edit(db, trade_id, **fields):
    return portfolio_router.update_realized_trade(
        trade_id, RealizedTradeUpdate(**fields), db=db
    )


def test_correcting_the_sale_price_recomputes_the_gain():
    db = make_db()
    trade = add_trade(db)

    edit(db, trade.id, sale_price=160.0)

    db.refresh(trade)
    assert trade.sale_price == 160.0
    assert trade.realized_gain == 600.0  # (160 - 100) × 10


def test_correcting_the_share_count_recomputes_the_gain():
    db = make_db()
    trade = add_trade(db)

    edit(db, trade.id, shares_sold=4.0)

    db.refresh(trade)
    assert trade.shares_sold == 4.0
    assert trade.realized_gain == 200.0  # (150 - 100) × 4


def test_correcting_the_cost_basis_recomputes_the_gain():
    db = make_db()
    trade = add_trade(db)

    edit(db, trade.id, avg_cost=120.0)

    db.refresh(trade)
    assert trade.realized_gain == 300.0  # (150 - 120) × 10


def test_a_correction_can_turn_a_gain_into_a_loss():
    db = make_db()
    trade = add_trade(db)

    edit(db, trade.id, sale_price=80.0)

    db.refresh(trade)
    assert trade.realized_gain == -200.0  # (80 - 100) × 10


def test_the_sale_date_can_be_moved_into_its_real_tax_year():
    db = make_db()
    trade = add_trade(db, created_at=datetime(2026, 1, 5, 12, 0))

    edit(db, trade.id, sale_date="2025-12-28")

    db.refresh(trade)
    assert trade.created_at.date() == date(2025, 12, 28)
    # Noon, so a timezone shift on display cannot walk it across midnight and
    # back into the wrong year — the same stamp a fresh reduction uses.
    assert trade.created_at.hour == 12


def test_untouched_fields_are_left_alone():
    db = make_db()
    trade = add_trade(db, created_at=datetime(2026, 3, 3, 12, 0))

    edit(db, trade.id, sale_price=155.0)

    db.refresh(trade)
    assert trade.shares_sold == 10.0
    assert trade.avg_cost == 100.0
    assert trade.ticker == "AAPL"
    assert trade.created_at == datetime(2026, 3, 3, 12, 0)


def test_an_empty_edit_is_harmless():
    db = make_db()
    trade = add_trade(db)

    edit(db, trade.id)

    db.refresh(trade)
    assert trade.sale_price == 150.0
    assert trade.realized_gain == 500.0


def test_editing_a_missing_trade_is_a_404():
    db = make_db()
    with pytest.raises(HTTPException) as exc:
        edit(db, 999, sale_price=10.0)
    assert exc.value.status_code == 404


def test_a_non_positive_price_is_rejected_before_it_reaches_the_ledger():
    for bad in (0, -5):
        with pytest.raises(ValueError):
            RealizedTradeUpdate(sale_price=bad)


def test_a_future_sale_date_is_rejected():
    with pytest.raises(ValueError):
        RealizedTradeUpdate(sale_date="2099-01-01")


def test_the_response_names_the_ticker_it_changed():
    db = make_db()
    trade = add_trade(db, ticker="MSFT")

    result = edit(db, trade.id, sale_price=200.0)

    assert result["ticker"] == "MSFT"
    assert result["realized_gain"] == 1000.0  # (200 - 100) × 10
