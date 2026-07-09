"""Safe backup, verification, and restore of the SQLite portfolio database.

Holdings data is the app's most valuable state, so every backup goes through the
SQLite *online backup API* (``sqlite3.Connection.backup``) rather than a raw file
copy. The online API is the only WAL-safe way to snapshot a live database: it
copies a transactionally consistent set of pages even while the app is reading
and writing, and it checkpoints the WAL contents into the standalone backup file
so the result is a single, self-contained ``.db`` with no ``-wal``/``-shm``
sidecars to keep in sync.

Restores never delete the current files — the (possibly broken) live database is
moved aside as ``*.failed-<timestamp>`` for inspection before the verified backup
is copied into place.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from pathlib import Path

from app import paths

logger = logging.getLogger(__name__)

BACKUP_DIRNAME = "backups"
DEFAULT_KEEP = 5


def backups_dir() -> Path:
    """Directory holding database backups, created on first use."""
    directory = paths.data_dir() / BACKUP_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def env_path() -> Path:
    """Path to the per-user ``.env`` (Claude key etc.)."""
    return paths.data_dir() / ".env"


def snapshot_env(dest_path: Path) -> Path | None:
    """Copy the current ``.env`` to ``dest_path`` if it exists; else return None."""
    src = env_path()
    if not src.exists():
        return None
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest_path)
    return dest_path


def restore_env(env_backup: Path, ts: str | None = None) -> bool:
    """Restore a ``.env`` backup, preserving the current one as ``.failed-<ts>``."""
    env_backup = Path(env_backup)
    if not env_backup.exists():
        return False
    current = env_path()
    if current.exists():
        stamp = ts or _timestamp()
        current.replace(Path(f"{current}.failed-{stamp}"))
    shutil.copyfile(env_backup, current)
    return True


def live_db_path() -> Path:
    """Filesystem path of the live SQLite database from the configured URL.

    Raises ``ValueError`` for non-file databases (non-SQLite or ``:memory:``),
    which cannot be backed up and are only used in tests/dev.
    """
    from app.config import settings

    url = settings.DATABASE_URL
    if not url.startswith("sqlite") or ":memory:" in url:
        raise ValueError("Backups require a file-based SQLite database")
    return Path(url.replace("sqlite:///", "", 1))


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def count_holdings(db_path: Path) -> int:
    """Row count of the ``holdings`` table in ``db_path`` (0 if missing/absent).

    Callers use this *before* taking a safety-critical backup so
    ``verify_backup`` can be given the database's real current count instead of
    a hardcoded ``0`` — otherwise a backup that silently lost the holdings
    table would still pass verification (0 rows satisfies an expectation of 0).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def create_backup(
    source_db: Path,
    label: str,
    dest_dir: Path | None = None,
    ts: str | None = None,
) -> Path:
    """Snapshot ``source_db`` into ``dest_dir`` using the online backup API.

    The filename is ``<label>-<timestamp>.db``. ``ts`` may be supplied for
    deterministic tests. Returns the path to the created backup.
    """
    source_db = Path(source_db)
    if not source_db.exists():
        raise FileNotFoundError(f"Source database not found: {source_db}")
    dest_dir = Path(dest_dir) if dest_dir else backups_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{label}-{ts or _timestamp()}.db"

    source_conn = sqlite3.connect(str(source_db))
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            with dest_conn:
                source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()

    logger.info("Created database backup %s", dest.name)
    return dest


def verify_backup(backup_path: Path, expected_min_holdings: int | None = None) -> bool:
    """Return True only if ``backup_path`` is a healthy, non-empty SQLite file.

    Runs ``PRAGMA integrity_check`` and, when ``expected_min_holdings`` is given,
    confirms the ``holdings`` table has at least that many rows. A missing
    holdings table counts as valid only when zero rows are expected (a fresh DB).
    """
    backup_path = Path(backup_path)
    if not backup_path.exists() or backup_path.stat().st_size == 0:
        return False

    conn = sqlite3.connect(str(backup_path))
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            return False
        if expected_min_holdings is not None:
            try:
                count = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
            except sqlite3.OperationalError:
                return expected_min_holdings == 0
            return count >= expected_min_holdings
        return True
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()


def restore_backup(backup_path: Path, target_db: Path, ts: str | None = None) -> bool:
    """Restore ``backup_path`` over ``target_db`` without destroying the current file.

    Refuses to restore an unverified backup. The existing database and its WAL
    sidecars are moved aside as ``*.failed-<timestamp>`` before the verified
    backup is copied into place. Returns True on success.
    """
    backup_path = Path(backup_path)
    target_db = Path(target_db)
    if not verify_backup(backup_path):
        raise ValueError("Refusing to restore an unverified backup")

    stamp = ts or _timestamp()
    for suffix in ("", "-wal", "-shm"):
        current = Path(str(target_db) + suffix)
        if current.exists():
            current.replace(Path(f"{current}.failed-{stamp}"))

    target_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup_path, target_db)
    logger.info("Restored database from backup %s", backup_path.name)
    return True


def prune_backups(dest_dir: Path | None = None, keep: int = DEFAULT_KEEP) -> list[Path]:
    """Delete all but the ``keep`` most recent backups. Returns removed paths."""
    dest_dir = Path(dest_dir) if dest_dir else backups_dir()
    if not dest_dir.exists():
        return []
    backups = sorted(dest_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed: list[Path] = []
    for old in backups[keep:]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            logger.warning("Could not prune old backup %s", old.name)
    return removed
