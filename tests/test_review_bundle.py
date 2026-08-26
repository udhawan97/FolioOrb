"""Review Bundle stays scoped, read-only, bounded, and auditable."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from zipfile import ZipFile

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
