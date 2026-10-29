"""Exact reviewed writes, bounded replay and complete-field reconciliation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import io
import json
import sqlite3
import threading

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from app.database import engine as application_engine
from app.models import Base, Holding, Portfolio
from app.routers import portfolio as routes
from app.services import (
    backup_service, csv_confirmation as confirmation, holdings_csv, holdings_preview,
    portfolio_lifecycle, write_serialization,
)

PREVIEW = "/api/portfolio/holdings/preview"
CONFIRM = "/api/portfolio/holdings/confirm"
RECONCILE = "/api/portfolio/holdings/reconcile"
CSV = "ticker,shares,avg_cost,is_watchlist,hold_class,notes\nSYN,1.25,10,false,core,=1+1\n"


@pytest.fixture(name="state", autouse=True)
def _state(monkeypatch):
    clock = [0.0]
    store = confirmation.PreviewStore(clock=lambda: clock[0])
    monkeypatch.setattr(confirmation, "store", store)
    monkeypatch.setattr(routes, "validate_ticker_symbol", lambda _ticker: {"valid": True})
    return store, clock


def preview(api_client, raw=CSV, portfolio_id=1):
    with api_client(routes.router) as client:
        response = client.post(PREVIEW, params={"portfolio_id": portfolio_id},
                               files={"file": ("fictional.csv", raw, "text/csv")})
    assert response.status_code == 200
    return response.json()


def confirm(api_client, report, portfolio_id=1):
    with api_client(routes.router) as client:
        return client.post(CONFIRM, params={"portfolio_id": portfolio_id},
                           json={"token": report["confirmation"]["token"],
                                 "normalized_digest": report["normalized_digest"]})


def manifest(report):
    return {key: report[key] for key in
            ("portfolio_id", "input_digest", "normalized_digest", "reviewed_rows")}


def compare(api_client, report, raw=CSV, metadata=None, portfolio_id=1):
    with api_client(routes.router) as client:
        return client.post(RECONCILE, params={"portfolio_id": portfolio_id},
                           files={"file": ("fictional.csv", raw, "text/csv")},
                           data={"manifest": json.dumps(metadata or manifest(report))})


def snapshot(db):
    return {table.name: list(db.execute(select(table)).all())
            for table in Base.metadata.sorted_tables}


@contextmanager
def forbid_writes(db):
    before = snapshot(db)

    def inspect(_conn, _cursor, statement, _params, _context, _many):
        assert not statement.lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")
        )

    event.listen(db.bind, "before_cursor_execute", inspect)
    try:
        yield
    finally:
        event.remove(db.bind, "before_cursor_execute", inspect)
    assert snapshot(db) == before


def test_exact_valid_set_commits_together_preserving_report(api_client, db):
    db.add(Holding(portfolio_id=1, ticker="MSFT", shares=1, avg_cost=2))
    db.commit()
    raw = CSV + "SYN,9,10,false,auto,duplicate\nMSFT,2,2,false,auto,existing\n" \
        + "BAD,NaN,1,false,auto,invalid\nWATCH,0,,true,trade,watch\n"
    with forbid_writes(db):
        report = preview(api_client, raw)
    assert (report["would_add"], report["skipped"], report["errors"]) == (2, 2, 1)
    assert report["rows"][-1]["proposed_values"]["avg_cost"] == 0
    assert report["rows"][-1]["proposed_values"]["thesis_review_interval_days"] is None
    response = confirm(api_client, report)
    assert response.status_code == 200
    result = response.json()
    assert result["saved"] is True and result["added"] == 2
    assert result["reviewed_rows"] == report["reviewed_rows"]
    expected = deepcopy(report["rows"])
    for row in expected:
        if row["status"] == "would_add":
            row["status"] = "added"
    assert result["rows"] == expected
    for row in report["rows"]:
        if row["status"] == "would_add":
            holding = db.query(Holding).filter_by(ticker=row["ticker"]).one()
            actual = {key: getattr(holding, key) for key in confirmation.FIELDS}
            assert actual == row["proposed_values"]
    assert db.query(Holding).count() == 3
    assert all(not rows for name, rows in snapshot(db).items()
               if name not in {"holdings", "portfolios"})
    with forbid_writes(db):
        assert confirm(api_client, report).json() == result
        data = compare(api_client, report, raw).json()
    assert data["matching"] == 2 and data["unknown"] == data["mismatching"] == 0
    repeated = preview(api_client, raw)
    assert repeated["would_add"] == 0 and repeated["confirmation"] is None


def test_confirm_and_compare_never_call_provider_or_ai(api_client, db, monkeypatch):
    def validate(_ticker):
        assert not db.in_transaction()
        return {"valid": True}

    monkeypatch.setattr(routes, "validate_ticker_symbol", validate)
    report = preview(api_client)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Confirm/reconcile must not call a provider or AI")

    monkeypatch.setattr(routes, "validate_ticker_symbol", forbidden)
    monkeypatch.setattr(holdings_csv, "remap_columns_with_claude", forbidden)
    monkeypatch.setattr(holdings_csv, "narrate_import_summary", forbidden)
    assert confirm(api_client, report).status_code == 200
    with forbid_writes(db):
        assert compare(api_client, report).json()["matching"] == 1


@pytest.mark.parametrize("field,value", [
    ("shares", 2), ("avg_cost", 11), ("is_watchlist", True), ("hold_class", "trade"),
    ("notes", "changed"), ("thesis_review_interval_days", 30), ("target_weight_bps", 100),
    ("thesis_reviewed_at", datetime(2026, 10, 29)),
])
def test_selected_change_rejects_entire_set(api_client, db, *, field, value):
    existing = Holding(portfolio_id=1, ticker="OLD", shares=1, avg_cost=10)
    db.add(existing)
    db.commit()
    report = preview(api_client)
    setattr(existing, field, value)
    db.commit()
    before = snapshot(db)
    result = confirm(api_client, report)
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "stale"
    assert result.json()["detail"]["not_executed"] is True
    assert snapshot(db) == before
    assert confirm(api_client, report).json()["detail"]["code"] == "reconcile"


def test_unrelated_portfolio_change_does_not_invalidate(api_client, db):
    db.add(Portfolio(id=2, name="Other fictional portfolio"))
    db.commit()
    report = preview(api_client)
    db.add(Holding(portfolio_id=2, ticker="OTHER", shares=3, notes="private fictional note"))
    db.commit()
    assert confirm(api_client, report).status_code == 200


def test_expiry_tamper_wrong_scope_and_zero_valid_sets(api_client, db, state):
    store, clock = state
    db.add(Portfolio(id=2, name="Other"))
    db.commit()
    report = preview(api_client)
    assert confirm(api_client, report, portfolio_id=2).json()["detail"]["code"] == "scope"
    with api_client(routes.router) as client:
        unknown = client.post(CONFIRM, json={"token": "x" * 43,
                                             "normalized_digest": "0" * 64})
        assert unknown.json()["detail"]["code"] == "reconcile"
        assert client.post(CONFIRM, json={"token": "bad", "rows": []}).status_code == 422
    clock[0] += confirmation.TTL_SECONDS
    expired = confirm(api_client, report)
    assert expired.status_code == 410 and expired.json()["detail"]["not_executed"] is True
    assert not store.pending and db.query(Holding).count() == 0
    invalid = preview(api_client, "ticker,shares\nBAD,NaN\n")
    assert invalid["confirmation"] is None and invalid["reviewed_rows"] == []


def test_pending_and_receipt_eviction_and_restart_are_non_executable(api_client, db, state,
                                                                    monkeypatch):
    store, clock = state
    reports = [preview(api_client, f"ticker,shares\nT{i:03},1\n") for i in range(17)]
    assert len(store.pending) == 16
    assert confirm(api_client, reports[0]).json()["detail"]["code"] == "reconcile"
    store.pending.clear()
    receipts = []
    for i in range(17):
        report = preview(api_client, f"ticker,shares\nT{i:03},1\n")
        assert confirm(api_client, report).status_code == 200
        receipts.append(report)
    assert len(store.receipts) == 16 and not store.pending
    assert confirm(api_client, receipts[0]).json()["detail"]["code"] == "reconcile"
    clock[0] += confirmation.TTL_SECONDS
    assert confirm(api_client, receipts[-1]).json()["detail"]["code"] == "reconcile"
    assert db.query(Holding).count() == 17
    report = preview(api_client, "ticker,shares\nNEW,1\n")
    monkeypatch.setattr(confirmation, "store", confirmation.PreviewStore())
    assert confirm(api_client, report).json()["detail"]["code"] == "reconcile"
    with forbid_writes(db):
        assert compare(api_client, report, "ticker,shares\nNEW,1\n").json()["mismatching"] == 1


@pytest.mark.parametrize("after", [False, True])
def test_lost_commit_ack_never_reexecutes(api_client, db, state, monkeypatch, after):
    raw = CSV + "SECOND,2,20,false,auto,fictional\n"
    report = preview(api_client, raw)
    original = db.commit

    def fail_commit():
        if after:
            original()
        raise OSError("fictional interrupted acknowledgement")

    monkeypatch.setattr(db, "commit", fail_commit)
    assert confirm(api_client, report).json()["detail"]["code"] == "reconcile"
    monkeypatch.setattr(db, "commit", original)
    assert db.query(Holding).count() == (2 if after else 0)
    assert confirm(api_client, report).json()["detail"]["code"] == "reconcile"
    assert len(state[0].pending) == len(state[0].receipts) == 0
    data = compare(api_client, report, raw).json()
    assert data["matching" if after else "mismatching"] == 2


def test_second_insert_failure_rolls_back_all_reviewed_rows(api_client, db):
    raw = CSV + "SECOND,2,20,false,auto,fictional\n"
    report = preview(api_client, raw)
    before = snapshot(db)
    inserts = []

    def fail_second(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO HOLDINGS"):
            inserts.append(True)
            if len(inserts) == 2:
                raise RuntimeError("fictional insert failure")

    event.listen(db.bind, "before_cursor_execute", fail_second)
    try:
        assert confirm(api_client, report).json()["detail"]["code"] == "reconcile"
    finally:
        event.remove(db.bind, "before_cursor_execute", fail_second)
    assert len(inserts) == 2 and snapshot(db) == before


def test_reconciliation_checks_every_field_and_original_file(api_client, db):
    report = preview(api_client)
    assert confirm(api_client, report).status_code == 200
    holding = db.query(Holding).one()
    for field, value in [("shares", 4), ("avg_cost", 5), ("is_watchlist", True),
                         ("hold_class", "trade"), ("notes", "changed"),
                         ("thesis_review_interval_days", 60), ("ticker", "syn")]:
        old = getattr(holding, field)
        setattr(holding, field, value)
        db.commit()
        with forbid_writes(db):
            data = compare(api_client, report).json()
        assert data["mismatching"] == 1
        assert data["rows"][0]["current"][field] == value
        setattr(holding, field, old)
        db.commit()
    assert compare(api_client, report, CSV + "\n").status_code == 400
    for change in [{"normalized_digest": "0" * 64}, {"reviewed_rows": [3]},
                   {"reviewed_rows": [2, 2]}, {"reviewed_rows": [True]},
                   {"reviewed_rows": list(range(2, 203))}, {"portfolio_id": 2}]:
        metadata = {**manifest(report), **change}
        assert compare(api_client, report, metadata=metadata).status_code == 400
    holding.shares = float("inf")
    db.commit()
    result = compare(api_client, report).json()
    assert result["unknown"] == 1 and result["rows"][0]["current"] is None


def test_sql_debug_hides_financial_parameters(caplog):
    assert application_engine.hide_parameters is True
    original = application_engine.echo
    application_engine.echo = True
    try:
        with application_engine.connect() as connection:
            connection.execute(text("SELECT :sensitive"), {"sensitive": "fictional-secret-note"})
    finally:
        application_engine.echo = original
    assert "fictional-secret-note" not in caplog.text


@pytest.fixture(name="factory")
def _factory(tmp_path):
    path = tmp_path / "fictional.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False},
                           hide_parameters=True)

    @event.listens_for(engine, "connect")
    def pragmas(connection, _record):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=50")
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        db.add_all([Portfolio(id=1, name="Default"), Portfolio(id=2, name="CSV lab"),
                    Portfolio(id=3, name="Other")])
        db.commit()
    yield sessions, engine, path
    engine.dispose()


def confirm_record(store, db, report, portfolio_id=2):
    return store.confirm(
        db, portfolio_id, report["confirmation"]["token"], report["normalized_digest"]
    )


def prepare(store, db, raw=CSV, portfolio_id=2):
    reservation, existing = store.reserve(db, portfolio_id)
    result = holdings_preview.prepare_preview(raw.encode(), "fictional.csv", "text/csv", existing,
                                             lambda _ticker: {"valid": True})
    return store.issue(db, reservation, result)


def test_concurrent_confirms_return_same_receipt_once(factory, state):
    sessions, _engine, _path = factory
    store = state[0]
    with sessions() as db:
        report = prepare(store, db)
    barrier = threading.Barrier(2)

    def execute():
        with sessions() as db:
            barrier.wait(timeout=5)
            return confirm_record(store, db, report)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = list(workers.map(lambda _index: execute(), range(2)))
    assert first == second and first["added"] == 1
    with sessions() as db:
        assert db.query(Holding).count() == 1
    first["rows"][0]["values"]["notes"] = "mutated response"
    assert second["rows"][0]["values"]["notes"] == "=1+1"


def test_busy_is_prewrite_manual_retry_and_expiry_rechecked_after_wait(factory, state,
                                                                     monkeypatch):
    sessions, _engine, _path = factory
    store, clock = state
    with sessions() as db:
        report = prepare(store, db)
    with sessions() as blocker, sessions() as contender:
        write_serialization.begin_financial_write(blocker)
        with pytest.raises(confirmation.ConfirmationError) as error:
            confirm_record(store, contender, report)
        assert error.value.detail["code"] == "busy"
        assert error.value.detail["not_executed"] is True
        blocker.rollback()
        assert confirm_record(store, contender, report)["saved"] is True
    with sessions() as db:
        report = prepare(store, db, "ticker,shares\nNEW,1\n")
    original = write_serialization.begin_financial_write

    def delayed(db):
        original(db)
        clock[0] += confirmation.TTL_SECONDS

    monkeypatch.setattr(write_serialization, "begin_financial_write", delayed)
    with sessions() as db:
        with pytest.raises(confirmation.ConfirmationError) as error:
            confirm_record(store, db, report)
        assert error.value.detail["code"] == "expired"
        assert db.query(Holding).count() == 1


@pytest.mark.parametrize("deleted", [2, 3])
def test_preparing_preview_revoked_on_selected_delete_recreate(
    factory, state, monkeypatch, deleted
):
    sessions, _engine, _path = factory
    entered, resume = threading.Event(), threading.Event()

    def delayed(_ticker):
        entered.set()
        assert resume.wait(5)
        return {"valid": True}

    monkeypatch.setattr(routes, "validate_ticker_symbol", delayed)

    def execute():
        with sessions() as db:
            upload = UploadFile(file=io.BytesIO(CSV.encode()), filename="fictional.csv")
            return routes.preview_holdings(upload, 2, db)

    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(execute)
        assert entered.wait(5)
        with sessions() as db:
            original = db.get(Portfolio, deleted)
            identity = {field: getattr(original, field) for field in
                        ("id", "name", "description", "created_at", "updated_at")}
            portfolio_lifecycle.delete_portfolio(db, deleted)
            db.add(Portfolio(**identity))
            db.commit()
        resume.set()
        if deleted == 2:
            with pytest.raises(HTTPException) as error:
                future.result(5)
            assert error.value.status_code == 409
        else:
            report = future.result(5)
            with sessions() as db:
                assert confirm_record(state[0], db, report)["saved"] is True


def backup_copy(path, target):
    with sqlite3.connect(path) as live, sqlite3.connect(target) as destination:
        live.backup(destination)


@pytest.mark.parametrize("preview_first", [False, True, "receipt"])
def test_runtime_restore_before_first_csv_or_after_preview_blocks_old_engine(factory, state,
                                                                           preview_first):
    sessions, engine, path = factory
    store = state[0]
    backup = path.with_name("fictional-backup.db")
    backup_copy(path, backup)
    with sessions() as db:
        report = prepare(store, db) if preview_first else None
        if preview_first == "receipt":
            assert confirm_record(store, db, report)["saved"] is True
    engine.dispose()
    backup_service.restore_backup(backup, path)
    with sessions() as db:
        with pytest.raises(confirmation.ConfirmationError) as error:
            if report:
                confirm_record(store, db, report)
            else:
                store.reserve(db, 2)
        assert error.value.detail["code"] == "generation"
        assert not store.pending and not store.receipts
    replacement = create_engine(f"sqlite:///{path}")
    try:
        with replacement.connect():
            pass
        with sessionmaker(bind=replacement)() as db:
            assert prepare(store, db)["would_add"] == 1
    finally:
        replacement.dispose()


def test_external_file_replacement_and_startup_restore_generation(factory, state):
    sessions, engine, path = factory
    copy = path.with_name("replacement.db")
    backup_copy(path, copy)
    engine.dispose()
    copy.replace(path)
    with sessions() as db:
        with pytest.raises(confirmation.ConfirmationError):
            state[0].reserve(db, 2)
    # Startup sequence: restore precedes creation/first connection of a new engine.
    backup = path.with_name("startup.db")
    backup_copy(path, backup)
    backup_service.restore_backup(backup, path)
    fresh = create_engine(f"sqlite:///{path}")
    try:
        with fresh.connect():
            pass
        with sessionmaker(bind=fresh)() as db:
            assert prepare(state[0], db)["confirmation"] is not None
    finally:
        fresh.dispose()


def test_wrong_reviewed_digest_never_commits(api_client, db):
    report = preview(api_client)
    with api_client(routes.router) as client:
        response = client.post(CONFIRM, json={"token": report["confirmation"]["token"],
                                             "normalized_digest": "0" * 64})
    assert response.status_code == 409
    assert response.json()["detail"]["not_executed"] is True
    assert db.query(Holding).count() == 0


def test_preparing_eviction_and_response_copies_are_bounded(db, state):
    store = state[0]
    reservations = [store.reserve(db, 1)[0] for _ in range(17)]
    assert len(store.pending) == 16
    prepared = holdings_preview.prepare_preview(CSV.encode(), "fictional.csv", "text/csv", set(),
                                                lambda _ticker: {"valid": True})
    with pytest.raises(confirmation.ConfirmationError):
        store.issue(db, reservations[0], prepared)
    report = store.issue(db, reservations[-1], prepared)
    report["rows"][0]["proposed_values"]["notes"] = "mutated returned response"
    saved = store.confirm(db, 1, report["confirmation"]["token"], report["normalized_digest"])
    assert saved["rows"][0]["proposed_values"]["notes"] == "=1+1"
    assert db.query(Holding).one().notes == "=1+1"


def test_deleted_portfolio_revokes_pending_and_successful_receipts(factory, state):
    sessions, _engine, _path = factory
    store = state[0]
    with sessions() as db:
        report = prepare(store, db)
        confirm_record(store, db, report)
        pending = prepare(store, db, "ticker,shares\nNEW,1\n")
        original = db.get(Portfolio, 2)
        identity = {field: getattr(original, field) for field in
                    ("id", "name", "description", "created_at", "updated_at")}
        portfolio_lifecycle.delete_portfolio(db, 2)
        db.add(Portfolio(**identity))
        db.commit()
        for reviewed in (report, pending):
            with pytest.raises(confirmation.ConfirmationError) as error:
                confirm_record(store, db, reviewed)
            assert error.value.detail["code"] == "reconcile"
        assert db.query(Holding).count() == 0


def metadata_for(report):
    return routes.CsvReconciliation(**manifest(report))


def test_comparison_revokes_a_not_yet_admitted_confirmation(factory, state):
    sessions, _engine, _path = factory
    store = state[0]
    with sessions() as db:
        report = prepare(store, db)
    proceed, queued = threading.Event(), threading.Event()

    def delayed_original():
        queued.set()
        assert proceed.wait(5)
        with sessions() as db:
            return confirm_record(store, db, report)

    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(delayed_original)
        assert queued.wait(5)
        with sessions() as db:
            metadata = metadata_for(report)
            expected = confirmation.reviewed_rows(
                CSV.encode(), "fictional.csv", "text/csv", metadata
            )
            before = snapshot(db)
            compared = store.compare(db, 2, expected, metadata)
            assert compared["mismatching"] == 1 and snapshot(db) == before
        proceed.set()
        with pytest.raises(confirmation.ConfirmationError):
            future.result(5)
    with sessions() as db:
        assert db.query(Holding).count() == 0


def test_comparison_waits_for_an_admitted_confirmation(factory, state):
    sessions, _engine, _path = factory
    store = state[0]
    with sessions() as db:
        report = prepare(store, db)
    staged, finish = threading.Event(), threading.Event()

    def admitted_original():
        with sessions() as db:
            real_commit = db.commit

            def commit():
                staged.set()
                assert finish.wait(5)
                real_commit()

            db.commit = commit
            return confirm_record(store, db, report)

    def read_current():
        with sessions() as db:
            metadata = metadata_for(report)
            expected = confirmation.reviewed_rows(
                CSV.encode(), "fictional.csv", "text/csv", metadata
            )
            return store.compare(db, 2, expected, metadata)

    with ThreadPoolExecutor(max_workers=2) as workers:
        original = workers.submit(admitted_original)
        assert staged.wait(5)
        comparison = workers.submit(read_current)
        assert not comparison.done()
        finish.set()
        assert original.result(5)["saved"] is True
        assert comparison.result(5)["matching"] == 1


def test_expiry_during_real_sqlite_reservation_wait(factory, state, monkeypatch):
    sessions, _engine, _path = factory
    store, clock = state
    with sessions() as db:
        report = prepare(store, db)
    entered = threading.Event()
    original = write_serialization.begin_financial_write

    def waiting(db):
        entered.set()
        original(db)

    def execute():
        with sessions() as db:
            db.execute(text("PRAGMA busy_timeout=5000"))
            return confirm_record(store, db, report)

    with sessions() as blocker:
        original(blocker)
        monkeypatch.setattr(write_serialization, "begin_financial_write", waiting)
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(execute)
            assert entered.wait(5)
            clock[0] += confirmation.TTL_SECONDS
            blocker.rollback()
            with pytest.raises(confirmation.ConfirmationError) as error:
                future.result(5)
            assert error.value.detail["code"] == "expired"
    with sessions() as db:
        assert db.query(Holding).count() == 0


def test_all_200_reviewed_additions_commit_and_compare(api_client, db):
    raw = "ticker,shares\n" + "".join(f"T{i:03},1.25\n" for i in range(200))
    report = preview(api_client, raw)
    assert report["would_add"] == 200
    result = confirm(api_client, report).json()
    assert result["added"] == 200 and len(set(result["inserted_ids"])) == 200
    with forbid_writes(db):
        assert compare(api_client, report, raw).json()["matching"] == 200


def test_cutover_guard_waits_for_confirm_to_finish(factory, state):
    from app.services import database_generation

    sessions, _engine, _path = factory
    with sessions() as db:
        report = prepare(state[0], db)
    staged, finish, replaced = threading.Event(), threading.Event(), threading.Event()

    @database_generation.replacement
    def replace():
        replaced.set()

    def execute():
        with sessions() as db:
            original = db.commit

            def paused():
                staged.set()
                assert finish.wait(5)
                original()

            db.commit = paused
            return confirm_record(state[0], db, report)

    with ThreadPoolExecutor(max_workers=2) as workers:
        confirmed = workers.submit(execute)
        assert staged.wait(5)
        cutover = workers.submit(replace)
        assert not replaced.is_set()
        finish.set()
        assert confirmed.result(5)["saved"] is True
        cutover.result(5)
        assert replaced.is_set()


def test_initialized_engine_read_does_not_wait_for_csv_guard(factory):
    from app.services import database_generation

    _sessions, engine, _path = factory
    entered, finished = threading.Event(), threading.Event()

    def read():
        entered.set()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as worker:
        with database_generation.guard():
            future = worker.submit(read)
            assert entered.wait(5)
            completed_without_guard = finished.wait(5)
        future.result(5)
    assert completed_without_guard, "origin stamping must not serialize later unrelated reads"
