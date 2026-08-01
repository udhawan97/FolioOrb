"""A holding quoted in another currency must not be summed into a dollar total.

``TICKER_PATTERN`` accepts foreign listings — ``VOD.L``, ``SHOP.TO``, ``BHP.AX``
all pass validation — and Yahoo prices each in its home currency. London quotes
arrive in *pence*, so a share priced at 70 GBp was landing in the portfolio total
as $70: a seventy-eight-fold overstatement of that position, with no indication
on screen that anything was off.

The valuation already knows how to say "this position could not be priced": a
quote that fails is left out of the totals, named in ``missing_tickers``, and
drags ``data_quality`` below "complete", which in turn suppresses the daily
snapshot. A foreign-currency quote is the same kind of problem — a number that
cannot be trusted in a dollar sum — so it travels the same path rather than a
new one, and is named separately only so the UI can explain *which* kind.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Holding, Portfolio, PortfolioSnapshot
from app.services import portfolio_valuation


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


def add_holding(db, ticker, shares, avg_cost):
    db.add(Holding(portfolio_id=1, ticker=ticker, shares=shares, avg_cost=avg_cost))
    db.commit()


def quote(ticker, price, currency="USD"):
    return {
        "ticker": ticker,
        "current_price": price,
        "day_change": 0.0,
        "day_change_pct": 0.0,
        "name": ticker,
        "currency": currency,
        "error": None,
    }


def loader(*quotes):
    return lambda _tickers: list(quotes)


def test_pence_quoted_holding_stays_out_of_the_dollar_total():
    db = make_db()
    add_holding(db, "AAPL", 10, 100.0)
    add_holding(db, "VOD.L", 100, 0.7)

    valuation = portfolio_valuation.evaluate(
        db, 1, quote_loader=loader(quote("AAPL", 150.0), quote("VOD.L", 70.0, "GBp"))
    )

    # 10 × $150 only. The 100 × 70 GBp position would have added $7,000.
    assert valuation.total_value == 1500.0
    assert valuation.foreign_currency_tickers == ("VOD.L",)


def test_foreign_holding_still_appears_with_its_currency():
    """Excluding it from the total must not hide the position itself."""
    db = make_db()
    add_holding(db, "VOD.L", 100, 0.7)

    valuation = portfolio_valuation.evaluate(
        db, 1, quote_loader=loader(quote("VOD.L", 70.0, "GBp"))
    )

    row = next(r for r in valuation.holdings if r["ticker"] == "VOD.L")
    assert row["currency"] == "GBp"
    assert row["current_price"] == 70.0
    assert row["allocation_pct"] == 0


def test_foreign_holding_degrades_data_quality():
    db = make_db()
    add_holding(db, "AAPL", 10, 100.0)
    add_holding(db, "SHOP.TO", 5, 50.0)

    valuation = portfolio_valuation.evaluate(
        db, 1, quote_loader=loader(quote("AAPL", 150.0), quote("SHOP.TO", 90.0, "CAD"))
    )

    assert valuation.data_quality == "partial"
    assert valuation.priced_position_count == 1
    assert valuation.expected_position_count == 2


def test_no_snapshot_is_recorded_while_a_holding_is_unpriceable():
    """A snapshot that quietly drops a position is worse than no snapshot."""
    db = make_db()
    add_holding(db, "AAPL", 10, 100.0)
    add_holding(db, "BHP.AX", 20, 30.0)

    valuation = portfolio_valuation.evaluate(
        db,
        1,
        quote_loader=loader(quote("AAPL", 150.0), quote("BHP.AX", 45.0, "AUD")),
        record_snapshot=True,
    )

    assert not valuation.snapshot_recorded
    assert db.query(PortfolioSnapshot).count() == 0


def test_usd_holdings_are_completely_unaffected():
    db = make_db()
    add_holding(db, "AAPL", 10, 100.0)
    add_holding(db, "MSFT", 5, 200.0)

    valuation = portfolio_valuation.evaluate(
        db, 1, quote_loader=loader(quote("AAPL", 150.0), quote("MSFT", 300.0))
    )

    assert valuation.total_value == 3000.0
    assert valuation.data_quality == "complete"
    assert not valuation.foreign_currency_tickers


def test_a_quote_without_a_currency_is_treated_as_dollars():
    """Only an explicitly foreign currency changes behaviour, never a missing one."""
    db = make_db()
    add_holding(db, "AAPL", 10, 100.0)
    bare = quote("AAPL", 150.0)
    del bare["currency"]

    valuation = portfolio_valuation.evaluate(db, 1, quote_loader=loader(bare))

    assert valuation.total_value == 1500.0
    assert valuation.data_quality == "complete"
    assert not valuation.foreign_currency_tickers


def test_currency_casing_and_padding_do_not_matter():
    """`usd `, `USD`, and `Usd` are all dollars; `GBp` is not."""
    db = make_db()
    add_holding(db, "AAPL", 10, 100.0)

    valuation = portfolio_valuation.evaluate(
        db, 1, quote_loader=loader(quote("AAPL", 150.0, " usd "))
    )

    assert valuation.total_value == 1500.0
    assert not valuation.foreign_currency_tickers


def test_a_watchlist_row_in_another_currency_does_not_degrade_quality():
    """Watchlist rows never enter the totals, so they cannot corrupt them."""
    db = make_db()
    add_holding(db, "AAPL", 10, 100.0)
    db.add(Holding(portfolio_id=1, ticker="VOD.L", shares=0, avg_cost=0, is_watchlist=True))
    db.commit()

    valuation = portfolio_valuation.evaluate(
        db, 1, quote_loader=loader(quote("AAPL", 150.0), quote("VOD.L", 70.0, "GBp"))
    )

    assert valuation.total_value == 1500.0
    assert valuation.data_quality == "complete"
    assert not valuation.foreign_currency_tickers
