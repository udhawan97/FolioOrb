# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
"""Download → verify → ready orchestration and the OS install handoff.

The downloader functions are stubbed so the state-machine flow is exercised
without the network; subprocess and the exit hook are stubbed so the handoff is
asserted without launching anything or quitting the process.
"""
from pathlib import Path
import hashlib

import pytest

from app import paths
from app.services import update_downloader, update_installer, update_service
from app.services.update_service import UpdateStatus


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    # This file tests the install() orchestration itself, not the frozen-build
    # guard (covered separately by test_install_refuses_when_not_frozen) — the
    # tests run under pytest, which is never a frozen PyInstaller build.
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    update_service._reset_for_tests()
    update_installer._reset_for_tests()
    yield
    update_service._reset_for_tests()
    update_installer._reset_for_tests()


def _info():
    return {
        "version": "4.4.0",
        "asset_name": "FolioOrb-macOS-arm64-v4.4.0.dmg",
        "download_url": "https://github.com/x/releases/download/v4.4.0/app.dmg",
        "sha256_url": "https://github.com/x/releases/download/v4.4.0/SHA256SUMS.txt",
        "size_bytes": 4,
    }


def _stub_download(monkeypatch, contents=b"data"):
    def fake_dl(url, dest, on_progress=None, should_cancel=None):
        Path(dest).write_bytes(contents)
        if on_progress:
            on_progress(len(contents), len(contents))
        return Path(dest)

    monkeypatch.setattr(update_downloader, "download_update", fake_dl)
    monkeypatch.setattr(update_downloader, "fetch_text", lambda url:
                        f"{hashlib.sha256(contents).hexdigest()}  {_info()['asset_name']}")


def _ready_installer(tmp_path):
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"installer")
    update_installer._rt.update(
        path=installer, sha256=update_downloader.compute_sha256(installer),
    )
    update_service.mark(UpdateStatus.READY)
    return installer


def test_run_success_reaches_ready(monkeypatch):
    _stub_download(monkeypatch)
    monkeypatch.setattr(update_downloader, "verify_download", lambda p, s, f: True)

    update_installer._run(_info())

    assert update_service.get_state()["status"] == "ready"
    assert update_installer._rt["path"] is not None
    assert update_installer._rt["path"].exists()


def test_run_verify_failure_discards_and_errors(monkeypatch):
    _stub_download(monkeypatch)
    monkeypatch.setattr(update_downloader, "verify_download", lambda p, s, f: False)

    update_installer._run(_info())

    st = update_service.get_state()
    assert st["status"] == "error"
    assert update_installer._rt["path"] is None
    # The unverified file was removed.
    assert not (update_downloader.pending_dir() / _info()["asset_name"]).exists()


def test_run_rejects_bad_signature(monkeypatch):
    from app.services import signature_service

    info = _info()
    info["sha256_sig_url"] = "https://github.com/x/releases/download/v4.4.0/SHA256SUMS.txt.minisig"
    _stub_download(monkeypatch)
    monkeypatch.setattr(signature_service, "is_configured", lambda: True)
    monkeypatch.setattr(signature_service, "verify_manifest", lambda content, sig, **k: False)

    update_installer._run(info)

    st = update_service.get_state()
    assert st["status"] == "error"
    assert "signature" in st["error"].lower()
    assert update_installer._rt["path"] is None
    # The file is discarded when its signature can't be trusted.
    assert not (update_downloader.pending_dir() / info["asset_name"]).exists()


def test_run_cancel_returns_to_available(monkeypatch):
    def cancel_dl(url, dest, on_progress=None, should_cancel=None):
        raise update_downloader.DownloadCancelled()

    monkeypatch.setattr(update_downloader, "download_update", cancel_dl)
    update_installer._run(_info())
    assert update_service.get_state()["status"] == "available"


def test_launch_installer_windows_is_silent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(update_installer.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(update_service, "current_platform_key", lambda: "windows")

    installer = _ready_installer(tmp_path)
    update_installer._launch_installer(installer, update_installer._rt["sha256"])

    args = calls[0][0][0]
    assert "/VERYSILENT" in args and "/SUPPRESSMSGBOXES" in args


def test_launch_installer_macos_uses_bundle_swap(tmp_path, monkeypatch):
    """When running as a real .app, macOS installs via the bundle swap — it must
    NOT degrade to merely opening the DMG / releases page."""
    from app.services import macos_updater

    swapped = []
    monkeypatch.setattr(macos_updater, "launch_swap", lambda dmg, digest:
                        swapped.append((dmg, digest)) or True)
    opened = []
    monkeypatch.setattr(update_installer.subprocess, "Popen", lambda *a, **k: opened.append(a))
    monkeypatch.setattr(update_service, "current_platform_key", lambda: "macos")

    installer = _ready_installer(tmp_path)
    digest = update_installer._rt["sha256"]
    update_installer._launch_installer(installer, digest)

    assert swapped == [(installer, digest)]
    assert not opened  # did not fall back to `open`


def test_launch_installer_macos_falls_back_when_not_a_bundle(tmp_path, monkeypatch):
    """Dev/source run (not a .app): fall back to opening the DMG for manual install."""
    from app.services import macos_updater

    monkeypatch.setattr(macos_updater, "launch_swap", lambda dmg, digest: False)
    calls = []
    monkeypatch.setattr(update_installer.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(update_service, "current_platform_key", lambda: "macos")

    installer = _ready_installer(tmp_path)
    update_installer._launch_installer(installer, update_installer._rt["sha256"])

    assert calls[0][0][0][0] == "open"


def test_install_requires_ready_state():
    # Idle → nothing happens.
    assert update_installer.install()["status"] != "installing"


def test_install_refuses_when_not_frozen(monkeypatch):
    """A dev/web-mode server must refuse install() even if called directly."""
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    update_service.mark(UpdateStatus.READY)
    update_installer._rt["path"] = Path("/x/Setup.exe")
    launched = []
    monkeypatch.setattr(update_installer, "_launch_installer", lambda p, digest: launched.append(p))

    st = update_installer.install()

    assert st["status"] == "error"
    assert "packaged app" in st["error"].lower()
    assert not launched


def _setup_file_db(tmp_path, monkeypatch):
    import sqlite3

    from app.config import settings

    db = tmp_path / "portfolio.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db.as_posix()}")
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE holdings (id INTEGER PRIMARY KEY, ticker TEXT)")
    conn.execute("INSERT INTO holdings (ticker) VALUES ('VOO')")
    conn.commit()
    conn.close()
    return db


def test_install_creates_verified_backup_and_rollback_point(tmp_path, monkeypatch):
    from app import app_settings
    from app.services import backup_service

    _setup_file_db(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")
    _ready_installer(tmp_path)
    monkeypatch.setattr(update_installer, "_launch_installer", lambda p, digest: None)

    st = update_installer.install()

    assert st["status"] == "installing"
    # pylint infers "rollback_point" as the DEFAULTS literal's static None type
    # and flags subscripting it; the runtime value is the merged dict set by
    # save_settings() above.
    # pylint: disable=unsubscriptable-object
    rollback_point = app_settings.load_settings()["rollback_point"]
    assert rollback_point is not None
    assert Path(rollback_point["db_backup"]).exists()
    assert backup_service.verify_backup(Path(rollback_point["db_backup"]), expected_min_holdings=1)
    assert rollback_point["env_backup"] and Path(rollback_point["env_backup"]).exists()
    assert rollback_point["version"]
    # pylint: enable=unsubscriptable-object


def test_install_rejects_backup_that_silently_lost_holdings(tmp_path, monkeypatch):
    """Regression: verification must use the DB's real count, not a hardcoded 0.

    A hardcoded expected_min_holdings=0 would accept a corrupted backup that
    ended up with zero (or no) holdings even though the live DB has one — this
    proves the fix catches exactly that case instead of proceeding to install.
    """
    from app.services import backup_service

    _setup_file_db(tmp_path, monkeypatch)
    _ready_installer(tmp_path)
    launched = []
    monkeypatch.setattr(update_installer, "_launch_installer", lambda p, digest: launched.append(p))

    def _empty_backup(
        source_db, label, dest_dir=None, ts=None, expected_min_holdings=None
    ):
        # Simulate a backup that "succeeded" but lost the holdings table.
        dest_dir = dest_dir or backup_service.backups_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        empty = dest_dir / f"{label}-corrupt.db"
        import sqlite3

        conn = sqlite3.connect(str(empty))
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()
        return empty

    monkeypatch.setattr(backup_service, "create_backup", _empty_backup)

    st = update_installer.install()

    assert st["status"] == "error"
    assert not launched


def test_install_aborts_when_backup_fails(tmp_path, monkeypatch):
    from app.services import backup_service

    _setup_file_db(tmp_path, monkeypatch)
    _ready_installer(tmp_path)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(backup_service, "create_backup", boom)
    launched = []
    monkeypatch.setattr(update_installer, "_launch_installer", lambda p, digest: launched.append(p))

    st = update_installer.install()

    assert st["status"] == "error"
    assert not launched  # never hand off without a verified backup


def test_install_aborts_when_rollback_point_cannot_be_recorded(tmp_path, monkeypatch):
    from app import app_settings

    _setup_file_db(tmp_path, monkeypatch)
    _ready_installer(tmp_path)

    def refuse_settings(_changes):
        raise OSError("Fixture settings disk full")

    monkeypatch.setattr(app_settings, "save_settings", refuse_settings)
    monkeypatch.setattr(update_installer.subprocess, "Popen", lambda *a, **k:
                        pytest.fail("No installation without a recorded recovery point"))
    assert update_installer.install()["status"] == "error"


def test_install_launches_and_schedules_exit(tmp_path, monkeypatch):
    installer = _ready_installer(tmp_path)
    # Focus on handoff + exit scheduling; backup is covered by its own tests.
    monkeypatch.setattr(update_installer, "_create_rollback_point", lambda: {"version": "4.3.4"})

    launched = {}
    monkeypatch.setattr(
        update_installer, "_launch_installer", lambda p, digest: launched.setdefault("p", p)
    )

    fired = {}

    class FakeTimer:
        def __init__(self, delay, func):
            fired["func"] = func

        def start(self):
            fired["started"] = True

    monkeypatch.setattr(update_installer.threading, "Timer", FakeTimer)
    quit_calls = []
    update_installer.register_exit_hook(lambda: quit_calls.append(1))

    st = update_installer.install()

    assert st["status"] == "installing"
    assert launched["p"] == installer
    assert fired["started"] is True
    # The scheduled callback is the registered exit hook.
    fired["func"]()
    assert quit_calls == [1]


@pytest.mark.parametrize("change", ["replace", "delete"])
def test_install_refuses_changed_ready_bytes(tmp_path, monkeypatch, change):
    installer = _ready_installer(tmp_path)
    if change == "replace":
        installer.write_bytes(b"changed after verification")
    else:
        installer.unlink()
    monkeypatch.setattr(update_installer, "_create_rollback_point", lambda:
                        pytest.fail("Changed bytes must be refused before backup"))
    monkeypatch.setattr(update_installer.subprocess, "Popen", lambda *a, **k:
                        pytest.fail("Changed bytes must never be launched"))
    assert update_installer.install()["status"] == "error"
    assert update_installer._rt["path"] is None


def test_install_rechecks_after_backup(tmp_path, monkeypatch):
    installer = _ready_installer(tmp_path)

    def backup_changes_file():
        installer.write_bytes(b"changed during backup")
        return {"version": "4.3.4"}

    monkeypatch.setattr(update_installer, "_create_rollback_point", backup_changes_file)
    monkeypatch.setattr(update_installer.subprocess, "Popen", lambda *a, **k:
                        pytest.fail("Changed bytes must never be launched"))
    assert update_installer.install()["status"] == "error"
