"""
Regression tests for the daily portfolio-snapshot uniqueness guarantee.

Two paths are covered:
  1. The startup migration collapses pre-existing duplicate snapshot rows to the
     most recent row per (portfolio_id, snapshot_date) and installs the UNIQUE index.
  2. That collapse is a one-time repair, not per-boot work.
  3. Portfolio valuation refreshes today's snapshot in place instead of inserting a
     second row for the same day.
"""
# pylint: disable=protected-access
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import _ensure_performance_indexes
from app.models import Base, Holding, Portfolio, PortfolioSnapshot
from app.services import portfolio_valuation


def _make_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_migration_dedupes_snapshots_and_adds_unique_index():
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE portfolio_snapshots ("
            "id INTEGER PRIMARY KEY, portfolio_id INTEGER, snapshot_date VARCHAR(10), "
            "total_value FLOAT, total_cost_basis FLOAT, unrealized_gain FLOAT, "
            "realized_gain FLOAT, total_return FLOAT, created_at DATETIME)"
        ))
        conn.execute(text(
            "CREATE TABLE holdings "
            "(id INTEGER PRIMARY KEY, portfolio_id INTEGER, is_active BOOLEAN)"
        ))
        # Three duplicate rows for the same day; the row with the highest id must win.
        for value in (100, 200, 300):
            conn.execute(text(
                "INSERT INTO portfolio_snapshots "
                "(portfolio_id, snapshot_date, total_value, total_cost_basis, "
                "unrealized_gain, realized_gain, total_return) "
                "VALUES (1, '2026-07-07', :v, 0, 0, 0, 0)"
            ), {"v": value})

        _ensure_performance_indexes(conn, {"portfolio_snapshots", "holdings"})

        rows = conn.execute(text(
            "SELECT COUNT(*), MAX(total_value) FROM portfolio_snapshots"
        )).fetchone()
        assert rows[0] == 1
        assert rows[1] == 300  # latest row retained

        indexes = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        ).fetchall()}
        assert "ux_portfolio_snapshots_pid_date" in indexes
        assert "ix_holdings_portfolio_active" in indexes


def test_dedupe_scan_is_skipped_once_the_unique_index_exists():
    """The collapse is a one-time repair, so it must not run on every startup.

    Migrations run before the app serves anything, and this one did a full scan
    plus GROUP BY over portfolio_snapshots on every boot. It can only ever find
    rows on a database predating the unique index — once that index is there,
    duplicates cannot be inserted at all.
    """
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE portfolio_snapshots ("
            "id INTEGER PRIMARY KEY, portfolio_id INTEGER, snapshot_date VARCHAR(10), "
            "total_value FLOAT, total_cost_basis FLOAT, unrealized_gain FLOAT, "
            "realized_gain FLOAT, total_return FLOAT, created_at DATETIME)"
        ))
        conn.execute(text(
            "CREATE TABLE holdings "
            "(id INTEGER PRIMARY KEY, portfolio_id INTEGER, is_active BOOLEAN)"
        ))
        _ensure_performance_indexes(conn, {"portfolio_snapshots", "holdings"})

    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn, _cursor, statement, *_args):  # noqa: ARG001
        seen.append(statement)

    with engine.begin() as conn:
        _ensure_performance_indexes(conn, {"portfolio_snapshots", "holdings"})

    assert not [s for s in seen if "DELETE FROM portfolio_snapshots" in s], (
        "the dedupe scan ran again even though the unique index already exists"
    )


def test_upsert_daily_snapshot_is_idempotent_within_a_day():
    engine = _make_engine()
    Base.metadata.create_all(bind=engine)  # includes the unique index via __table_args__
    session = sessionmaker(bind=engine)()
    session.add(Portfolio(id=1, name="Test"))
    session.add(Holding(portfolio_id=1, ticker="TEST", shares=10, avg_cost=80))
    session.commit()

    def quote_at(price):
        return lambda _tickers: [{
            "ticker": "TEST", "current_price": price,
            "day_change": 0.5, "day_change_pct": 0.5,
        }]

    portfolio_valuation.evaluate(
        session, 1, quote_loader=quote_at(100), record_snapshot=True
    )
    portfolio_valuation.evaluate(
        session, 1, quote_loader=quote_at(110), record_snapshot=True
    )

    snaps = session.query(PortfolioSnapshot).filter_by(portfolio_id=1).all()
    assert len(snaps) == 1              # one row per day, not two
    assert snaps[0].total_value == 1100.0  # refreshed to the latest figures
