"""Static contracts keep every supported launcher on one owned runtime profile."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CANONICAL_DATABASE_URL = "DATABASE_URL=sqlite:///./database/portfolio.db"


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_source_setup_and_installers_keep_historical_canonical_database_url():
    for relative in (
        ".env.example",
        "scripts/setup.sh",
        "scripts/setup.ps1",
        "scripts/install-mac.sh",
        "scripts/install-win.ps1",
    ):
        assert CANONICAL_DATABASE_URL in _text(relative), relative


def test_ci_and_release_pair_noncanonical_databases_with_isolated_data_roots():
    for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
        content = _text(relative)
        assert "FOLIOORB_DATA_DIR" in content, relative
        assert "RUNNER_TEMP" in content, relative
        assert "DATABASE_URL" in content, relative


def test_demo_and_capture_scripts_pair_database_with_disposable_data_root():
    for relative in ("docs-site/scripts/record_demos.sh", "docs-site/scripts/capture.sh"):
        content = _text(relative)
        assert "mktemp -d" in content, relative
        assert 'export FOLIOORB_DATA_DIR="$TMP_DIR/data"' in content, relative
        assert "DATABASE_URL" in content, relative

    seed_help = _text("docs-site/scripts/seed_demo.py")
    assert "FOLIOORB_DATA_DIR" in seed_help
    assert "DATABASE_URL" in seed_help

    record = _text("docs-site/scripts/record_demos.sh")
    assert 'RAW_DIR="$REPO_ROOT/docs-site/_demos/raw"' in record
    assert 'rm -rf -- "$RAW_DIR"' in record


def test_launchers_prepare_profile_before_restore_or_database_import():
    source_launcher = _text("run.py")
    assert source_launcher.index("prepare_runtime_profile") < source_launcher.index(
        "apply_pending_restore"
    )

    desktop_launcher = _text("desktop/main.py")
    assert desktop_launcher.index("prepare_runtime_profile") < desktop_launcher.index(
        "apply_pending_restore"
    )

    config = _text("app/config.py")
    assert "prepare_runtime_profile" in config


def test_desktop_duplicate_preflight_follows_pending_restore_and_precedes_server():
    desktop_launcher = _text("desktop/main.py")
    restore = desktop_launcher.index("backup_service.apply_pending_restore()")
    preflight = desktop_launcher.index("preflight_active_holding_uniqueness(engine)")
    server = desktop_launcher.index("threading.Thread(target=_run_server")

    assert restore < preflight < server


def test_desktop_duplicate_resolver_registers_an_explicit_native_bridge():
    desktop_launcher = _text("desktop/main.py")

    assert "window.expose(bridge.resolve_duplicates)" in desktop_launcher
    assert "window.addEventListener('pywebviewready', markReady)" in desktop_launcher


def test_packaged_release_runs_duplicate_recovery_smoke_on_both_platforms():
    workflow = _text(".github/workflows/release.yml")

    # Unsigned macOS/Windows builds are exercised before staging. The isolated
    # macOS signing job and Windows packaging job exercise the signed copies.
    assert workflow.count("--smoke-duplicate-recovery") == 4
    assert "dist/FolioOrb.app/Contents/MacOS/FolioOrb --smoke-duplicate-recovery" in workflow
    assert workflow.count('@("--smoke", "--smoke-duplicate-recovery")') == 2


def test_source_duplicate_recovery_smoke_exercises_real_backend():
    result = subprocess.run(
        [sys.executable, "desktop/main.py", "--smoke-duplicate-recovery"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Packaged duplicate recovery smoke passed" in result.stdout
