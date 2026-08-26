"""Source-installer profiles survive code replacement outside the install tree."""

from __future__ import annotations

import os
import runpy
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent.parent
MIGRATOR = ROOT / "scripts" / "migrate_source_profile.py"


def _run_migrator(
    source: Path, destination: Path, *, database_url: str | None = None
) -> subprocess.CompletedProcess[str]:
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


def test_windows_publication_skips_posix_mode_and_retries_transient_locks():
    namespace = runpy.run_path(str(MIGRATOR))
    harden = namespace["_harden_staging_directory"]
    publish = namespace["_publish_staging_directory"]
    rename_attempts: list[tuple[Path, Path]] = []
    delays: list[float] = []

    class StagingPath:
        @staticmethod
        def chmod(_mode: int) -> None:
            raise AssertionError("Windows publication must not apply POSIX mode bits")

    def rename(source: Path, destination: Path) -> None:
        rename_attempts.append((source, destination))
        if len(rename_attempts) < 3:
            raise PermissionError("transient Windows directory lock")

    windows_os = SimpleNamespace(name="nt", rename=rename)
    harden.__globals__["os"] = windows_os
    publish.__globals__["os"] = windows_os
    publish.__globals__["time"] = SimpleNamespace(sleep=delays.append)

    harden(StagingPath())
    publish(Path("staging"), Path("profile"))

    assert rename_attempts == [
        (Path("staging"), Path("profile")),
        (Path("staging"), Path("profile")),
        (Path("staging"), Path("profile")),
    ]
    assert delays == [0.05, 0.1]


def test_installers_and_launchers_share_the_external_profile_contract():
    mac_installer = (ROOT / "scripts" / "install-mac.sh").read_text(encoding="utf-8")
    windows_installer = (ROOT / "scripts" / "install-win.ps1").read_text(encoding="utf-8")
    for content in (mac_installer, windows_installer):
        assert "migrate_source_profile.py" in content
        assert ".source-profile-path" in content
        assert ".source-install-migration-complete" in content
        assert "FOLIOORB_DATA_DIR" in content
        assert "v5.16.0" in content
        assert "main/scripts/migrate_source_profile.py" in content

    assert 'mv "$INSTALL_DIR" "$ROLLBACK_DIR"' in mac_installer
    assert "prior source install was restored" in mac_installer.lower()
    assert "Move-Item $installDir $rollbackDir" in windows_installer
    assert "prior source install was restored" in windows_installer.lower()
    assert "FolioOrb-source.cmd" in windows_installer

    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "Exercise Windows source installer and parser gate" in release_workflow
    assert "System.Management.Automation.Language.Parser" in release_workflow

    for relative in ("FolioOrb.command", "FolioOrb.bat", "scripts/start.sh", "scripts/start.ps1"):
        assert ".source-profile-path" in (ROOT / relative).read_text(encoding="utf-8")
