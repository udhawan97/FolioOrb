"""Backup-first duplicate resolution never fabricates financial activity."""
# pylint: disable=protected-access

from __future__ import annotations

import sqlite3
import subprocess
import sys

import pytest

from app.services import backup_service, holding_conflict_recovery


def _database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE holdings ("
        "id INTEGER PRIMARY KEY, portfolio_id INTEGER NOT NULL, "
        "ticker VARCHAR(10) NOT NULL, company_name VARCHAR(200), "
        "shares FLOAT, avg_cost FLOAT, is_active BOOLEAN, is_watchlist BOOLEAN, "
        "hold_class VARCHAR(20), notes TEXT, thesis_reviewed_at DATETIME, "
        "thesis_review_interval_days INTEGER, target_weight_bps INTEGER, "
        "added_at DATETIME);"
        "INSERT INTO holdings VALUES "
        "(1, 1, 'AAPL', 'Apple old', 2, 100, 1, 0, 'anchor', 'first', "
        "'2026-01-02', 90, 6000, '2025-01-01');"
        "INSERT INTO holdings VALUES "
        "(2, 1, ' aapl ', 'Apple current', 3, 120, 1, 0, 'trade', 'second', "
        "'2026-07-08', 30, 4000, '2025-02-02');"
    )
    connection.commit()
    connection.close()


def test_resolution_requires_every_explicit_choice_before_backup(tmp_path):
    database = tmp_path / "portfolio.db"
    _database(database)

    with pytest.raises(
        holding_conflict_recovery.DuplicateResolutionError,
        match="every listed ticker",
    ):
        holding_conflict_recovery.resolve_duplicates(database, tmp_path, [])

    assert not (tmp_path / "backups").exists()
    assert len(holding_conflict_recovery.list_duplicate_groups(database)) == 1


def test_resolution_backs_up_then_archives_without_sale_or_value_changes(tmp_path):
    database = tmp_path / "portfolio.db"
    _database(database)
    result = holding_conflict_recovery.resolve_duplicates(
        database,
        tmp_path,
        [{"portfolio_id": 1, "ticker": "AAPL", "keep_id": 2}],
    )

    backup = tmp_path / "backups" / result["backup"]
    assert result["archived"] == 1
    assert backup_service.verify_vault_backup(backup)
    assert not holding_conflict_recovery.list_duplicate_groups(database)

    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT id, ticker, shares, avg_cost, is_active, notes "
            "FROM holdings ORDER BY id"
        ).fetchall()
        realized_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='realized_trades'"
        ).fetchone()
    finally:
        connection.close()

    assert rows == [
        (1, "AAPL", 2.0, 100.0, 0, "first"),
        (2, " aapl ", 3.0, 120.0, 1, "second"),
    ]
    assert realized_table is None


def test_resolution_rejects_values_changed_after_the_window_was_rendered(tmp_path):
    database = tmp_path / "portfolio.db"
    _database(database)
    displayed = holding_conflict_recovery.list_duplicate_groups(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE holdings SET shares = 200, avg_cost = 999, notes = 'changed' "
        "WHERE id = 1"
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        holding_conflict_recovery.DuplicateResolutionError,
        match="changed after the choices were shown",
    ):
        holding_conflict_recovery.resolve_duplicates(
            database,
            tmp_path,
            [{"portfolio_id": 1, "ticker": "AAPL", "keep_id": 2}],
            displayed_groups=displayed,
        )

    assert not (tmp_path / "backups").exists()
    assert len(holding_conflict_recovery.list_duplicate_groups(database)) == 1


def test_resolution_binds_target_and_thesis_fields_shown_to_the_user(tmp_path):
    database = tmp_path / "portfolio.db"
    _database(database)
    displayed = holding_conflict_recovery.list_duplicate_groups(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE holdings SET target_weight_bps = 7250, "
        "thesis_reviewed_at = '2026-08-26', thesis_review_interval_days = 14 "
        "WHERE id = 1"
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        holding_conflict_recovery.DuplicateResolutionError,
        match="changed after the choices were shown",
    ):
        holding_conflict_recovery.resolve_duplicates(
            database,
            tmp_path,
            [{"portfolio_id": 1, "ticker": "AAPL", "keep_id": 2}],
            displayed_groups=displayed,
        )

    assert not (tmp_path / "backups").exists()


def test_resolution_writer_lock_covers_preflight_backup_and_archive(
    tmp_path, monkeypatch
):
    database = tmp_path / "portfolio.db"
    _database(database)
    real_backup = backup_service.create_verified_backup
    writer_result = {}

    def backup_with_competing_process(*args, **kwargs):
        script = (
            "import sqlite3,sys\n"
            "db=sqlite3.connect(sys.argv[1], timeout=0.1)\n"
            "db.execute(\"INSERT INTO holdings "
            "(portfolio_id,ticker,is_active) VALUES (1,'AAPL',1)\")\n"
            "db.commit()\n"
        )
        attempt = subprocess.run(
            [sys.executable, "-c", script, str(database)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        writer_result["returncode"] = attempt.returncode
        writer_result["stderr"] = attempt.stderr
        return real_backup(*args, **kwargs)

    monkeypatch.setattr(
        backup_service, "create_verified_backup", backup_with_competing_process
    )
    result = holding_conflict_recovery.resolve_duplicates(
        database,
        tmp_path,
        [{"portfolio_id": 1, "ticker": "AAPL", "keep_id": 2}],
    )

    assert result["archived"] == 1
    assert writer_result["returncode"] != 0
    assert "locked" in writer_result["stderr"].lower()
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM holdings").fetchone()[0] == 2
    finally:
        connection.close()


def test_resolution_names_backup_when_post_update_guard_fails(tmp_path, monkeypatch):
    database = tmp_path / "portfolio.db"
    _database(database)
    displayed = holding_conflict_recovery.list_duplicate_groups(database)
    real_groups = holding_conflict_recovery._groups
    calls = 0

    def force_late_conflict(connection):
        nonlocal calls
        calls += 1
        groups = real_groups(connection)
        if calls == 3:
            return displayed
        return groups

    monkeypatch.setattr(holding_conflict_recovery, "_groups", force_late_conflict)

    with pytest.raises(
        holding_conflict_recovery.DuplicateResolutionError,
        match="Duplicate holdings remain",
    ) as captured:
        holding_conflict_recovery.resolve_duplicates(
            database,
            tmp_path,
            [{"portfolio_id": 1, "ticker": "AAPL", "keep_id": 2}],
        )

    assert captured.value.backup_name is not None
    backup = tmp_path / "backups" / captured.value.backup_name
    assert backup_service.verify_vault_backup(backup)
    assert len(holding_conflict_recovery.list_duplicate_groups(database)) == 1
