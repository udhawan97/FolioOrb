"""Source-installer profiles survive code replacement outside the install tree."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import venv
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import source_runtime


ROOT = Path(__file__).resolve().parent.parent
MIGRATOR = ROOT / "scripts" / "migrate_source_profile.py"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(POWERSHELL is None, reason="Requires a compatible PowerShell runtime")
@pytest.mark.parametrize("explicit", [None, "main"])
@pytest.mark.parametrize("relative", [False, True])
def test_windows_extraction_is_install_sibling_only_after_metadata_acceptance(
    tmp_path, explicit, relative,
):
    """System TEMP may be a different drive; no parent exists on metadata refusal."""
    log = tmp_path / "archive-path.txt"
    wrapper = tmp_path / "layout-fixture.ps1"
    wrapper.write_text("""$ErrorActionPreference = 'Stop'
function Invoke-RestMethod { param($Uri, [switch] $UseBasicParsing); throw 'metadata unavailable' }
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch] $UseBasicParsing)
    Set-Content -LiteralPath $env:REQUEST_LOG -Value $OutFile
    throw 'Fixture stops archive I/O'
}
function py { & $env:FIXTURE_PYTHON @args }
& $env:FIXTURE_INSTALLER
""", encoding="utf-8")
    install = tmp_path / "install" if relative else tmp_path / "new install parent" / "install"
    other_temp = tmp_path / "unrelated system temp"
    other_temp.mkdir()
    profile = tmp_path / "other profile"
    env = dict(os.environ)
    env.pop("FOLIO_REF", None)
    env.setdefault("LOCALAPPDATA", str(tmp_path / "unused default"))
    env.update(
        TEMP=str(other_temp), TMP=str(other_temp), REQUEST_LOG=str(log),
        FIXTURE_PYTHON=sys.executable, FIXTURE_INSTALLER=str(ROOT / "scripts" / "install-win.ps1"),
        FOLIOORB_INSTALL_DIR="install" if relative else str(install),
        FOLIOORB_DATA_DIR=str(profile),
        FOLIOORB_SHORTCUT=str(tmp_path / "shortcut.lnk"), FOLIOORB_INSTALL_NO_START="1",
    )
    if explicit:
        env["FOLIO_REF"] = explicit
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(wrapper)],
        env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode != 0  # Archive I/O is deliberately stopped before cutover.
    if explicit:
        archive = Path(log.read_text(encoding="utf-8-sig").strip())
        assert archive.parent.parent == install.parent
        assert archive.parent.name.startswith(".folioorb-install-")
        assert not archive.parent.exists()
    else:
        if not relative:
            assert not install.parent.exists()
        assert not log.exists()
    assert not install.exists() and not profile.exists()
    assert not list(other_temp.iterdir())


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


@pytest.mark.parametrize("version", [(3, 11, 4), (3, 11, 5), (3, 12, 0)])
def test_source_interpreter_minimum(monkeypatch, version):
    interpreter = SimpleNamespace(version_info=version, executable="/fictional/venv/python")
    monkeypatch.setattr(source_runtime, "sys", interpreter)
    if version < (3, 11, 5):
        with pytest.raises(SystemExit, match=r"Found 3\.11\.4 at /fictional/venv/python"):
            source_runtime.require_source_python()
    else:
        source_runtime.require_source_python()


def test_stale_venv_is_refused_by_source_entry_points(tmp_path):
    """The supported host interpreter must not mask the venv actually used."""
    root = tmp_path / "checkout"
    for relative in (
        "app/__init__.py", "app/source_runtime.py", "run.py",
        "scripts/setup.sh", "scripts/start.sh", "FolioOrb.command",
        "scripts/setup.ps1", "scripts/start.ps1", "FolioOrb.bat",
    ):
        dest = root / relative
        dest.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(ROOT / relative, dest)

    virtualenv = root / "venv"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(virtualenv)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    # Exercise the real entry points on each CI platform. Only the disposable
    # venv advertises the old patch; the Python found on PATH stays supported.
    (hooks / "sitecustomize.py").write_text(
        "import os, sys\n"
        "if os.path.normcase(os.path.abspath(sys.prefix)) == "
        "os.path.normcase(os.environ['TEST_STALE_VENV']):\n"
        "    sys.version_info = (3, 11, 4, 'final', 0)\n", encoding="utf-8",
    )
    profile = tmp_path / "disposable profile"
    profile.mkdir()
    sentinel = profile / "keep.txt"
    sentinel.write_bytes(b"fictional profile")
    env = {
        **os.environ, "PYTHONPATH": str(hooks), "TEST_STALE_VENV": str(virtualenv),
        "FOLIOORB_DATA_DIR": str(profile), "DATABASE_URL": f"sqlite:///{profile / 'test.db'}",
        "FOLIO_DISABLE_UPDATE_SCHEDULER": "1", "ANTHROPIC_API_KEY": "",
        "PIP_NO_INDEX": "1", "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.name == "nt":
        python = virtualenv / "Scripts/python.exe"
        shell = POWERSHELL
        assert shell
        commands = [
            [shell, "-NoProfile", "-File", "scripts/setup.ps1",
             "-NoStart"],
            [shell, "-NoProfile", "-File", "scripts/start.ps1"],
            ["cmd.exe", "/d", "/c", "FolioOrb.bat"],
        ]
    else:
        python = virtualenv / "bin/python"
        commands = [["/bin/bash", name] for name in
                    ("scripts/setup.sh", "scripts/start.sh", "FolioOrb.command")]
    for command in [[str(python), "run.py"], *commands]:
        result = subprocess.run(command, cwd=root, env=env, input="\n", text=True,
                                capture_output=True, timeout=30, check=False)
        output = result.stdout + result.stderr
        assert result.returncode != 0, command
        assert "requires Python 3.11.5 or newer. Found 3.11.4" in output, output
        assert "Installing dependencies" not in output
        assert "browser will open" not in output
        assert sentinel.read_bytes() == b"fictional profile"
        assert list(profile.iterdir()) == [sentinel]
