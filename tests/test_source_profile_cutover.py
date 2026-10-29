"""Installer cutover owns the stopped source profile until its pointer is published."""
# pylint: disable=protected-access,redefined-outer-name
from contextlib import closing, contextmanager
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "source_cutover", ROOT / "scripts" / "migrate_source_profile.py",
)
migrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrator)


def _source(root, *, lease_aware=True):
    database = root / "database" / "portfolio.db"
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE holdings (ticker TEXT)")
        connection.execute("INSERT INTO holdings VALUES ('LATEST')")
        connection.commit()
    (root / ".env").write_text("DATABASE_URL=sqlite:///./database/portfolio.db\n")
    if lease_aware:
        (root / "run.py").write_text("backup_service.acquire_profile_lock()\n")
    return database


def _rows(database):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("SELECT ticker FROM holdings ORDER BY ticker").fetchall()


@contextmanager
def _running_profile(root):
    script = (
        "import sys; from pathlib import Path; from app import paths; "
        "from app.services import backup_service; "
        "paths.data_dir=lambda:Path(sys.argv[1]); "
        "backup_service.acquire_profile_lock(); print('locked',flush=True); sys.stdin.read()"
    )
    worker = subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-c", script, str(root)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
    )
    try:
        assert worker.stdout.readline().strip() == "locked"
        yield
    finally:
        worker.communicate("", timeout=10)
        assert worker.returncode == 0


def _replacement(root):
    root.mkdir()
    (root / "run.py").write_text("# replacement fixture\n")
    return root


@pytest.fixture(autouse=True)
def local_database_selection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_cutover_refuses_runtime_owner_before_snapshot_or_publication(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "profile"
    database = _source(source)
    replacement = _replacement(tmp_path / "extracted")
    receipt = tmp_path / "cutover.json"
    with _running_profile(source), pytest.raises(RuntimeError, match="Quit the open"):
        migrator.install_source(source, destination, replacement, receipt)
    assert _rows(database) == [("LATEST",)]
    assert replacement.exists() and not destination.exists() and not receipt.exists()
    assert not list(tmp_path.glob("source-profile-recovery-*"))


def test_snapshot_and_source_cutover_exclude_late_writers(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "profile"
    database = _source(source)
    replacement = _replacement(tmp_path / "extracted")
    receipt = tmp_path / "cutover.json"
    backup = migrator._backup_database
    writer_blocked = []

    def try_late_write(live, target):
        backup(live, target)
        with closing(sqlite3.connect(live, timeout=0)) as connection:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                connection.execute("INSERT INTO holdings VALUES ('LATE')")
            writer_blocked.append(True)

    monkeypatch.setattr(migrator, "_backup_database", try_late_write)
    assert migrator.install_source(source, destination, replacement, receipt) == "MIGRATED"
    recorded = json.loads(receipt.read_text())
    recovery = Path(recorded["recovery"])
    assert writer_blocked == [True]
    assert _rows(recovery / database.relative_to(source)) == [("LATEST",)]
    assert _rows(destination / "database" / "portfolio.db") == [("LATEST",)]
    assert (source / ".source-profile-path").read_text().strip() == str(destination)
    assert not replacement.exists()


def test_cutover_keeps_profile_leases_until_replacement_is_visible(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "profile"
    _source(source)
    replacement = _replacement(tmp_path / "extracted")
    rename = Path.rename
    observations = []

    def inspect_leases(path, target):
        if path == replacement:
            moved_source = next(tmp_path.glob("source-profile-recovery-*"))
            for root in (moved_source, destination):
                with pytest.raises(RuntimeError, match="Quit the open"):
                    with migrator._profile_lease(root):
                        pytest.fail("Cutover released its profile lease early")
            observations.append(True)
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", inspect_leases)
    migrator.install_source(source, destination, replacement, tmp_path / "cutover.json")
    assert observations == [True]


def test_failed_source_replacement_restores_old_tree_and_preserves_snapshot(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "profile"
    database = _source(source)
    replacement = _replacement(tmp_path / "extracted")
    rename = Path.rename

    def refuse_replacement(path, target):
        if path == replacement:
            raise OSError("Fixture replacement failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", refuse_replacement)
    with pytest.raises(OSError, match="Fixture replacement failure"):
        migrator.install_source(source, destination, replacement, tmp_path / "cutover.json")
    assert _rows(database) == _rows(destination / "database" / "portfolio.db") == [("LATEST",)]
    assert replacement.exists() and not (source / ".source-profile-path").exists()
    assert not list(tmp_path.glob("source-profile-recovery-*"))


def test_legacy_launcher_without_runtime_lease_is_refused_without_changes(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "profile"
    database = _source(source, lease_aware=False)
    replacement = _replacement(tmp_path / "extracted")
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="legacy launcher.*exclusive profile lease"):
        migrator.install_source(source, destination, replacement, tmp_path / "cutover.json")
    assert database.read_bytes() == before
    assert not destination.exists() and not (source / ".runtime.lock").exists()
    assert replacement.exists()


def test_existing_external_profile_must_be_closed_and_match_selection(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "profile"
    _source(destination)
    source.mkdir()
    (source / "run.py").write_text("backup_service.acquire_profile_lock()\n")
    (source / ".source-profile-path").write_text(str(destination))
    replacement = _replacement(tmp_path / "extracted")
    with _running_profile(destination), pytest.raises(RuntimeError, match="Quit the open"):
        migrator.install_source(source, destination, replacement, tmp_path / "cutover.json")
    with pytest.raises(RuntimeError, match="FOLIOORB_DATA_DIR"):
        migrator.install_source(source, tmp_path / "other-profile", replacement,
                                tmp_path / "cutover.json")
    assert not (tmp_path / "other-profile").exists()
    assert _rows(destination / "database" / "portfolio.db") == [("LATEST",)]


def test_cli_cutover_receipt_points_to_retained_recovery(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "profile"
    _source(source)
    replacement = _replacement(tmp_path / "extracted")
    receipt = tmp_path / "cutover.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_source_profile.py"),
         "--source", str(source), "--destination", str(destination),
         "--replace-source", str(replacement), "--receipt", str(receipt)],
        env=os.environ.copy(), capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "MIGRATED"
    assert Path(json.loads(receipt.read_text())["recovery"]).is_dir()


def test_nested_profile_refuses_before_creating_a_lease(tmp_path):
    source = tmp_path / "source"
    database = _source(source)
    replacement = _replacement(tmp_path / "extracted")
    with pytest.raises(RuntimeError, match="outside the source install"):
        migrator.install_source(source, source / "nested", replacement, tmp_path / "receipt.json")
    assert _rows(database) == [("LATEST",)]
    assert not (source / ".runtime.lock").exists()
    assert not (source / "nested").exists()


def test_failed_receipt_rolls_back_fresh_source_publication(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "profile"
    replacement = _replacement(tmp_path / "extracted")
    with pytest.raises(OSError):
        migrator.install_source(source, destination, replacement, tmp_path / "absent" / "receipt")
    assert not source.exists() and replacement.exists()
    assert destination.is_dir()
