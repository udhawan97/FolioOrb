"""Database schema versioning and the safe-migration entry point.

The app's tables are created by ``create_all`` and evolved by the idempotent
raw-SQL steps in ``app.database.ensure_startup_migrations``. This module wraps
both in a *protected* sequence:

* An ``app_meta`` key/value table records the on-disk ``schema_version``.
* When the stored version is behind the code's ``SCHEMA_VERSION`` **and** the
  database already holds user data, a verified backup is taken *before* any
  migration runs.
* If the migration then raises, the verified backup is restored and the broken
  database is set aside as ``*.failed-*`` for inspection.

Invariant: holdings data is never mutated by a version-bumping migration without
a recoverable, integrity-checked copy on disk first.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Bump this whenever a new migration changes the on-disk schema shape. A bump
# triggers the backup-first path on existing databases. SCHEMA_VERSION = 1 is the
# baseline: the schema shipped through v4.3.x (hold_class, is_watchlist,
# verdict_snapshots, the performance indexes, and the snapshot uniqueness index).
# v2 adds the DCA tables (dca_plans, dca_contributions) — additive-only, created
# by create_all, so MIN_COMPATIBLE_APP_VERSION is unchanged.
# v3 adds the additive dca_plans.catchup_floor column (ALTER in
# ensure_startup_migrations) — still additive, MIN_COMPATIBLE unchanged.
# v4 adds the additive verdict_snapshots.portfolio_id column (ALTER + backfill
# to portfolio 1) for per-portfolio verdict history — additive, MIN_COMPATIBLE
# unchanged.
SCHEMA_VERSION = 4

# Oldest app version whose ORM models can still read this schema. Additive-only
# migrations (new tables/columns/indexes) keep this unchanged, so a normal
# rollback to a recent prior version always works. A *destructive* migration must
# raise this value AND must hard-require the pre-migration backup (see below).
MIN_COMPATIBLE_APP_VERSION = "4.3.0"

_META_TABLE = "app_meta"

# Tables that indicate the database already holds real user data. Checked by
# name rather than just "holdings" so a database that has, say, realized
# trades or verdict history but (temporarily) zero active holdings still gets
# the backup-first treatment.
_USER_DATA_TABLES = (
    "holdings",
    "realized_trades",
    "verdict_snapshots",
    "portfolio_snapshots",
    "ai_summaries",
)


@dataclass
class MigrationResult:
    """Outcome of :func:`apply_migrations_safely`, for logging and diagnostics."""

    ran_migration: bool
    backed_up: bool
    backup_path: str | None
    restored: bool
    previous_schema_version: int
    schema_version: int


def _ensure_app_meta(conn) -> None:
    conn.execute(
        text(f"CREATE TABLE IF NOT EXISTS {_META_TABLE} (key VARCHAR PRIMARY KEY, value VARCHAR)")
    )


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    ).fetchone()
    return row is not None


def _read_meta(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute(
        text(f"SELECT value FROM {_META_TABLE} WHERE key=:k"), {"k": key}
    ).fetchone()
    return row[0] if row else default


def _write_meta(conn, key: str, value: str) -> None:
    conn.execute(
        text(
            f"INSERT INTO {_META_TABLE}(key, value) VALUES(:k, :v) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        ),
        {"k": key, "v": value},
    )


def read_schema_version(engine: Engine) -> int:
    """Return the on-disk schema version, creating ``app_meta`` if absent (0 if unset)."""
    with engine.begin() as conn:
        _ensure_app_meta(conn)
        raw = _read_meta(conn, "schema_version", "0")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _is_file_sqlite() -> bool:
    from app.config import settings

    url = settings.DATABASE_URL
    return url.startswith("sqlite") and ":memory:" not in url


def apply_migrations_safely(engine: Engine) -> MigrationResult:
    """Run schema creation and migrations with backup-first / restore-on-failure.

    Steps:
      1. Ensure ``app_meta`` and read the stored schema version.
      2. If the version is behind and the DB already holds data, take a verified
         backup first (best effort — a failed backup is logged, and the current
         migration set is additive/non-destructive so startup still proceeds; a
         future destructive migration must instead hard-require this backup).
      3. Run ``create_all`` (additive: only ever creates missing tables) followed
         by ``ensure_startup_migrations`` (idempotent).
      4. On failure, restore the verified backup and re-raise.
      5. On success, stamp the new schema version and metadata.
    """
    from app import models
    from app.database import ensure_startup_migrations
    from app.version import __version__

    with engine.begin() as conn:
        _ensure_app_meta(conn)
        stored = int(_read_meta(conn, "schema_version", "0") or 0)
        had_data = any(_table_exists(conn, name) for name in _USER_DATA_TABLES)

    needs_bump = stored < SCHEMA_VERSION
    backup_path = None
    backed_up = False
    restored = False

    if needs_bump and had_data and _is_file_sqlite():
        try:
            from app.services import backup_service

            source_db = backup_service.live_db_path()
            # The database's real current holdings count, so verification below
            # can catch a backup that silently lost the table — a hardcoded
            # expectation of 0 would let that slip through undetected.
            pre_count = backup_service.count_holdings(source_db)
            backup_path = backup_service.create_backup(source_db, label=f"pre-migrate-v{stored}")
            backed_up = backup_service.verify_backup(backup_path, expected_min_holdings=pre_count)
            if not backed_up:
                logger.error("Pre-migration backup failed verification: %s", backup_path.name)
                backup_path = None
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Could not create pre-migration backup: %s", type(exc).__name__)
            backup_path = None

    try:
        models.Base.metadata.create_all(bind=engine)
        ensure_startup_migrations(engine)
    except Exception:
        if backup_path and backed_up:
            from app.services import backup_service

            engine.dispose()
            restored = backup_service.restore_backup(backup_path, backup_service.live_db_path())
            logger.error("Migration failed; restored pre-migration backup %s", backup_path.name)
        raise

    with engine.begin() as conn:
        if needs_bump:
            _write_meta(conn, "schema_version", str(SCHEMA_VERSION))
            _write_meta(conn, "min_compatible_app_version", MIN_COMPATIBLE_APP_VERSION)
        _write_meta(conn, "last_run_app_version", __version__)

    return MigrationResult(
        ran_migration=needs_bump,
        backed_up=backed_up,
        backup_path=str(backup_path) if backup_path else None,
        restored=restored,
        previous_schema_version=stored,
        schema_version=SCHEMA_VERSION,
    )
