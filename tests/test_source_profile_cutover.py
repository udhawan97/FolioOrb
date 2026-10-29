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


@pytest.fixture(autouse=True, params=["native", "contents"])
def cutover_mode(request, monkeypatch):
    """Exercise Windows content transactions locally as well as the native path."""
    if request.param == "contents":
        monkeypatch.setattr(migrator, "WINDOWS_CONTENT_CUTOVER", True)


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
    publish = migrator._publish_replacement
    backup = migrator._backup_database
    observations = []
    lease_identity = []

    def remember_lease(live, target):
        lease_identity.append((source / ".runtime.lock").stat().st_ino)
        return backup(live, target)

    def inspect_leases(extracted, target, moved_entries=None):
        moved_source = next(tmp_path.glob("source-profile-recovery-*"))
        held_source = source if source.exists() else moved_source
        assert (held_source / ".runtime.lock").stat().st_ino == lease_identity[0]
        roots = [moved_source, destination]
        if source.exists():
            roots.append(source)
        for root in roots:
            with pytest.raises(RuntimeError, match="Quit the open"):
                with migrator._profile_lease(root):
                    pytest.fail("Cutover released its profile lease early")
        observations.append(True)
        return publish(extracted, target, moved_entries)

    monkeypatch.setattr(migrator, "_publish_replacement", inspect_leases)
    monkeypatch.setattr(migrator, "_backup_database", remember_lease)
    migrator.install_source(source, destination, replacement, tmp_path / "cutover.json")
    assert observations == [True]


def test_failed_source_replacement_restores_old_tree_and_preserves_snapshot(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "profile"
    database = _source(source)
    replacement = _replacement(tmp_path / "extracted")
    def refuse_replacement(*_args):
        raise OSError("Fixture replacement failure")

    monkeypatch.setattr(migrator, "_publish_replacement", refuse_replacement)
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


def test_content_cutover_partial_publication_restores_every_old_fact(tmp_path, monkeypatch):
    monkeypatch.setattr(migrator, "WINDOWS_CONTENT_CUTOVER", True)
    source, destination = tmp_path / "source", tmp_path / "profile"
    database = _source(source)
    (source / "old-only.txt").write_text("original source fact\n")
    replacement = _replacement(tmp_path / "extracted")
    (replacement / "second.txt").write_text("new source fact\n")
    original_rename = Path.rename
    publication_moves = []

    def fail_second_entry(path, target):
        if path.parent == replacement:
            if publication_moves:
                raise OSError("Fixture partial publication failure")
            result = original_rename(path, target)
            publication_moves.append(path.name)
            return result
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_second_entry)
    with pytest.raises(OSError, match="Fixture partial publication failure"):
        migrator.install_source(source, destination, replacement, tmp_path / "receipt.json")
    assert _rows(database) == _rows(destination / "database" / "portfolio.db") == [("LATEST",)]
    assert (source / "old-only.txt").read_text() == "original source fact\n"
    assert (source / "run.py").read_text() == "backup_service.acquire_profile_lock()\n"
    assert not (source / ".source-profile-path").exists()
    assert (replacement / "run.py").read_text() == "# replacement fixture\n"
    assert (replacement / "second.txt").read_text() == "new source fact\n"
    assert len(publication_moves) == 1
    assert not list(tmp_path.glob("source-profile-recovery-*"))


def test_content_cutover_receipt_failure_restores_existing_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(migrator, "WINDOWS_CONTENT_CUTOVER", True)
    source, destination = tmp_path / "source", tmp_path / "profile"
    database = _source(destination)
    source.mkdir()
    (source / "run.py").write_text("backup_service.acquire_profile_lock()\n")
    pointer = source / ".source-profile-path"
    pointer.write_text(str(destination))
    replacement = _replacement(tmp_path / "extracted")
    with pytest.raises(OSError):
        migrator.install_source(source, destination, replacement, tmp_path / "absent" / "receipt")
    assert pointer.read_text() == str(destination)
    assert (source / "run.py").read_text() == "backup_service.acquire_profile_lock()\n"
    assert (replacement / "run.py").read_text() == "# replacement fixture\n"
    assert _rows(database) == [("LATEST",)]
    assert not list(tmp_path.glob("source-update-rollback-*"))


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows directory-handle semantics")
def test_windows_open_child_blocks_ancestor_rename_even_with_delete_sharing(tmp_path):
    import ctypes
    from ctypes import wintypes

    source = tmp_path / "source"
    source.mkdir()
    recovery = tmp_path / "retained"
    # No SQLite or fixture database is involved: isolate the CreateFileW child
    # handle from all other possible sources of a directory rename refusal.
    # https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = create_file(str(source / ".runtime.lock"), 0xC0000000, 0x7, None, 4, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    try:
        with pytest.raises(PermissionError):
            source.rename(recovery)
    finally:
        assert kernel.CloseHandle(handle)
    source.rename(recovery)
    assert (recovery / ".runtime.lock").is_file()
