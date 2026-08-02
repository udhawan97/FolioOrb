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
from datetime import datetime, timezone
from pathlib import Path

from app import paths

logger = logging.getLogger(__name__)

BACKUP_DIRNAME = "backups"
DEFAULT_KEEP = 5
MANUAL_KEEP = 12


def backups_dir(*, create: bool = True) -> Path:
    """Return the backup-vault directory, optionally creating it.

    Inventory and download paths pass ``create=False`` so merely opening the
    Backup Vault never changes the filesystem. Snapshot-producing paths keep
    the default and create the directory on first write.
    """
    directory = paths.data_dir() / BACKUP_DIRNAME
    if create:
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


def resolve_backup_name(name: str) -> Path:
    """Resolve one vault basename without allowing path traversal."""
    raw = str(name or "").strip()
    safe = Path(raw).name
    if not raw or safe != raw or not safe.endswith(".db"):
        raise ValueError("Invalid backup name")
    vault = backups_dir(create=False).resolve()
    path = (vault / safe).resolve()
    if path.parent != vault:
        raise ValueError("Invalid backup name")
    return path


def _vault_connection(path: Path) -> sqlite3.Connection:
    """Open one stable vault artifact without creating SQLite sidecars.

    ``immutable=1`` is intentionally confined to closed backup artifacts. It
    must never be used for the live database, whose committed state may still
    reside in WAL. A non-empty sibling WAL means the artifact is not standalone
    and is therefore refused rather than read incompletely.
    """
    path = Path(path)
    wal = Path(f"{path}-wal")
    if wal.exists() and wal.stat().st_size > 0:
        raise sqlite3.DatabaseError("Backup has an uncommitted WAL sidecar")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _count_vault_holdings(db_path: Path) -> int:
    """Count holdings in a closed vault artifact without mutating it."""
    db_path = Path(db_path)
    if not db_path.exists():
        return 0
    try:
        conn = _vault_connection(db_path)
    except (OSError, sqlite3.DatabaseError):
        return 0
    try:
        return conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    except sqlite3.DatabaseError:
        return 0
    finally:
        conn.close()


def backup_info(path: Path) -> dict:
    """Public, secret-free metadata for one database backup."""
    path = Path(path)
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "created_at": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "verified": verify_vault_backup(path),
        "holding_count": _count_vault_holdings(path),
    }


def list_backups() -> list[dict]:
    """Newest-first inventory of the local database vault."""
    vault = backups_dir(create=False)
    if not vault.exists():
        return []
    backup_paths = sorted(
        vault.glob("*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return [backup_info(path) for path in backup_paths]


def create_manual_backup() -> dict:
    """Create and verify a user-requested database-only vault snapshot."""
    source = live_db_path()
    expected = count_holdings(source)
    backup = create_backup(source, label="manual")
    if (
        not verify_backup(backup, expected_min_holdings=expected)
        or not verify_vault_backup(backup)
    ):
        _safe_remove(backup)
        raise ValueError("Backup verification failed")
    # A user-created snapshot must never evict an update or pre-restore rollback
    # point. Apply its larger retention window only to other manual snapshots.
    prune_backups(keep=MANUAL_KEEP, pattern="manual-*.db")
    return backup_info(backup)


def queue_restore(name: str) -> dict:
    """Verify a vault item and queue it for the next clean process start."""
    from app import app_settings

    backup = resolve_backup_name(name)
    if not verify_vault_backup(backup):
        raise ValueError("Refusing to queue an unverified backup")
    requested_at = datetime.now(timezone.utc).isoformat()
    pending = {"name": backup.name, "requested_at": requested_at}
    app_settings.save_settings({"pending_db_restore": pending})
    return pending


def apply_pending_restore() -> dict | None:
    """Apply a queued restore before the database engine is imported.

    The current database gets its own verified safety backup first. A failed
    request is cleared so one bad vault item cannot trap the app in a startup
    loop; the live file remains untouched on every pre-swap failure.
    """
    from app import app_settings

    settings = app_settings.load_settings()
    pending = settings.get("pending_db_restore")
    if not isinstance(pending, dict) or not pending.get("name"):
        return None

    now = datetime.now(timezone.utc).isoformat()
    try:
        requested = resolve_backup_name(str(pending["name"]))
        if not verify_vault_backup(requested):
            raise ValueError("Queued backup failed verification")
        live = live_db_path()
        safety_name = None
        if live.exists():
            expected = count_holdings(live)
            safety = create_backup(live, label="pre-manual-restore")
            if not verify_backup(safety, expected_min_holdings=expected):
                _safe_remove(safety)
                raise ValueError("Safety backup failed verification")
            safety_name = safety.name
        restore_backup(requested, live)
        result = {
            "status": "restored",
            "name": requested.name,
            "safety_backup": safety_name,
            "completed_at": now,
        }
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Queued database restore failed: %s", type(exc).__name__)
        result = {
            "status": "failed",
            "name": str(pending.get("name") or ""),
            "error": type(exc).__name__,
            "completed_at": now,
        }
    app_settings.save_settings({
        "pending_db_restore": None,
        "last_db_restore": result,
    })
    return result


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

    conn = None
    try:
        conn = _vault_connection(backup_path)
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
    except (OSError, sqlite3.DatabaseError):
        return False
    finally:
        if conn is not None:
            conn.close()


def verify_vault_backup(backup_path: Path) -> bool:
    """Require both SQLite integrity and FolioOrb's holdings schema."""
    backup_path = Path(backup_path)
    if not verify_backup(backup_path):
        return False
    try:
        conn = _vault_connection(backup_path)
    except (OSError, sqlite3.DatabaseError):
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='holdings'"
        ).fetchone()
        return row is not None
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()


def restore_backup(backup_path: Path, target_db: Path, ts: str | None = None) -> bool:
    """Restore ``backup_path`` over ``target_db`` without destroying the current file.

    Refuses to restore an unverified backup. The backup is first copied to a
    staging file and re-verified there — only once that copy is confirmed intact
    are the existing database and its WAL sidecars moved aside as
    ``*.failed-<timestamp>`` and the staged copy swapped into place. This way a
    failed copy (disk full, interrupted process) never leaves the live database
    missing with no verified replacement ready — it's untouched instead.
    Returns True on success.
    """
    backup_path = Path(backup_path)
    target_db = Path(target_db)
    if not verify_backup(backup_path):
        raise ValueError("Refusing to restore an unverified backup")

    stamp = ts or _timestamp()
    target_db.parent.mkdir(parents=True, exist_ok=True)
    staging = target_db.parent / f"{target_db.name}.staging-{stamp}"
    shutil.copyfile(backup_path, staging)
    if not verify_backup(staging):
        _safe_remove(staging)
        raise ValueError("Restored copy failed verification — live database left untouched")

    for suffix in ("", "-wal", "-shm"):
        current = Path(str(target_db) + suffix)
        if current.exists():
            current.replace(Path(f"{current}.failed-{stamp}"))

    staging.replace(target_db)
    logger.info("Restored database from backup %s", backup_path.name)
    return True


def _safe_remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError as exc:
        logger.debug("Could not remove staging file %s: %s", path.name, type(exc).__name__)


def prune_backups(
    dest_dir: Path | None = None,
    keep: int = DEFAULT_KEEP,
    *,
    pattern: str = "*.db",
) -> list[Path]:
    """Delete all but the ``keep`` newest matching backups.

    The optional pattern keeps independently managed classes of rollback point
    from evicting one another.
    """
    dest_dir = Path(dest_dir) if dest_dir else backups_dir()
    if not dest_dir.exists():
        return []
    backups = sorted(
        dest_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
    )
    removed: list[Path] = []
    for old in backups[keep:]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            logger.warning("Could not prune old backup %s", old.name)
    return removed
