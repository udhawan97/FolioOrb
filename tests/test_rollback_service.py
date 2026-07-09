# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
"""Data-safe rollback: safety backup first, optional snapshot restore, relaunch.

Uses real on-disk SQLite so the backup/restore paths run end to end. The
installer launch is stubbed so nothing is actually executed.
"""
import sqlite3

import pytest

from app import app_settings, paths
from app.config import settings
from app.services import backup_service, rollback_service, update_installer, update_service
from app.services.update_service import UpdateStatus


def _seed_db(path, tickers):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE holdings (id INTEGER PRIMARY KEY, ticker TEXT)")
    conn.executemany("INSERT INTO holdings (ticker) VALUES (?)", [(t,) for t in tickers])
    conn.commit()
    conn.close()


def _holdings(path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT ticker FROM holdings ORDER BY id")]
    finally:
        conn.close()


@pytest.fixture
def rollback_env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    live = tmp_path / "portfolio.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{live.as_posix()}")
    _seed_db(live, ["NEW"])  # current (post-update) data

    # A pre-update snapshot the user could restore, plus an archived installer.
    snapshot = tmp_path / "backups" / "pre-update.db"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    _seed_db(snapshot, ["OLD"])
    archived = tmp_path / "updates" / "archive" / "Setup.exe"
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_text("installer")

    app_settings.save_settings({
        "rollback_point": {
            "version": "4.3.0",
            "db_backup": str(snapshot),
            "env_backup": None,
            "installer": str(archived),
            "created_at": "2026-07-08T00:00:00Z",
        }
    })
    update_service._reset_for_tests()
    launched = []
    monkeypatch.setattr(update_installer, "launch_installer", lambda p: launched.append(p))
    yield {"live": live, "archived": archived, "launched": launched, "tmp": tmp_path}
    update_service._reset_for_tests()


def test_can_rollback(rollback_env):
    assert rollback_service.can_rollback() is True
    app_settings.save_settings({"rollback_point": None})
    assert rollback_service.can_rollback() is False


def test_rollback_keeps_current_data_by_default(rollback_env):
    result = rollback_service.rollback(restore_data=False)

    assert result["status"] == "installing"
    assert rollback_env["launched"] == [rollback_env["archived"]]
    # Current data is untouched, and a pre-rollback safety backup was taken.
    assert _holdings(rollback_env["live"]) == ["NEW"]
    safety = list((rollback_env["tmp"] / "backups").glob("pre-rollback-*.db"))
    assert len(safety) == 1
    assert backup_service.verify_backup(safety[0], expected_min_holdings=1)


def test_rollback_can_restore_pre_update_snapshot(rollback_env):
    result = rollback_service.rollback(restore_data=True)

    assert result["status"] == "installing"
    # The pre-update snapshot is restored...
    assert _holdings(rollback_env["live"]) == ["OLD"]
    # ...and the current ("NEW") data is preserved in the pre-rollback safety copy.
    safety = list((rollback_env["tmp"] / "backups").glob("pre-rollback-*.db"))
    assert _holdings(safety[0]) == ["NEW"]


def test_rollback_aborts_if_safety_backup_fails(rollback_env, monkeypatch):
    monkeypatch.setattr(
        backup_service, "create_backup",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    result = rollback_service.rollback(restore_data=True)

    assert result["status"] == "error"
    assert rollback_env["launched"] == []          # never handed off
    assert _holdings(rollback_env["live"]) == ["NEW"]  # data untouched


def test_rollback_refuses_while_update_in_progress(rollback_env):
    """Regression: rollback must not run concurrently with an active download/install.

    Without this guard, the always-visible Restore button could be clicked
    mid-download and interleave writes with the download thread's state
    updates. The rollback point remains untouched and nothing is launched.
    """
    for busy_status in (
        UpdateStatus.DOWNLOADING, UpdateStatus.VERIFYING,
        UpdateStatus.BACKING_UP, UpdateStatus.INSTALLING,
    ):
        update_service.mark(busy_status)
        result = rollback_service.rollback(restore_data=False)
        assert result["status"] == "error"
        assert "already in progress" in result["error"].lower()
    assert rollback_env["launched"] == []


def test_rollback_safety_backup_rejects_lost_holdings(rollback_env, monkeypatch):
    """Regression: the pre-rollback safety backup must use the DB's real count.

    A hardcoded expected_min_holdings=0 would accept a "successful" backup that
    silently lost the holdings table — this proves the fix catches it and
    refuses to proceed with the rollback.
    """
    def _empty_backup(source_db, label, dest_dir=None, ts=None):
        dest_dir = dest_dir or backup_service.backups_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        empty = dest_dir / f"{label}-corrupt.db"
        conn = sqlite3.connect(str(empty))
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()
        return empty

    monkeypatch.setattr(backup_service, "create_backup", _empty_backup)

    result = rollback_service.rollback(restore_data=False)

    assert result["status"] == "error"
    assert rollback_env["launched"] == []
    assert _holdings(rollback_env["live"]) == ["NEW"]  # untouched


def test_rollback_without_installer_keeps_data_safe(rollback_env, monkeypatch):
    # Archived installer missing and no network to fetch the previous release.
    app_settings.save_settings({
        "rollback_point": {
            "version": "4.3.0", "db_backup": str(rollback_env["tmp"] / "backups" / "pre-update.db"),
            "env_backup": None, "installer": None, "created_at": "2026-07-08T00:00:00Z",
        }
    })
    monkeypatch.setattr(update_service, "fetch_release_info", lambda v: None)

    result = rollback_service.rollback(restore_data=True)

    assert result["status"] == "error"
    assert "data is safe" in result["error"].lower()
    # Data was still restored offline even though the binary couldn't be reinstalled.
    assert _holdings(rollback_env["live"]) == ["OLD"]
