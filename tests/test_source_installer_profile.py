"""Source-installer profiles survive code replacement outside the install tree."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
MIGRATOR = ROOT / "scripts" / "migrate_source_profile.py"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _run_migrator(
    source: Path, destination: Path, *, database_url: str | None = None
) -> subprocess.CompletedProcess[str]:
    # These fixtures model the current lease-aware launcher; legacy refusal is tested separately.
    if source.is_dir():
        (source / "run.py").write_text("backup_service.acquire_profile_lock()\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop("DATABASE_URL", None)
    if database_url is not None:
        environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [
            sys.executable,
            str(MIGRATOR),
            "--source",
            str(source),
            "--destination",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_migrator_preserves_complete_profile_and_live_wal(tmp_path):
    source = tmp_path / "FolioOrb"
    destination = tmp_path / "durable-profile"
    database_dir = source / "database"
    database_dir.mkdir(parents=True)

    connection = sqlite3.connect(database_dir / "portfolio.db")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE holdings (ticker TEXT NOT NULL)")
    connection.execute("INSERT INTO holdings VALUES ('DEMO')")
    connection.commit()

    (source / ".env").write_text("SECRET_KEY=demo\n", encoding="utf-8")
    (source / "settings.json").write_text('{"notify_updates": false}\n', encoding="utf-8")
    (source / "backup-policy.json").write_text(
        '{"auto_backup_enabled": true}\n', encoding="utf-8"
    )
    (source / "backups").mkdir()
    (source / "backups" / "manual.db").write_bytes(b"verified-backup")
    (source / "updates" / "pending").mkdir(parents=True)
    (source / "updates" / "pending" / "asset.part").write_bytes(b"partial")
    (source / "logs").mkdir()
    (source / "logs" / "updates.log").write_text("kept\n", encoding="utf-8")

    result = _run_migrator(source, destination)
    connection.close()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "MIGRATED"
    assert (destination / ".source-profile-v1").is_file()
    assert (destination / ".env").read_text(encoding="utf-8") == "SECRET_KEY=demo\n"
    assert (destination / "backups" / "manual.db").read_bytes() == b"verified-backup"
    assert (destination / "updates" / "pending" / "asset.part").read_bytes() == b"partial"
    with sqlite3.connect(destination / "database" / "portfolio.db") as migrated:
        assert migrated.execute("SELECT ticker FROM holdings").fetchone() == ("DEMO",)
        assert migrated.execute("PRAGMA quick_check").fetchone() == ("ok",)
    assert (source / "database" / "portfolio.db").is_file()


def test_migrator_fails_closed_when_both_profiles_have_data(tmp_path):
    source = tmp_path / "FolioOrb"
    destination = tmp_path / "durable-profile"
    source.mkdir()
    destination.mkdir()
    (source / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    (destination / "settings.json").write_text("{}\n", encoding="utf-8")

    result = _run_migrator(source, destination)

    assert result.returncode == 1
    assert "refusing to choose or overwrite either" in result.stderr
    assert (source / ".env").read_text(encoding="utf-8") == "SOURCE=1\n"
    assert (destination / "settings.json").read_text(encoding="utf-8") == "{}\n"
    assert not (destination / ".source-profile-v1").exists()


def test_migrator_marker_does_not_hide_a_later_source_conflict(tmp_path):
    source = tmp_path / "FolioOrb"
    destination = tmp_path / "durable-profile"
    source.mkdir()
    destination.mkdir()
    (destination / ".source-profile-v1").write_text("ready\n", encoding="utf-8")
    (source / ".env").write_text("SOURCE=1\n", encoding="utf-8")

    result = _run_migrator(source, destination)

    assert result.returncode == 1
    assert "refusing to choose or overwrite either" in result.stderr
    assert (source / ".env").is_file()


def test_migrator_honors_custom_relative_database_and_live_wal(tmp_path):
    source = tmp_path / "FolioOrb"
    destination = tmp_path / "durable-profile"
    database = source / "custom" / "wealth.db"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE holdings (ticker TEXT NOT NULL)")
    connection.execute("INSERT INTO holdings VALUES ('WAL')")
    connection.commit()
    (source / ".env").write_text(
        "DATABASE_URL=sqlite:///./custom/wealth.db\n", encoding="utf-8"
    )

    result = _run_migrator(source, destination)
    connection.close()

    assert result.returncode == 0, result.stderr
    with sqlite3.connect(destination / "custom" / "wealth.db") as migrated:
        assert migrated.execute("SELECT ticker FROM holdings").fetchone() == ("WAL",)


def test_migrator_process_database_url_precedes_dotenv(tmp_path):
    source = tmp_path / "FolioOrb"
    destination = tmp_path / "durable-profile"
    intended = source / "custom" / "intended.db"
    intended.parent.mkdir(parents=True)
    with sqlite3.connect(intended) as connection:
        connection.execute("CREATE TABLE proof (value TEXT)")
        connection.execute("INSERT INTO proof VALUES ('process')")
    (source / ".env").write_text(
        "DATABASE_URL=sqlite:///./custom/wrong.db\n", encoding="utf-8"
    )

    result = _run_migrator(
        source, destination, database_url="sqlite:///./custom/intended.db"
    )

    assert result.returncode == 0, result.stderr
    assert (destination / "custom" / "intended.db").is_file()
    assert not (destination / "custom" / "wrong.db").exists()
    assert "DATABASE_URL=sqlite:///./custom/intended.db" in (
        destination / ".env"
    ).read_text(encoding="utf-8")

    installed_source = tmp_path / "new-source"
    installed_source.mkdir()
    (installed_source / ".source-profile-path").write_text(
        f"{destination}\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment.pop("DATABASE_URL", None)
    environment.pop("FOLIOORB_DATA_DIR", None)
    script = (
        "import sys; from pathlib import Path; from app import paths; "
        "paths._source_root=lambda: Path(sys.argv[1]); "
        "print(paths.resolve_runtime_profile().database_path)"
    )
    next_launch = subprocess.run(
        (sys.executable, "-c", script, str(installed_source)),
        cwd=tmp_path,
        env={**environment, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert next_launch.stdout.strip() == str(destination / "custom" / "intended.db")


def test_migrator_fails_closed_for_absolute_database_url(tmp_path):
    source = tmp_path / "FolioOrb"
    destination = tmp_path / "durable-profile"
    source.mkdir()
    outside = tmp_path / "outside.db"
    with sqlite3.connect(outside) as connection:
        connection.execute("CREATE TABLE proof (value TEXT)")
    (source / ".env").write_text(
        f"DATABASE_URL=sqlite:///{outside.as_posix()}\n", encoding="utf-8"
    )

    result = _run_migrator(source, destination)

    assert result.returncode == 1
    assert "absolute legacy DATABASE_URL" in result.stderr
    assert outside.is_file()
    assert not destination.exists()


def test_migrator_fails_closed_when_configured_database_is_missing(tmp_path):
    source = tmp_path / "FolioOrb"
    destination = tmp_path / "durable-profile"
    source.mkdir()
    (source / ".env").write_text(
        "DATABASE_URL=sqlite:///./custom/missing.db\n", encoding="utf-8"
    )

    result = _run_migrator(source, destination)

    assert result.returncode == 1
    assert "configured legacy database is missing" in result.stderr
    assert (source / ".env").is_file()
    assert not destination.exists()


def test_installers_and_launchers_share_the_external_profile_contract():
    mac_installer = (ROOT / "scripts" / "install-mac.sh").read_text(encoding="utf-8")
    windows_installer = (ROOT / "scripts" / "install-win.ps1").read_text(encoding="utf-8")
    for content in (mac_installer, windows_installer):
        assert "migrate_source_profile.py" in content
        assert "--replace-source" in content
        assert ".source-install-migration-complete" in content
        assert "FOLIOORB_DATA_DIR" in content
        assert "v5.16.0" in content
        assert "main/scripts/migrate_source_profile.py" in content
    assert ".source-profile-path" in MIGRATOR.read_text(encoding="utf-8")

    assert '--replace-source "$EXTRACTED"' in mac_installer
    assert "prior source install was restored" in mac_installer.lower()
    assert "--replace-source $extracted.FullName" in windows_installer
    assert "prior source install was restored" in windows_installer.lower()
    assert "FolioOrb-source.cmd" in windows_installer

    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "Exercise Windows source installer and parser gate" in release_workflow
    assert "System.Management.Automation.Language.Parser" in release_workflow

    for relative in ("FolioOrb.command", "FolioOrb.bat", "scripts/start.sh", "scripts/start.ps1"):
        assert ".source-profile-path" in (ROOT / relative).read_text(encoding="utf-8")


@pytest.mark.skipif(POWERSHELL is None, reason="Requires a compatible PowerShell runtime")
@pytest.mark.parametrize("metadata", [
    "failure", "empty", "malformed", "main", "latest-main", "unsupported", "badref", "stable",
])
@pytest.mark.parametrize("explicit", [None, "main", "latest-main", "v5.16.1"])
def test_windows_installer_channel_resolution(tmp_path, metadata, explicit):
    """CI Windows runs the actual script with metadata/archive I/O denied by stubs."""
    wrapper = tmp_path / "fixture.ps1"
    wrapper.write_text("""$ErrorActionPreference = 'Stop'
function Invoke-RestMethod {
    param($Uri, [switch] $UseBasicParsing)
    Add-Content -LiteralPath $env:REQUEST_LOG -Value "metadata:$Uri"
    if ($env:METADATA -eq 'failure') { throw 'Fixture metadata failure' }
    if ($env:METADATA -eq 'empty') { return @{} }
    if ($env:METADATA -eq 'malformed') { return 'broken metadata' }
    if ($env:METADATA -eq 'main') { return @{ tag_name = 'main' } }
    if ($env:METADATA -eq 'latest-main') { return @{ tag_name = 'latest-main' } }
    if ($env:METADATA -eq 'unsupported') { return @{ tag_name = 'v5.15.0' } }
    if ($env:METADATA -eq 'badref') { return @{ tag_name = 'not-a-tag' } }
    return @{ tag_name = 'v5.16.1' }
}
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch] $UseBasicParsing)
    Add-Content -LiteralPath $env:REQUEST_LOG -Value "archive:$Uri"
    throw 'Fixture refuses archive download'
}
function py { & $env:FIXTURE_PYTHON @args }
& $env:FIXTURE_INSTALLER
""", encoding="utf-8")
    install, profile = tmp_path / "install", tmp_path / "profile"
    install.mkdir()
    profile.mkdir()
    (install / "keep.txt").write_bytes(b"existing code")
    (profile / "keep.txt").write_bytes(b"existing profile")
    shortcut, log = tmp_path / "shortcut.lnk", tmp_path / "requests.log"
    env = dict(os.environ)
    env.pop("FOLIO_REF", None)
    env.setdefault("LOCALAPPDATA", str(tmp_path / "unused-default"))
    env.update(
        REQUEST_LOG=str(log), METADATA=metadata, FIXTURE_PYTHON=sys.executable,
        FIXTURE_INSTALLER=str(ROOT / "scripts" / "install-win.ps1"),
        FOLIOORB_INSTALL_DIR=str(install), FOLIOORB_DATA_DIR=str(profile),
        FOLIOORB_SHORTCUT=str(shortcut), FOLIOORB_INSTALL_NO_START="1",
    )
    if explicit:
        env["FOLIO_REF"] = explicit
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(wrapper)],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode != 0  # Archive download is always refused.
    requests = log.read_text(encoding="utf-8-sig").splitlines()
    if explicit is None and metadata != "stable":
        assert len(requests) == 1
        assert ("latest stable release" in result.stderr or
                "Source installs support stable tags" in result.stderr)
    else:
        selected = explicit or "v5.16.1"
        archive = "heads/main" if selected == "main" else f"tags/{selected}"
        assert f"archive/refs/{archive}.zip" in requests[-1]
        assert len(requests) == (1 if explicit else 2)
    assert sorted(path.name for path in install.iterdir()) == ["keep.txt"]
    assert sorted(path.name for path in profile.iterdir()) == ["keep.txt"]
    assert (install / "keep.txt").read_bytes() == b"existing code"
    assert (profile / "keep.txt").read_bytes() == b"existing profile"
    assert not shortcut.exists()
