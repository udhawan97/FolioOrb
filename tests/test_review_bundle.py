"""Review Bundle stays scoped, read-only, bounded, and auditable."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zlib
from datetime import date, datetime, timedelta, timezone
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Holding, Portfolio, PortfolioSnapshot
from app.services import review_bundle


def _quotes(tickers: list[str]) -> list[dict]:
    currencies = {"AAPL": "USD", "VOD.L": "GBp"}
    return [
        {
            "ticker": ticker,
            "name": ticker,
            "current_price": 150.0,
            "day_change": 1.0,
            "day_change_pct": 0.5,
            "currency": currencies.get(ticker, "USD"),
            "quote_type": "EQUITY",
            "security_type": "STOCK",
            "sector": "Technology",
            "market_cap": 1_000_000,
            "pe_ratio": 20.0,
        }
        for ticker in tickers
    ]


def _seed_review_book(db) -> None:
    db.add_all([
        Holding(
            id=1,
            portfolio_id=1,
            ticker="AAPL",
            shares=10,
            avg_cost=100,
            is_active=True,
            is_watchlist=False,
            target_weight_bps=6000,
            notes="Durable cash flows",
        ),
        Holding(
            id=2,
            portfolio_id=1,
            ticker="VOD.L",
            shares=20,
            avg_cost=80,
            is_active=True,
            is_watchlist=False,
            target_weight_bps=4000,
            notes="Foreign listing stays outside USD totals",
        ),
        PortfolioSnapshot(
            portfolio_id=1,
            snapshot_date=(date.today() - timedelta(days=20)).isoformat(),
            total_value=1200,
            total_cost_basis=1000,
            unrealized_gain=200,
            realized_gain=0,
            total_return=200,
        ),
    ])
    db.commit()


def _rewrite_bundle(payload: bytes, mutate) -> bytes:
    """Return a deterministic copy after ``mutate(name, content)`` edits members."""
    source = ZipFile(io.BytesIO(payload))
    output = io.BytesIO()
    with source, ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name in source.namelist():
            content = mutate(name, source.read(name))
            if content is None:
                continue
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content)
    return output.getvalue()


def _corrupt_deflate_stream(payload: bytes, member_name: str) -> bytes:
    """Flip one compressed byte that the raw DEFLATE decoder rejects."""
    raw = bytearray(payload)
    with ZipFile(io.BytesIO(payload)) as archive:
        info = archive.getinfo(member_name)
        header = info.header_offset
        name_size = int.from_bytes(raw[header + 26:header + 28], "little")
        extra_size = int.from_bytes(raw[header + 28:header + 30], "little")
        start = header + 30 + name_size + extra_size
        compressed = bytes(raw[start:start + info.compress_size])

    for index in range(len(compressed)):
        candidate = bytearray(compressed)
        candidate[index] ^= 0xFF
        try:
            zlib.decompress(candidate, -zlib.MAX_WBITS)
        except zlib.error:
            raw[start + index] ^= 0xFF
            return bytes(raw)
    raise AssertionError("Could not construct a malformed DEFLATE stream")


def test_bundle_reuses_one_quote_snapshot_and_hashes_every_receipt(db):
    _seed_review_book(db)
    calls = []

    def load(tickers):
        calls.append(list(tickers))
        return _quotes(tickers)

    generated = datetime(2026, 8, 25, 21, 30, tzinfo=timezone.utc)
    before_snapshots = db.query(PortfolioSnapshot).count()
    before_targets = [db.get(Holding, holding_id).target_weight_bps for holding_id in (1, 2)]

    payload = review_bundle.build_review_bundle(
        db, 1, "month", quote_loader=load, generated_at=generated
    )

    assert calls == [["AAPL", "VOD.L"]]
    assert db.query(PortfolioSnapshot).count() == before_snapshots
    assert [db.get(Holding, holding_id).target_weight_bps for holding_id in (1, 2)] == (
        before_targets
    )
    assert not db.new and not db.dirty and not db.deleted

    with ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == [
            "review-pack.html",
            "review-pack.csv",
            "data-health.csv",
            "target-plan.csv",
            "manifest.json",
        ]
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["app_version"] == "5.16.1"
        assert manifest["generated_at_utc"] == "2026-08-25T21:30:00Z"
        assert manifest["reporting_currency"] == "USD"
        assert manifest["foreign_currency_tickers"] == ["VOD.L"]
        assert manifest["target_course_complete"] is True
        assert manifest["target_drift_available"] is False
        trust_areas = {area["key"]: area for area in manifest["trust_areas"]}
        assert trust_areas["prices"]["foreign_currency_tickers"] == ["VOD.L"]
        assert "no FX conversion" in " ".join(manifest["warnings"])
        for item in manifest["files"]:
            member = archive.read(item["name"])
            assert item["bytes"] == len(member)
            assert item["sha256"] == hashlib.sha256(member).hexdigest()
        assert b"2026-08-25T21:30:00Z" in archive.read("data-health.csv")
        assert b"2026-08-25T21:30:00Z" in archive.read("target-plan.csv")

    verification = review_bundle.verify_review_bundle(payload)
    assert verification == {
        "valid": True,
        "code": "verified",
        "message": "All four Review Bundle receipts match manifest.json.",
        "checked_files": 4,
        "expected_files": 4,
        "integrity_only": True,
        "integrity_note": review_bundle.INTEGRITY_ONLY_NOTE,
        "manifest": {
            "format_version": 1,
            "app_version": "5.16.1",
            "generated_at_utc": "2026-08-25T21:30:00Z",
            "portfolio_id": 1,
            "period": "month",
            "period_start": verification["manifest"]["period_start"],
            "period_end": verification["manifest"]["period_end"],
            "reporting_currency": "USD",
        },
    }


def test_bundle_verifier_detects_changed_receipt_and_manifest_claim(db):
    _seed_review_book(db)
    payload = review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)

    changed_receipt = _rewrite_bundle(
        payload,
        lambda name, content: content + b"changed" if name == "review-pack.html" else content,
    )
    result = review_bundle.verify_review_bundle(changed_receipt)
    assert result["valid"] is False
    assert result["code"] == "size_mismatch"
    assert result["checked_files"] == 0
    assert result["integrity_only"] is True

    def change_digest(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["files"][0]["sha256"] = "0" * 64
        return json.dumps(manifest).encode()

    changed_manifest = _rewrite_bundle(payload, change_digest)
    result = review_bundle.verify_review_bundle(changed_manifest)
    assert result["valid"] is False
    assert result["code"] == "hash_mismatch"


def test_bundle_verifier_rejects_wrong_members_format_and_invalid_zip(db):
    _seed_review_book(db)
    payload = review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)

    missing = _rewrite_bundle(
        payload,
        lambda name, content: None if name == "target-plan.csv" else content,
    )
    assert review_bundle.verify_review_bundle(missing)["code"] == "unexpected_members"

    def change_format(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["format_version"] = 2
        return json.dumps(manifest).encode()

    unsupported = review_bundle.verify_review_bundle(_rewrite_bundle(payload, change_format))
    assert unsupported["valid"] is False
    assert unsupported["code"] == "invalid_manifest"
    assert "not supported" in unsupported["message"]

    def change_format_to_float(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["format_version"] = 1.0
        return json.dumps(manifest).encode()

    result = review_bundle.verify_review_bundle(
        _rewrite_bundle(payload, change_format_to_float)
    )
    assert result["valid"] is False
    assert result["code"] == "invalid_manifest"

    invalid = review_bundle.verify_review_bundle(b"not a zip")
    assert invalid["valid"] is False
    assert invalid["code"] == "invalid_zip"


def test_bundle_verifier_bounds_manifest_identity_fields(db):
    _seed_review_book(db)
    payload = review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)

    def invalid_identity(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["app_version"] = "v" * 65
        return json.dumps(manifest).encode()

    result = review_bundle.verify_review_bundle(_rewrite_bundle(payload, invalid_identity))
    assert result["valid"] is False
    assert result["code"] == "invalid_manifest"
    assert "identity fields" in result["message"]

    def invalid_date(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["period_start"] = "not-a-date"
        return json.dumps(manifest).encode()

    result = review_bundle.verify_review_bundle(_rewrite_bundle(payload, invalid_date))
    assert result["valid"] is False
    assert "date metadata" in result["message"]

    def noncanonical_utc(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["generated_at_utc"] = "2026-08-25T16:30:00-05:00"
        return json.dumps(manifest).encode()

    result = review_bundle.verify_review_bundle(_rewrite_bundle(payload, noncanonical_utc))
    assert result["valid"] is False
    assert "date metadata" in result["message"]

    def overflowing_utc(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["generated_at_utc"] = "0001-01-01T00:00:00+23:59"
        return json.dumps(manifest).encode()

    result = review_bundle.verify_review_bundle(_rewrite_bundle(payload, overflowing_utc))
    assert result["valid"] is False
    assert result["code"] == "invalid_manifest"
    assert "date metadata" in result["message"]


def test_bundle_verifier_fails_closed_on_adversarial_zip_and_json(db):
    _seed_review_book(db)
    payload = review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)

    corrupted = _corrupt_deflate_stream(payload, "review-pack.html")
    result = review_bundle.verify_review_bundle(corrupted)
    assert result["valid"] is False
    assert result["code"] == "invalid_zip"

    def pathological_integer(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["format_version"] = "INTEGER_SENTINEL"
        encoded = json.dumps(manifest).encode()
        return encoded.replace(b'"INTEGER_SENTINEL"', b"9" * 5000)

    result = review_bundle.verify_review_bundle(
        _rewrite_bundle(payload, pathological_integer)
    )
    assert result["valid"] is False
    assert result["code"] == "invalid_manifest"

    def lone_surrogate(name, content):
        if name != "manifest.json":
            return content
        manifest = json.loads(content)
        manifest["app_version"] = "\ud800"
        return json.dumps(manifest).encode()

    result = review_bundle.verify_review_bundle(_rewrite_bundle(payload, lone_surrogate))
    assert result["valid"] is False
    assert result["code"] == "invalid_manifest"
    assert "app version" in result["message"]


def test_bundle_verifier_rejects_reordered_and_unsupported_members(db):
    _seed_review_book(db)
    payload = review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)
    with ZipFile(io.BytesIO(payload)) as source:
        members = [(name, source.read(name)) for name in source.namelist()]

    reordered_io = io.BytesIO()
    with ZipFile(reordered_io, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in reversed(members):
            archive.writestr(name, content)
    result = review_bundle.verify_review_bundle(reordered_io.getvalue())
    assert result["valid"] is False
    assert result["code"] == "unexpected_members"

    unsupported_io = io.BytesIO()
    with ZipFile(unsupported_io, "w", compression=ZIP_BZIP2) as archive:
        for name, content in members:
            archive.writestr(name, content)
    result = review_bundle.verify_review_bundle(unsupported_io.getvalue())
    assert result["valid"] is False
    assert result["code"] == "unsafe_member"


def test_bundle_verifier_reports_completed_receipts_before_a_mismatch(db):
    _seed_review_book(db)
    payload = review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)

    def change_second_receipt(name, content):
        if name == "review-pack.csv":
            return content[:-1] + bytes([content[-1] ^ 0x01])
        return content

    result = review_bundle.verify_review_bundle(
        _rewrite_bundle(payload, change_second_receipt)
    )
    assert result["valid"] is False
    assert result["code"] == "hash_mismatch"
    assert result["checked_files"] == 1


def test_bundle_verifier_bounds_compressed_input_and_expanded_members(monkeypatch):
    monkeypatch.setattr(review_bundle, "MAX_BUNDLE_BYTES", 128)
    assert review_bundle.verify_review_bundle(b"x" * 129)["code"] == "size_limit"

    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name in review_bundle.BUNDLE_MEMBER_NAMES:
            archive.writestr(name, b"x" * 40)
    result = review_bundle.verify_review_bundle(output.getvalue())
    assert result["valid"] is False
    assert result["code"] == "size_limit"


def test_bundle_rejects_invalid_identity_period_and_oversize_output(db, monkeypatch):
    _seed_review_book(db)
    with pytest.raises(ValueError, match="period must be month or quarter"):
        review_bundle.build_review_bundle(db, 1, "year", quote_loader=_quotes)
    with pytest.raises(ValueError, match="positive integer"):
        review_bundle.build_review_bundle(db, 0, "month", quote_loader=_quotes)
    with pytest.raises(ValueError, match="Portfolio not found"):
        review_bundle.build_review_bundle(db, 99, "month", quote_loader=_quotes)

    monkeypatch.setattr(review_bundle, "MAX_BUNDLE_BYTES", 64)
    with pytest.raises(ValueError, match="8 MiB safety limit"):
        review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)


def test_bundle_bounds_manifest_in_addition_to_review_members(db, monkeypatch):
    _seed_review_book(db)
    monkeypatch.setattr(
        review_bundle,
        "_encoded_members",
        lambda _report, _trust, _plan, _generated: [
            ("review-pack.html", b"x"),
            ("review-pack.csv", b"x"),
            ("data-health.csv", b"x"),
            ("target-plan.csv", b"x"),
        ],
    )
    monkeypatch.setattr(review_bundle, "MAX_BUNDLE_BYTES", 100)

    with pytest.raises(ValueError, match="8 MiB safety limit"):
        review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)


def test_bundle_checks_final_zip_size_after_writing(db, monkeypatch):
    _seed_review_book(db)
    monkeypatch.setattr(
        review_bundle,
        "_encoded_members",
        lambda _report, _trust, _plan, _generated: [
            ("review-pack.html", b"x"),
            ("review-pack.csv", b"x"),
            ("data-health.csv", b"x"),
            ("target-plan.csv", b"x"),
        ],
    )
    monkeypatch.setattr(review_bundle, "MAX_BUNDLE_BYTES", 10_000)
    original_write = review_bundle._zip_write  # pylint: disable=protected-access
    padding = b"".join(
        hashlib.sha256(index.to_bytes(2, "little")).digest()
        for index in range(600)
    )

    def write_with_padding(archive, name, payload):
        original_write(archive, name, payload)
        if name == "manifest.json":
            original_write(archive, "test-padding.bin", padding)

    monkeypatch.setattr(review_bundle, "_zip_write", write_with_padding)

    with pytest.raises(ValueError, match="8 MiB safety limit"):
        review_bundle.build_review_bundle(db, 1, "month", quote_loader=_quotes)


def test_bundle_filename_is_fixed_and_contains_no_user_text():
    assert review_bundle.bundle_filename(
        7, "quarter", day=date(2026, 8, 25)
    ) == "folioorb-quarter-review-bundle-2026-08-25-p7.zip"


def test_bundle_names_missing_data_and_leaves_target_drift_blank(db):
    _seed_review_book(db)

    def missing_aapl(tickers):
        return [quote for quote in _quotes(tickers) if quote["ticker"] != "AAPL"]

    payload = review_bundle.build_review_bundle(
        db,
        1,
        "month",
        quote_loader=missing_aapl,
        generated_at=datetime(2026, 8, 25, 21, 30, tzinfo=timezone.utc),
    )

    with ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["missing_tickers"] == ["AAPL"]
        assert manifest["foreign_currency_tickers"] == ["VOD.L"]
        assert manifest["data_quality"]["review_valuation"] == "unavailable"
        assert manifest["data_quality"]["target_plan_valuation"] == "unavailable"
        assert manifest["target_drift_available"] is False
        trust_areas = {area["key"]: area for area in manifest["trust_areas"]}
        assert trust_areas["prices"]["missing_tickers"] == ["AAPL"]
        assert trust_areas["fundamentals"]["missing_tickers"] == ["AAPL"]

        target_rows = list(csv.reader(io.StringIO(
            archive.read("target-plan.csv").decode("utf-8-sig")
        )))
        aapl = next(row for row in target_rows if row and row[0] == "AAPL")
        assert aapl[3:] == ["", "", "", ""]


def test_bundle_scopes_quotes_and_receipts_to_the_selected_portfolio(db):
    _seed_review_book(db)
    db.add_all([
        Portfolio(id=2, name="Second Book"),
        Holding(
            id=3,
            portfolio_id=2,
            ticker="MSFT",
            shares=5,
            avg_cost=110,
            is_active=True,
            is_watchlist=False,
            target_weight_bps=10_000,
            notes="Second portfolio only",
        ),
    ])
    db.commit()
    calls = []

    def load(tickers):
        calls.append(list(tickers))
        return _quotes(tickers)

    payload = review_bundle.build_review_bundle(db, 2, "quarter", quote_loader=load)

    assert calls == [["MSFT"]]
    with ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["portfolio_id"] == 2
        receipts = b"\n".join(
            archive.read(name)
            for name in (
                "review-pack.html",
                "review-pack.csv",
                "data-health.csv",
                "target-plan.csv",
                "manifest.json",
            )
        )
        assert b"MSFT" in receipts
        assert b"AAPL" not in receipts
        assert b"VOD.L" not in receipts


def test_bundle_keeps_one_database_snapshot_during_quote_loading(tmp_path):
    database_path = tmp_path / "concurrent-bundle.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine)
    seed = sessions()
    seed.add_all([
        Portfolio(id=1, name="Snapshot Book"),
        Holding(
            id=1,
            portfolio_id=1,
            ticker="AAPL",
            shares=10,
            avg_cost=100,
            is_active=True,
            is_watchlist=False,
            target_weight_bps=10_000,
            notes="Original course",
        ),
    ])
    seed.commit()
    seed.close()

    def mutate_while_quotes_load(tickers):
        writer = sessions()
        writer.query(Holding).filter(Holding.id == 1).update({
            Holding.target_weight_bps: 9_000,
            Holding.notes: "Committed while quotes loaded",
        })
        writer.commit()
        writer.close()
        return _quotes(tickers)

    reader = sessions()
    try:
        payload = review_bundle.build_review_bundle(
            reader,
            1,
            "month",
            quote_loader=mutate_while_quotes_load,
        )
    finally:
        reader.close()

    verifier = sessions()
    try:
        assert verifier.get(Holding, 1).target_weight_bps == 9_000
    finally:
        verifier.close()
        engine.dispose()

    with ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["target_course_complete"] is True
        target_rows = list(csv.reader(io.StringIO(
            archive.read("target-plan.csv").decode("utf-8-sig")
        )))
        aapl = next(row for row in target_rows if row and row[0] == "AAPL")
        assert aapl[1] == "10000"
