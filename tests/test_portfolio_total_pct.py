# pylint: disable=protected-access

import asyncio

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database as app_database
from app.models import Base, Holding, Portfolio, PortfolioSnapshot, RealizedTrade
from app.routers import portfolio as portfolio_router
from app.schemas import HoldingCreate, HoldingUpdate
from app.services import stock_service


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


def make_empty_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def add_holding(db, ticker, shares, avg_cost, is_active=True):
    db.add(
        Holding(
            portfolio_id=1,
            ticker=ticker,
            shares=shares,
            avg_cost=avg_cost,
            is_active=is_active,
        )
    )
    db.commit()


def add_trade(db, ticker, shares_sold, sale_price, avg_cost):
    db.add(
        RealizedTrade(
            portfolio_id=1,
            ticker=ticker,
            shares_sold=shares_sold,
            sale_price=sale_price,
            avg_cost=avg_cost,
            realized_gain=(sale_price - avg_cost) * shares_sold,
        )
    )
    db.commit()


def quote(ticker, price, day_change=0.0, day_change_pct=0.0):
    return {
        "ticker": ticker,
        "name": f"{ticker} Inc.",
        "current_price": price,
        "day_change": day_change,
        "day_change_pct": day_change_pct,
    }


def row_by_ticker(rows, ticker):
    return next(row for row in rows if row["ticker"] == ticker)


def test_open_holding_total_pct_uses_current_price(monkeypatch):
    db = make_db()
    add_holding(db, "OPEN", shares=10, avg_cost=100)
    monkeypatch.setattr(
        portfolio_router,
        "get_portfolio_quotes",
        lambda _tickers: [quote("OPEN", 115)],
    )

    rows, *_ = portfolio_router._compute_portfolio(1, db)

    assert row_by_ticker(rows, "OPEN")["total_return_pct"] == 15.0


def test_holding_daily_value_change_uses_share_count_times_quote_move(monkeypatch):
    db = make_db()
    add_holding(db, "VOO", shares=8.5, avg_cost=400)
    monkeypatch.setattr(
        portfolio_router,
        "get_portfolio_quotes",
        lambda _tickers: [quote("VOO", 456.70, day_change=-1.32, day_change_pct=-0.29)],
    )

    rows, total_value, total_daily_change, _ = portfolio_router._compute_portfolio(1, db)
    row = row_by_ticker(rows, "VOO")

    assert total_value == 3881.95
    assert row["day_change"] == -1.32
    assert row["daily_value_change"] == -11.22
    assert total_daily_change == -11.22


def test_partial_sale_total_pct_combines_realized_and_unrealized(monkeypatch):
    db = make_db()
    add_holding(db, "MIX", shares=5, avg_cost=100)
    add_trade(db, "MIX", shares_sold=2, sale_price=130, avg_cost=100)
    add_trade(db, "MIX", shares_sold=3, sale_price=90, avg_cost=100)
    monkeypatch.setattr(
        portfolio_router,
        "get_portfolio_quotes",
        lambda _tickers: [quote("MIX", 120)],
    )

    rows, *_ = portfolio_router._compute_portfolio(1, db)

    # Realized: +30 over $500 sold basis. Unrealized: +100 over $500 remaining basis.
    assert row_by_ticker(rows, "MIX")["total_return_pct"] == 13.0


def test_realized_stats_weight_multiple_sells_by_quantity():
    db = make_db()
    add_trade(db, "SOLD", shares_sold=1, sale_price=150, avg_cost=100)
    add_trade(db, "SOLD", shares_sold=3, sale_price=110, avg_cost=100)

    stats = portfolio_router._realized_stats_by_ticker(1, db)["SOLD"]

    assert stats["shares_sold"] == 4
    assert stats["avg_sell_price"] == 120
    assert stats["avg_cost"] == 100
    assert stats["total_return_pct"] == 20


def test_missing_or_zero_basis_returns_none(monkeypatch):
    db = make_db()
    add_holding(db, "FREE", shares=10, avg_cost=0)
    add_trade(db, "ZERO", shares_sold=2, sale_price=50, avg_cost=0)
    monkeypatch.setattr(
        portfolio_router,
        "get_portfolio_quotes",
        lambda _tickers: [quote("FREE", 20)],
    )

    rows, *_ = portfolio_router._compute_portfolio(1, db)
    stats = portfolio_router._realized_stats_by_ticker(1, db)["ZERO"]

    assert row_by_ticker(rows, "FREE")["total_return_pct"] is None
    assert stats["total_return_pct"] is None


def test_default_portfolio_is_created_on_first_use(monkeypatch):
    db = make_empty_db()
    monkeypatch.setattr(portfolio_router.settings, "DEFAULT_HOLDINGS", ["VOO", "QQQ"])

    portfolio = portfolio_router._ensure_default_portfolio(db)

    holdings = db.query(Holding).order_by(Holding.ticker).all()
    assert portfolio.id == 1
    assert portfolio.name == "My Portfolio"
    assert [h.ticker for h in holdings] == ["QQQ", "VOO"]
    assert all(h.shares == 0 for h in holdings)


def test_hold_class_persists_via_update_endpoint():
    db = make_db()
    add_holding(db, "VOO", shares=1, avg_cost=400)
    holding = db.query(Holding).filter(Holding.ticker == "VOO").first()

    result = asyncio.run(
        portfolio_router.update_holding(
            holding.id,
            HoldingUpdate(hold_class="anchor"),
            db,
        )
    )

    db.refresh(holding)
    assert result["hold_class"] == "anchor"
    assert holding.hold_class == "anchor"


def test_hold_class_startup_migration_is_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "migration.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE holdings ("
            "id INTEGER PRIMARY KEY, "
            "portfolio_id INTEGER NOT NULL, "
            "ticker VARCHAR(10) NOT NULL, "
            "shares FLOAT NOT NULL, "
            "avg_cost FLOAT NOT NULL, "
            "is_active BOOLEAN, "
            "is_watchlist BOOLEAN DEFAULT 0)"
        ))

    monkeypatch.setattr(app_database, "engine", engine)
    monkeypatch.setattr(app_database.settings, "DATABASE_URL", f"sqlite:///{db_path}")

    app_database.ensure_startup_migrations()
    app_database.ensure_startup_migrations()

    with engine.begin() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(holdings)"))]
    assert columns.count("hold_class") == 1


def test_holding_create_rejects_unsafe_ticker_characters():
    try:
        HoldingCreate(ticker="');x//", shares=1)
    except ValueError as exc:
        assert "Ticker may contain only" in str(exc)
    else:
        raise AssertionError("Unsafe ticker was accepted")


def test_holding_create_allows_common_yfinance_ticker_characters():
    assert HoldingCreate(ticker="brk.b", shares=1).ticker == "BRK.B"
    assert HoldingCreate(ticker="btc-usd", shares=1).ticker == "BTC-USD"


def test_research_holding_can_be_added_without_shares(monkeypatch):
    db = make_db()
    monkeypatch.setattr(
        portfolio_router,
        "validate_ticker_symbol",
        lambda ticker: {
            "valid": True,
            "ticker": ticker,
            "quote": quote(ticker, 100),
            "suggestions": [],
        },
    )

    result = asyncio.run(
        portfolio_router.add_holding(
            HoldingCreate(ticker="idea", is_watchlist=True),
            db=db,
        )
    )

    holding = db.query(Holding).filter(Holding.ticker == "IDEA").first()
    assert result["ticker"] == "IDEA"
    assert holding.is_watchlist is True
    assert holding.shares == 0.0


def test_add_holding_rejects_unresolved_ticker(monkeypatch):
    db = make_db()
    monkeypatch.setattr(
        portfolio_router,
        "validate_ticker_symbol",
        lambda ticker: {
            "valid": False,
            "ticker": ticker,
            "message": f"Couldn't find ticker {ticker} — check the symbol",
            "suggestions": [{"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}],
        },
    )

    try:
        asyncio.run(
            portfolio_router.add_holding(
                HoldingCreate(ticker="NOPE", shares=1),
                db=db,
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Couldn't find ticker NOPE" in exc.detail["message"]
        assert exc.detail["suggestions"][0]["ticker"] == "AAPL"
    else:
        raise AssertionError("Invalid ticker was accepted")


def test_validate_ticker_symbol_rejects_unsafe_shape_without_quote_call(monkeypatch):
    called = False

    def fake_get_stock_data(_ticker):
        nonlocal called
        called = True
        return quote("AAPL", 100)

    monkeypatch.setattr(stock_service, "get_stock_data", fake_get_stock_data)
    monkeypatch.setattr(stock_service, "suggest_tickers", lambda _ticker, limit=3: [])

    result = stock_service.validate_ticker_symbol("AAPL; DROP")

    assert result["valid"] is False
    assert "letters, numbers" in result["message"]
    assert called is False


def test_validate_ticker_symbol_requires_resolved_quote(monkeypatch):
    monkeypatch.setattr(
        stock_service,
        "get_stock_data",
        lambda ticker: {"ticker": ticker, "current_price": 0.0, "error": None},
    )
    monkeypatch.setattr(
        stock_service,
        "suggest_tickers",
        lambda _ticker, limit=3: [{"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}],
    )

    result = stock_service.validate_ticker_symbol("APPL")

    assert result["valid"] is False
    assert "Couldn't find ticker APPL" in result["message"]
    assert result["suggestions"][0]["name"] == "Apple Inc."


def test_delete_realized_trade_adjusts_realized_total_and_today_snapshot(monkeypatch):
    db = make_db()
    add_holding(db, "SOLD", shares=2, avg_cost=100)
    add_trade(db, "SOLD", shares_sold=1, sale_price=150, avg_cost=100)
    trade = db.query(RealizedTrade).filter(RealizedTrade.ticker == "SOLD").first()
    monkeypatch.setattr(
        portfolio_router,
        "get_portfolio_quotes",
        lambda _tickers: [quote("SOLD", 110)],
    )

    before = asyncio.run(portfolio_router.get_pnl(db=db))
    result = asyncio.run(portfolio_router.remove_realized_trade(trade.id, db=db))
    after = asyncio.run(portfolio_router.get_pnl(db=db))

    snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.portfolio_id == 1).one()
    assert before["realized_gain"] == 50.0
    assert before["trades"][0]["id"] == trade.id
    assert result["ticker"] == "SOLD"
    assert after["realized_gain"] == 0.0
    assert after["trades"] == []
    assert snap.realized_gain == 0.0


def test_range_performance_excludes_watchlist_and_inactive(monkeypatch):
    db = make_db()
    add_holding(db, "AAPL", shares=10, avg_cost=100)
    add_holding(db, "OLD", shares=5, avg_cost=50, is_active=False)
    db.add(Holding(
        portfolio_id=1, ticker="WATCH", shares=0, avg_cost=0,
        is_active=True, is_watchlist=True,
    ))
    db.commit()

    seen_tickers = []

    def fake_history(tickers, **_kwargs):
        seen_tickers.extend(tickers)
        closes = [100.0 + i for i in range(30)]
        return {t: closes for t in tickers}

    monkeypatch.setattr(
        "app.services.portfolio_analytics.get_batched_history_closes",
        fake_history,
    )

    result = asyncio.run(portfolio_router.get_portfolio_range_performance(db=db))

    assert seen_tickers == ["AAPL"], "inactive and watchlist holdings must not be fetched"
    assert "AAPL" in result["ranges"]["week"]["holdings"]
    assert set(result["ranges"].keys()) == {"week", "month", "threeMonth", "sixMonth", "year"}


def test_range_performance_404_for_unknown_portfolio():
    db = make_empty_db()
    try:
        asyncio.run(portfolio_router.get_portfolio_range_performance(portfolio_id=999, db=db))
        assert False, "expected HTTPException for unknown portfolio"
    except HTTPException as exc:
        assert exc.status_code == 404
