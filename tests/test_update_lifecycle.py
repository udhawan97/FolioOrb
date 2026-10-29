"""Contending updater requests preserve the one operation already in progress."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
import hashlib
import threading

import pytest

from app import paths
from app.services import rollback_service, update_downloader, update_installer, update_service
from app.services.update_service import UpdateInfo, UpdateStatus


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    update_service._reset_for_tests()
    update_installer._reset_for_tests()
    yield
    update_service._reset_for_tests()
    update_installer._reset_for_tests()


def _available():
    info = UpdateInfo(
        version="9.9.9", name="fixture", published_at=None, notes_md="", channel="stable",
        release_url=None, download_url="fixture-download", asset_name="fixture.dmg",
        size_bytes=4, sha256_url="fixture-sums", sha256_sig_url=None,
    )
    update_service.mark(UpdateStatus.AVAILABLE, available=info)
    return info


def test_active_download_rejects_repeated_rollback_install_and_check(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    info = _available()

    def download(_url, destination, on_progress, should_cancel):
        destination.write_bytes(b"data")
        on_progress(2, 4)
        entered.set()
        assert release.wait(5), "Test did not release the download"

    monkeypatch.setattr(update_downloader, "download_update", download)
    monkeypatch.setattr(update_downloader, "fetch_text", lambda _url:
                        f"{hashlib.sha256(b'data').hexdigest()}  {info.asset_name}")
    monkeypatch.setattr(rollback_service, "_rollback_point", lambda:
                        pytest.fail("Conflicting rollback reached backup lookup"))
    monkeypatch.setattr(update_service, "_http_get", lambda *args:
                        pytest.fail("Busy check must not fetch metadata"))
    update_installer.start_download()
    worker = update_installer._rt["thread"]
    try:
        assert entered.wait(5)
        before = update_service.get_state()
        for _ in range(2):
            assert rollback_service.rollback() == before
            assert update_installer.install() == before
            assert update_service.check_for_updates(force=True) == before
        assert before["downloaded_bytes"] == 2
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert update_service.get_state()["status"] == "ready"
    assert update_service.check_for_updates(force=True)["status"] == "ready"


def test_simultaneous_rollbacks_start_only_one_backup_and_handoff(tmp_path, monkeypatch):
    gate = threading.Barrier(3)
    entered = threading.Event()
    release = threading.Event()
    installer = tmp_path / "previous.exe"
    installer.write_bytes(b"previous")
    backups = []
    launched = []
    failures = []
    monkeypatch.setattr(rollback_service, "_rollback_point", lambda: {"db_backup": "fixture"})

    def backup(**_kwargs):
        backups.append(True)
        entered.set()
        assert release.wait(5), "Test did not release the backup"

    monkeypatch.setattr(rollback_service.backup_service, "create_verified_backup", backup)
    monkeypatch.setattr(rollback_service, "_resolve_previous_installer", lambda _point:
                        (installer, update_downloader.compute_sha256(installer)))
    monkeypatch.setattr(update_installer, "launch_installer", lambda path, digest:
                        launched.append((path, digest)))
    monkeypatch.setattr(update_installer, "schedule_exit", lambda: None)

    def rollback():
        try:
            gate.wait(5)
            rollback_service.rollback()
        except Exception as exc:  # pylint: disable=broad-except
            failures.append(exc)

    workers = [threading.Thread(target=rollback) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        gate.wait(5)
        assert entered.wait(5)
        assert update_service.check_for_updates()["status"] == "backing_up"
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
    assert not failures
    assert not any(worker.is_alive() for worker in workers)
    assert len(backups) == len(launched) == 1
    assert update_service.get_state()["status"] == "installing"


def test_fast_download_completion_is_not_overwritten_by_start(monkeypatch):
    info = _available()

    class ImmediateThread:
        def __init__(self, target, args, **_kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

        def is_alive(self):
            return False

    monkeypatch.setattr(update_installer.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(update_downloader, "download_update", lambda _url, path, **_kwargs:
                        path.write_bytes(b"data"))
    monkeypatch.setattr(update_downloader, "fetch_text", lambda _url:
                        f"{hashlib.sha256(b'data').hexdigest()}  {info.asset_name}")
    assert update_installer.start_download()["status"] == "ready"


def test_checks_own_state_until_metadata_returns(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def offline(_url, _headers):
        entered.set()
        assert release.wait(5)
        raise update_service.UpdateOffline()

    monkeypatch.setattr(update_service, "_http_get", offline)
    worker = threading.Thread(target=update_service.check_for_updates)
    worker.start()
    try:
        assert entered.wait(5)
        before = update_service.get_state()
        assert before["status"] == "checking"
        assert update_service.check_for_updates() == before
        assert rollback_service.rollback() == before
        assert update_installer.start_download() == before
    finally:
        release.set()
        worker.join(5)
    assert update_service.get_state()["status"] == "offline"
