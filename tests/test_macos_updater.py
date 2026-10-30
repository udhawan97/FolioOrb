# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
"""macOS bundle-swap in-app updater: bundle detection, script handoff, markers.

No real DMG is mounted or app launched. Handoffs are stubbed; helper execution
replaces mount, process-wait and open commands with disposable fixture scripts.
"""
import hashlib
import os
import subprocess
from pathlib import Path

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

    digest = hashlib.sha256(b"dmg").hexdigest()
    assert macos_updater.launch_swap(dmg, digest) is True

    # Detached, launched via bash with the right args.
    args, kwargs = calls[0]
    argv = args[0]
    assert argv[0] == "/bin/bash"
    assert str(dmg) in argv and str(bundle) in argv
    assert argv[-1] == digest
    assert kwargs.get("start_new_session") is True

    # The script exists and contains the real swap steps — and never touches the
    # user data directory (DB/.env live outside the bundle).
    script = (tmp_path / "updates" / "macos-swap.sh").read_text()
    for needle in ("hdiutil attach", "ditto", "/bin/mv", "/usr/bin/open", "last-update-failed"):
        assert needle in script, needle
    assert "database" not in script and ".env" not in script


def test_launch_swap_false_when_not_a_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(macos_updater, "bundle_path", lambda: None)
    assert macos_updater.launch_swap(tmp_path / "x.dmg", "0" * 64) is False


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
    import time

    markers = tmp_path / "updates"
    markers.mkdir(parents=True)
    (markers / macos_updater.FAILED_MARKER).touch()
    ok = markers / macos_updater.OK_MARKER
    ok.touch()
    os.utime(ok, (time.time() + 10, time.time() + 10))  # ok is newer
    assert macos_updater.consume_failed_marker() is False


@pytest.mark.parametrize("change", ["unchanged", "replace", "delete"])
@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="Requires Bash updater helper")
def test_helper_checks_trusted_digest_after_wait_before_mount(tmp_path, change):
    """Run the real helper with only process-wait/mount/open commands stubbed."""
    dmg = tmp_path / "installer.dmg"
    dmg.write_bytes(b"verified")
    digest = hashlib.sha256(b"verified").hexdigest()
    bundle = tmp_path / "FolioOrb.app"
    bundle.mkdir()
    trace = tmp_path / "mount.log"
    commands = {
        "/usr/bin/hdiutil": 'printf mounted >> "$FIXTURE_TRACE"\nexit 1\n',
        "/usr/bin/open": "exit 0\n",
        "/bin/kill": {
            "unchanged": "exit 1\n",
            "replace": 'printf changed > "$FIXTURE_DMG"\nexit 1\n',
            "delete": '/bin/rm "$FIXTURE_DMG"\nexit 1\n',
        }[change],
    }
    source = macos_updater._SWAP_SCRIPT
    for index, (command, body) in enumerate(commands.items()):
        stub = tmp_path / f"command-{index}"
        stub.write_text("#!/bin/bash\n" + body)
        stub.chmod(0o755)
        source = source.replace(command, str(stub))
    script = tmp_path / "swap.sh"
    script.write_text(source)
    env = dict(os.environ, FIXTURE_DMG=str(dmg), FIXTURE_TRACE=str(trace))
    logs, markers = tmp_path / "logs", tmp_path / "markers"
    result = subprocess.run(
        ["/bin/bash", str(script), str(dmg), str(bundle), "fixture-pid",
         str(logs), str(markers), digest],
        env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 1
    assert (markers / macos_updater.FAILED_MARKER).exists()
    assert trace.exists() == (change == "unchanged")
    log = (logs / "macos-update.log").read_text()
    failure = "mount" if change == "unchanged" else "checksum-"
    assert f"FAILED: {failure}" in log
    assert bundle.is_dir()
