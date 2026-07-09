"""Backup, verification, and restore of the SQLite portfolio database.

These tests use real on-disk SQLite files in a temp directory to exercise the
online backup API, integrity checking, the non-destructive restore path (current
file preserved as ``*.failed-*``), and retention pruning.
"""
import sqlite3

import pytest

from app.services import backup_service


def _make_db(path, rows):
    """Create a minimal holdings DB with ``rows`` holding records."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE holdings (id INTEGER PRIMARY KEY, ticker TEXT)")
        conn.executemany(
            "INSERT INTO holdings (ticker) VALUES (?)", [(t,) for t in rows]
        )
        conn.commit()
    finally:
        conn.close()


def _holdings(path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT ticker FROM holdings ORDER BY id")]
    finally:
        conn.close()


def test_create_and_verify_preserves_rows(tmp_path):
    src = tmp_path / "portfolio.db"
    _make_db(src, ["VOO", "AAPL", "MSFT"])

    backup = backup_service.create_backup(src, label="test", dest_dir=tmp_path / "backups")

    assert backup.exists()
    assert backup_service.verify_backup(backup, expected_min_holdings=3)
    assert _holdings(backup) == ["VOO", "AAPL", "MSFT"]


def test_verify_rejects_missing_and_empty(tmp_path):
    assert backup_service.verify_backup(tmp_path / "nope.db") is False
    empty = tmp_path / "empty.db"
    empty.touch()
    assert backup_service.verify_backup(empty) is False


def test_verify_rejects_corrupt_file(tmp_path):
    junk = tmp_path / "corrupt.db"
    junk.write_bytes(b"this is definitely not a sqlite database")
    assert backup_service.verify_backup(junk) is False


def test_verify_min_holdings_when_table_absent(tmp_path):
    empty_db = tmp_path / "fresh.db"
    conn = sqlite3.connect(str(empty_db))
    conn.execute("CREATE TABLE unrelated (id INTEGER)")
    conn.commit()
    conn.close()
    # No holdings table: valid only when zero holdings are expected.
    assert backup_service.verify_backup(empty_db, expected_min_holdings=0) is True
    assert backup_service.verify_backup(empty_db, expected_min_holdings=1) is False


def test_restore_preserves_current_and_restores_rows(tmp_path):
    live = tmp_path / "portfolio.db"
    _make_db(live, ["OLD1", "OLD2"])
    backup = backup_service.create_backup(live, label="snap", dest_dir=tmp_path / "backups")

    # Simulate the live DB drifting/corrupting after the backup.
    conn = sqlite3.connect(str(live))
    conn.execute("DELETE FROM holdings")
    conn.execute("INSERT INTO holdings (ticker) VALUES ('BROKEN')")
    conn.commit()
    conn.close()

    assert backup_service.restore_backup(backup, live, ts="20260101-000000") is True

    # Rows come back from the backup, and the pre-restore file is preserved.
    assert _holdings(live) == ["OLD1", "OLD2"]
    assert (tmp_path / "portfolio.db.failed-20260101-000000").exists()


def test_restore_refuses_unverified_backup(tmp_path):
    live = tmp_path / "portfolio.db"
    _make_db(live, ["KEEP"])
    junk = tmp_path / "corrupt.db"
    junk.write_bytes(b"not sqlite")
    with pytest.raises(ValueError):
        backup_service.restore_backup(junk, live)
    # The live DB is untouched when a restore is refused.
    assert _holdings(live) == ["KEEP"]


def test_count_holdings(tmp_path):
    db = tmp_path / "portfolio.db"
    _make_db(db, ["VOO", "AAPL"])
    assert backup_service.count_holdings(db) == 2


def test_count_holdings_missing_table_or_file_is_zero(tmp_path):
    assert backup_service.count_holdings(tmp_path / "nope.db") == 0
    empty = tmp_path / "notable.db"
    conn = sqlite3.connect(str(empty))
    conn.execute("CREATE TABLE unrelated (id INTEGER)")
    conn.commit()
    conn.close()
    assert backup_service.count_holdings(empty) == 0


def test_env_snapshot_and_restore(tmp_path, monkeypatch):
    from app import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-original\n", encoding="utf-8")

    snap = backup_service.snapshot_env(tmp_path / "backup.env")
    assert snap is not None and snap.read_text(encoding="utf-8").startswith("ANTHROPIC_API_KEY=sk-original")

    # Current .env drifts, then is restored from the snapshot.
    env.write_text("ANTHROPIC_API_KEY=sk-changed\n", encoding="utf-8")
    assert backup_service.restore_env(snap, ts="20260101-000000") is True
    assert "sk-original" in env.read_text(encoding="utf-8")
    assert (tmp_path / ".env.failed-20260101-000000").exists()


def test_snapshot_env_returns_none_when_absent(tmp_path, monkeypatch):
    from app import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    assert backup_service.snapshot_env(tmp_path / "backup.env") is None


def test_prune_keeps_newest_n(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    import os
    import time

    created = []
    for i in range(7):
        src = tmp_path / f"src{i}.db"
        _make_db(src, [f"T{i}"])
        path = backup_service.create_backup(src, label=f"b{i}", dest_dir=backups, ts=f"t{i}")
        # Space out mtimes so ordering is deterministic.
        os.utime(path, (time.time() + i, time.time() + i))
        created.append(path)

    removed = backup_service.prune_backups(backups, keep=3)
    remaining = sorted(backups.glob("*.db"))
    assert len(remaining) == 3
    assert len(removed) == 4
    # The three newest (highest index) survive.
    assert {p.name for p in remaining} == {created[i].name for i in (4, 5, 6)}
