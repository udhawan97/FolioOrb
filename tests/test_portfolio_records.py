"""Average-cost and portable exports stay reconciled, bounded, and human-readable."""
import csv
import hashlib
import io
import json
from datetime import datetime
from zipfile import ZipFile

import pytest

from app.models import DcaContribution, DcaPlan, Holding, Portfolio, RealizedTrade
from app.services import portfolio_records


def _csv_rows(payload):
    text = payload.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_realized_recap_exports_raw_rows_and_reconciled_rounded_total(db):
    portfolio = db.get(Portfolio, 1)
    portfolio.name = "=Formula Portfolio"
    db.add_all([
        RealizedTrade(
            portfolio_id=1, ticker="+AAPL", shares_sold=1.005,
            sale_price=10.005, avg_cost=9.004, realized_gain=1.006,
            sale_currency="USD", sale_price_source="manual_entry",
            created_at=datetime(2026, 3, 1, 12, 0),
        ),
        RealizedTrade(
            portfolio_id=1, ticker="MSFT", shares_sold=2,
            sale_price=20, avg_cost=21, realized_gain=-2,
            sale_currency="USD", sale_price_source="market_quote",
            created_at=datetime(2026, 4, 1, 12, 0),
        ),
        RealizedTrade(
            portfolio_id=1, ticker="OLD", shares_sold=1,
            sale_price=1, avg_cost=1, realized_gain=0,
            sale_currency="USD", sale_price_source="manual_entry",
            created_at=datetime(2025, 1, 1, 12, 0),
        ),
    ])
    db.commit()

    rows = _csv_rows(portfolio_records.build_realized_recap_csv(db, 1, 2026))
    assert [row["row_type"] for row in rows] == ["trade", "trade", "total"]
    assert rows[0]["portfolio_name"].startswith("'=")
    assert rows[0]["ticker"].startswith("'+")
    assert rows[0]["sale_date_utc"] == "2026-03-01"
    detail_gain = sum(float(row["realized_gain_usd"]) for row in rows[:-1])
    assert float(rows[-1]["realized_gain_usd"]) == pytest.approx(detail_gain)
    assert "not a tax form" in rows[-1]["limitations"]
    assert "wash sales" in rows[-1]["limitations"]


def test_realized_recap_empty_year_has_one_zero_total_row(db):
    rows = _csv_rows(portfolio_records.build_realized_recap_csv(db, 1, 2026))
    assert len(rows) == 1
    assert rows[0]["row_type"] == "total"
    assert rows[0]["realized_gain_usd"] == "0.00"


def test_realized_recap_uses_utc_calendar_year_boundaries(db):
    db.add_all([
        RealizedTrade(
            portfolio_id=1, ticker="OLD", shares_sold=1,
            sale_price=2, avg_cost=1, realized_gain=1,
            sale_currency="USD", sale_price_source="manual_entry",
            created_at=datetime(2025, 12, 31, 23, 59, 59),
        ),
        RealizedTrade(
            portfolio_id=1, ticker="NEW", shares_sold=1,
            sale_price=3, avg_cost=1, realized_gain=2,
            sale_currency="USD", sale_price_source="market_quote",
            created_at=datetime(2026, 1, 1, 0, 0, 0),
        ),
    ])
    db.commit()

    rows = _csv_rows(portfolio_records.build_realized_recap_csv(db, 1, 2026))

    assert [row["ticker"] for row in rows[:-1]] == ["NEW"]
    assert rows[0]["sale_date_utc"] == "2026-01-01"


def test_realized_recap_rejects_nonfinite_stored_sale_facts(db):
    db.add(RealizedTrade(
        portfolio_id=1, ticker="BROKEN", shares_sold=1,
        sale_price=float("inf"), avg_cost=1, realized_gain=0,
        sale_currency="USD", sale_price_source="manual_entry",
        created_at=datetime(2026, 1, 1),
    ))
    db.commit()

    with pytest.raises(ValueError, match="finite numbers"):
        portfolio_records.build_realized_recap_csv(db, 1, 2026)


def test_portable_archive_has_deterministic_members_checksums_and_exclusions(db):
    db.add(Holding(
        portfolio_id=1, ticker="AAPL", shares=2, avg_cost=100,
        is_active=False, is_watchlist=True, notes="=private thesis",
        target_weight_bps=5000,
    ))
    plan = DcaPlan(
        portfolio_id=1, ticker="AAPL", amount=50, frequency="monthly",
        start_date="2026-01-01", is_active=True,
    )
    db.add(plan)
    db.flush()
    db.add(DcaContribution(
        plan_id=plan.id, scheduled_date="2026-01-01", exec_date="2026-01-02",
        price=100, shares=0.5, amount=50, status="pending",
    ))
    db.add(RealizedTrade(
        portfolio_id=1, ticker="VOD.L", shares_sold=1,
        sale_price=250, avg_cost=200, realized_gain=50,
        sale_currency="GBp", sale_price_source="market_quote",
        created_at=datetime(2026, 1, 2),
    ))
    db.commit()

    payload = portfolio_records.build_portable_archive(db)
    with ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == [
            "portfolios.csv",
            "holdings.csv",
            "realized_trades.csv",
            "portfolio_snapshots.csv",
            "dca_plans.csv",
            "dca_contributions.csv",
            "manifest.json",
        ]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == 1
        assert manifest["portfolio_ids"] == [1]
        assert manifest["member_order"] == archive.namelist()
        assert manifest["row_count_semantics"] == "CSV data rows; header excluded."
        assert manifest["manifest_included_in_files"] is False
        assert "self-reference" in manifest["manifest_exclusion_reason"]
        assert any("AI summaries" in item for item in manifest["omitted"])
        assert any("not a FolioOrb restore" in item for item in manifest["warnings"])
        for item in manifest["files"]:
            assert hashlib.sha256(archive.read(item["name"])).hexdigest() == item["sha256"]
        holdings = archive.read("holdings.csv").decode("utf-8-sig")
        assert "'=private thesis" in holdings
        contributions = _csv_rows(archive.read("dca_contributions.csv"))
        assert contributions[0]["portfolio_id"] == "1"
        trades = _csv_rows(archive.read("realized_trades.csv"))
        assert trades[0]["sale_currency"] == "GBp"
        assert trades[0]["sale_price_source"] == "market_quote"


def test_portable_archive_enforces_uncompressed_limit_without_partial_result(db, monkeypatch):
    db.add(Holding(
        portfolio_id=1, ticker="AAPL", shares=1, avg_cost=1,
        is_active=True, is_watchlist=False, notes="large",
    ))
    db.commit()
    monkeypatch.setattr(portfolio_records, "MAX_ARCHIVE_BYTES", 10)

    with pytest.raises(ValueError, match="64 MiB"):
        portfolio_records.build_portable_archive(db)


def test_portable_archive_enforces_compressed_limit_without_partial_result(
    db, monkeypatch
):
    original_write = getattr(portfolio_records, "_zip_write")
    monkeypatch.setattr(portfolio_records, "MAX_ARCHIVE_BYTES", 1200)
    monkeypatch.setattr(portfolio_records, "_model_rows", lambda _db: [])

    def simulate_compressed_growth(archive, name, data):
        original_write(archive, name, data)
        archive.fp.write(b"x" * 1201)

    monkeypatch.setattr(portfolio_records, "_zip_write", simulate_compressed_growth)

    with pytest.raises(ValueError, match="64 MiB"):
        portfolio_records.build_portable_archive(db)
