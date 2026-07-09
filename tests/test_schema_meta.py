"""Protected migration sequence: version stamping, backup-first, restore-on-fail.

Uses real on-disk SQLite files so the backup/restore paths (which operate on the
live database file) are exercised end to end. The configured DATABASE_URL and the
backup service's data directory are redirected to a temp location per test.
"""
import sqlite3

import pytest
from sqlalchemy import create_engine, text

from app import paths, schema_meta
from app.config import settings
from app.services import backup_service


@pytest.fixture
def file_db(tmp_path, monkeypatch):
    """A file-backed SQLite engine wired into config + backup paths."""
    db_path = tmp_path / "portfolio.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        yield engine, db_path
    finally:
        engine.dispose()


def test_read_schema_version_defaults_to_zero(file_db):
    engine, _ = file_db
    assert schema_meta.read_schema_version(engine) == 0


def test_fresh_db_stamps_version_without_backup(file_db):
    engine, _ = file_db
    result = schema_meta.apply_migrations_safely(engine)

    assert result.schema_version == schema_meta.SCHEMA_VERSION
    assert result.previous_schema_version == 0
    assert result.backed_up is False  # nothing to lose on a fresh DB
    assert schema_meta.read_schema_version(engine) == schema_meta.SCHEMA_VERSION
    # No backups created for a first-run empty database.
    assert list((backup_service.backups_dir()).glob("*.db")) == []


def test_existing_data_is_backed_up_and_preserved(file_db):
    engine, db_path = file_db
    # Seed a realistic holdings table with data, and force "needs migration".
    from app import models

    models.Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO portfolios (name) VALUES ('My Portfolio')"))
        conn.execute(
            text(
                "INSERT INTO holdings (portfolio_id, ticker, shares, avg_cost, is_active) "
                "VALUES (1, 'VOO', 10, 400, 1)"
            )
        )
        schema_meta._ensure_app_meta(conn)
        schema_meta._write_meta(conn, "schema_version", "0")

    result = schema_meta.apply_migrations_safely(engine)

    assert result.ran_migration is True
    assert result.backed_up is True
    assert result.backup_path is not None
    # Holding survived the migration.
    with engine.begin() as conn:
        tickers = [r[0] for r in conn.execute(text("SELECT ticker FROM holdings"))]
    assert tickers == ["VOO"]
    # A verified pre-migration backup exists and contains the holding.
    backups = list(backup_service.backups_dir().glob("pre-migrate-*.db"))
    assert len(backups) == 1
    assert backup_service.verify_backup(backups[0], expected_min_holdings=1)


def test_backup_rejects_result_that_lost_holdings(file_db, monkeypatch):
    """Regression: verification must use the DB's real holdings count, not 0.

    A hardcoded expected_min_holdings=0 would accept a "backup" that silently
    ended up with zero rows even though the live DB has one — this proves the
    fix (computing the real pre-backup count) catches that and skips the
    otherwise-unsafe migration path.
    """
    engine, db_path = file_db
    from app import models
    from app.services import backup_service as bs

    models.Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO portfolios (name) VALUES ('P')"))
        conn.execute(
            text(
                "INSERT INTO holdings (portfolio_id, ticker, shares, avg_cost, is_active) "
                "VALUES (1, 'AAPL', 1, 1, 1)"
            )
        )
        schema_meta._ensure_app_meta(conn)
        schema_meta._write_meta(conn, "schema_version", "0")

    def _empty_backup(source_db, label, dest_dir=None, ts=None):
        dest_dir = dest_dir or bs.backups_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        empty = dest_dir / f"{label}-corrupt.db"
        conn = sqlite3.connect(str(empty))
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()
        return empty

    monkeypatch.setattr(bs, "create_backup", _empty_backup)

    result = schema_meta.apply_migrations_safely(engine)

    assert result.backed_up is False
    assert result.backup_path is None


def test_had_data_detects_non_holdings_user_tables(file_db):
    """A DB with only verdict_snapshots (no holdings rows yet) still backs up first."""
    engine, _ = file_db
    from app import models

    models.Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO verdict_snapshots (ticker, action, confidence, hold_class) "
                "VALUES ('VOO', 'hold', 80, 'auto')"
            )
        )
        schema_meta._ensure_app_meta(conn)
        schema_meta._write_meta(conn, "schema_version", "0")

    result = schema_meta.apply_migrations_safely(engine)

    assert result.backed_up is True
    assert result.backup_path is not None


def test_failed_migration_restores_backup(file_db, monkeypatch):
    engine, db_path = file_db
    from app import models

    models.Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO portfolios (name) VALUES ('P')"))
        conn.execute(
            text(
                "INSERT INTO holdings (portfolio_id, ticker, shares, avg_cost, is_active) "
                "VALUES (1, 'MSFT', 5, 100, 1)"
            )
        )
        schema_meta._ensure_app_meta(conn)
        schema_meta._write_meta(conn, "schema_version", "0")

    def _boom():
        # Corrupt the live DB, then fail — the restore must undo this.
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM holdings")
        conn.commit()
        conn.close()
        raise RuntimeError("migration exploded")

    monkeypatch.setattr("app.database.ensure_startup_migrations", _boom)

    with pytest.raises(RuntimeError):
        schema_meta.apply_migrations_safely(engine)

    # After restore, the holding is back and a .failed-* file was preserved.
    check = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with check.begin() as conn:
            tickers = [r[0] for r in conn.execute(text("SELECT ticker FROM holdings"))]
    finally:
        check.dispose()
    assert tickers == ["MSFT"]
    assert list(db_path.parent.glob("portfolio.db.failed-*"))
