"""Manual freshness and opt-in automatic-backup safety policy."""
# pylint: disable=protected-access
import multiprocessing
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app import paths
from app.services import backup_service


def _make_db(path, tickers):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE holdings (id INTEGER PRIMARY KEY, ticker TEXT)")
    conn.executemany("INSERT INTO holdings (ticker) VALUES (?)", [(x,) for x in tickers])
    conn.commit()
    conn.close()


def _claim_worker(vault_text, day_text, queue):
    vault = Path(vault_text)
    claimed = backup_service._claim_auto_day(vault, date.fromisoformat(day_text))
    queue.put(claimed is not None)


def _backup_worker(source_text, vault_text, label, queue):
    try:
        created = backup_service.create_backup(
            Path(source_text), label, Path(vault_text)
        )
        queue.put({"name": created.name, "verified": backup_service.verify_vault_backup(created)})
    except Exception as exc:  # pragma: no cover - surfaced through process result
        queue.put({"error": type(exc).__name__})


def _create_verify_prune_worker(source_text, vault_text, queue):
    try:
        source = Path(source_text)
        vault = Path(vault_text)
        expected = backup_service.count_holdings(source)
        with backup_service.backup_operation(vault):
            created = backup_service.create_backup(
                source,
                "auto",
                vault,
                expected_min_holdings=expected,
            )
            verified = backup_service.verify_backup(
                created, expected_min_holdings=expected
            )
            backup_service.prune_backups(vault, keep=2, pattern="auto-*.db")
        queue.put({"verified": verified})
    except Exception as exc:  # pragma: no cover - surfaced through process result
        queue.put({"error": type(exc).__name__})


def test_manual_freshness_skips_corrupt_newer_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    vault = tmp_path / "backups"
    vault.mkdir()
    good = vault / "manual-good.db"
    bad = vault / "manual-newer.db"
    _make_db(good, ["AAPL"])
    bad.write_bytes(b"not sqlite")
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    os.utime(good, (now.timestamp() - 9 * 86_400,) * 2)
    os.utime(bad, (now.timestamp() - 86_400,) * 2)

    result = backup_service.manual_backup_freshness(now)
    assert result["status"] == "due"
    assert result["age_days"] == 9
    assert result["latest"]["name"] == good.name
    assert result["skipped_unverified"] == 1
    assert result["same_device_only"] is True


def test_manual_freshness_without_verified_snapshot_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    result = backup_service.manual_backup_freshness(
        datetime(2026, 8, 11, tzinfo=timezone.utc)
    )

    assert result["status"] == "none"
    assert result["age_days"] is None
    assert result["needs_attention"] is True
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize(
    ("age_days", "expected_status"),
    [(7, "current"), (8, "due"), (30, "due"), (31, "stale")],
)
def test_manual_freshness_exact_boundaries(
    tmp_path, monkeypatch, age_days, expected_status
):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    vault = tmp_path / "backups"
    vault.mkdir()
    manual = vault / "manual-boundary.db"
    _make_db(manual, ["AAPL"])
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    modified = now.timestamp() - age_days * 86_400
    os.utime(manual, (modified, modified))

    result = backup_service.manual_backup_freshness(now)

    assert result["status"] == expected_status
    assert result["age_days"] == age_days


def test_automatic_backup_claim_is_once_per_day_across_processes(tmp_path):
    vault = tmp_path / "backups"
    vault.mkdir()
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(
            target=_claim_worker,
            args=(str(vault), "2026-08-11", queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    assert sorted(queue.get(timeout=2) for _ in processes) == [False, True]
    claim = vault / "auto-2026-08-11.claim"
    assert claim.exists()
    if os.name != "nt":
        assert claim.stat().st_mode & 0o777 == 0o600


def test_auto_backup_is_opt_in_visible_and_auto_retention_only(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    live = tmp_path / "portfolio.db"
    _make_db(live, ["AAPL", "MSFT"])
    monkeypatch.setattr(backup_service, "live_db_path", lambda: live)
    vault = tmp_path / "backups"
    vault.mkdir()
    manual = vault / "manual-keep.db"
    update = vault / "pre-update-keep.db"
    restore = vault / "pre-manual-restore-keep.db"
    for protected in (manual, update, restore):
        _make_db(protected, ["KEEP"])

    assert backup_service.maybe_create_automatic_backup(date(2026, 8, 1))["status"] == "disabled"
    backup_service.set_auto_backup_enabled(True)
    results = [
        backup_service.maybe_create_automatic_backup(date(2026, 8, day))
        for day in range(1, 9)
    ]
    assert all(result["status"] == "succeeded" for result in results)
    repeated = backup_service.maybe_create_automatic_backup(date(2026, 8, 8))
    assert repeated["status"] == "already_attempted"
    assert len(list(vault.glob("auto-*.db"))) == backup_service.AUTO_KEEP
    assert all(path.exists() for path in (manual, update, restore))
    status = backup_service.backup_protection_status()
    assert status["automatic"]["auto_backup_enabled"] is True
    last_auto = status["automatic"]["last_auto_backup"]
    assert isinstance(last_auto, dict)
    assert last_auto.get("status") == "succeeded"
    assert status["manual_freshness"]["latest"]["name"] == manual.name


def test_auto_failure_after_claim_is_visible_not_retried_and_touches_no_other_class(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    live = tmp_path / "portfolio.db"
    _make_db(live, ["AAPL", "MSFT"])
    monkeypatch.setattr(backup_service, "live_db_path", lambda: live)
    vault = tmp_path / "backups"
    vault.mkdir()
    protected = [
        vault / "manual-keep.db",
        vault / "pre-update-keep.db",
        vault / "pre-manual-restore-keep.db",
    ]
    for path in protected:
        _make_db(path, ["KEEP"])
    backup_service.set_auto_backup_enabled(True)
    original_vault_verifier = backup_service.verify_vault_backup

    def reject_auto(path):
        return False if Path(path).name.startswith("auto-") else original_vault_verifier(path)

    monkeypatch.setattr(backup_service, "verify_vault_backup", reject_auto)
    day = date(2026, 8, 11)
    result = backup_service.maybe_create_automatic_backup(day)

    assert result["status"] == "failed"
    last_attempt = backup_service.load_backup_policy()["last_auto_backup"]
    assert isinstance(last_attempt, dict)
    assert dict(last_attempt)["status"] == "failed"
    assert (vault / "auto-2026-08-11.claim").exists()
    assert backup_service.maybe_create_automatic_backup(day)["status"] == "already_attempted"
    assert not list(vault.glob("auto-*.db"))
    assert not list(vault.glob("*.staging"))
    assert all(path.exists() for path in protected)


def test_same_second_backup_names_never_overwrite(tmp_path):
    source = tmp_path / "portfolio.db"
    _make_db(source, ["AAPL"])
    vault = tmp_path / "backups"

    first = backup_service.create_backup(source, "manual", vault)
    second = backup_service.create_backup(source, "manual", vault)

    assert first != second
    assert backup_service.verify_vault_backup(first)
    assert backup_service.verify_vault_backup(second)
    assert len(list(vault.glob("manual-*.db"))) == 2
    assert not list(vault.glob("*.staging"))


def test_manual_and_auto_publication_serialize_across_processes(tmp_path):
    source = tmp_path / "portfolio.db"
    _make_db(source, ["AAPL", "MSFT"])
    vault = tmp_path / "backups"
    vault.mkdir()
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(
            target=_backup_worker,
            args=(str(source), str(vault), label, queue),
        )
        for label in ("manual", "auto", "manual", "auto")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    results = [queue.get(timeout=2) for _ in processes]
    assert all("error" not in result for result in results)
    assert all(result["verified"] for result in results)
    assert len({result["name"] for result in results}) == len(processes)
    assert len(list(vault.glob("*.db"))) == len(processes)
    assert not list(vault.glob("*.staging"))


def test_create_verify_and_auto_prune_serialize_across_processes(tmp_path):
    source = tmp_path / "portfolio.db"
    _make_db(source, ["AAPL", "MSFT"])
    vault = tmp_path / "backups"
    vault.mkdir()
    protected = [
        vault / "manual-keep.db",
        vault / "pre-update-keep.db",
        vault / "pre-manual-restore-keep.db",
    ]
    for path in protected:
        _make_db(path, ["KEEP"])
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(
            target=_create_verify_prune_worker,
            args=(str(source), str(vault), queue),
        )
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    results = [queue.get(timeout=2) for _ in processes]
    assert all("error" not in result for result in results)
    assert all(result["verified"] for result in results)
    auto = list(vault.glob("auto-*.db"))
    assert len(auto) == 2
    assert all(backup_service.verify_backup(path, expected_min_holdings=2) for path in auto)
    assert all(path.exists() for path in protected)
    assert not list(vault.glob("*.staging"))
