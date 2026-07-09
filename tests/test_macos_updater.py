# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
"""macOS bundle-swap in-app updater: bundle detection, script handoff, markers.

No real DMG is mounted and nothing is executed — subprocess.Popen is stubbed and
the swap script is only inspected as text.
"""
import pytest

from app import paths
from app.services import macos_updater


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path


def test_bundle_path_detects_app(monkeypatch):
    monkeypatch.setattr(
        macos_updater.sys, "executable",
        "/Applications/FolioOrb.app/Contents/MacOS/FolioOrb",
    )
    assert str(macos_updater.bundle_path()).endswith("/Applications/FolioOrb.app")


def test_bundle_path_none_when_not_app(monkeypatch):
    monkeypatch.setattr(macos_updater.sys, "executable", "/usr/local/bin/python3")
    assert macos_updater.bundle_path() is None


def test_launch_swap_writes_script_and_detaches(tmp_path, monkeypatch):
    bundle = tmp_path / "FolioOrb.app"
    bundle.mkdir()
    monkeypatch.setattr(macos_updater, "bundle_path", lambda: bundle)
    calls = []
    monkeypatch.setattr(macos_updater.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))

    dmg = tmp_path / "updates" / "pending" / "app.dmg"
    dmg.parent.mkdir(parents=True)
    dmg.write_bytes(b"dmg")

    assert macos_updater.launch_swap(dmg) is True

    # Detached, launched via bash with the right args.
    args, kwargs = calls[0]
    argv = args[0]
    assert argv[0] == "/bin/bash"
    assert str(dmg) in argv and str(bundle) in argv
    assert kwargs.get("start_new_session") is True

    # The script exists and contains the real swap steps — and never touches the
    # user data directory (DB/.env live outside the bundle).
    script = (tmp_path / "updates" / "macos-swap.sh").read_text()
    for needle in ("hdiutil attach", "ditto", "/bin/mv", "/usr/bin/open", "last-update-failed"):
        assert needle in script, needle
    assert "database" not in script and ".env" not in script


def test_launch_swap_false_when_not_a_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(macos_updater, "bundle_path", lambda: None)
    assert macos_updater.launch_swap(tmp_path / "x.dmg") is False


def test_consume_failed_marker(tmp_path):
    markers = tmp_path / "updates"
    markers.mkdir(parents=True)
    # No markers → not a failure.
    assert macos_updater.consume_failed_marker() is False
    # Failed marker present → failure, and cleared afterwards.
    (markers / macos_updater.FAILED_MARKER).touch()
    assert macos_updater.consume_failed_marker() is True
    assert macos_updater.consume_failed_marker() is False


def test_ok_marker_newer_than_failed_is_not_a_failure(tmp_path):
    import os
    import time

    markers = tmp_path / "updates"
    markers.mkdir(parents=True)
    (markers / macos_updater.FAILED_MARKER).touch()
    ok = markers / macos_updater.OK_MARKER
    ok.touch()
    os.utime(ok, (time.time() + 10, time.time() + 10))  # ok is newer
    assert macos_updater.consume_failed_marker() is False
