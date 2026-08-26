"""Read-only Review Orbit handoff bundle with a checksummed manifest.

The bundle composes the existing review, trust, and target-plan contracts from
one frozen quote response set. It adds packaging and provenance only: no new
portfolio math, snapshots, targets, trades, or database rows are written.
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import date, datetime, timezone
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from sqlalchemy.orm import Session

from app.models import Portfolio
from app.services import (
    holdings_repository,
    portfolio_planning,
    portfolio_review,
    portfolio_valuation,
)
from app.services.stock_service import get_all_quotes
from app.version import __version__

QuoteLoader = Callable[[list[str]], list[dict]]

BUNDLE_FORMAT_VERSION = 1
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
SUPPORTED_PERIODS = frozenset({"month", "quarter"})


def _freeze_database_snapshot(db: Session) -> None:
    """Pin one SQLite read view before any bundle facts are collected.

    Python's SQLite driver does not consistently issue ``BEGIN`` for a SELECT.
    Without an explicit read transaction, another connection could commit a
    target or holding change while market quotes are loading and the later
    receipts could observe a different book. FolioOrb's production database is
    SQLite; an already-active transaction is itself the required snapshot.
    """
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        return
    driver = getattr(
        connection.connection,
        "driver_connection",
        connection.connection,
    )
    if not bool(getattr(driver, "in_transaction", False)):
        connection.exec_driver_sql("BEGIN")


def _utc_text(value: datetime) -> str:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _zip_write(archive: ZipFile, name: str, payload: bytes) -> None:
    info = ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, payload)


def bundle_filename(portfolio_id: int, period: str, *, day: date | None = None) -> str:
    """Return the fixed-format download name for a validated bundle request."""
    if period not in SUPPORTED_PERIODS:
        raise ValueError("period must be month or quarter")
    if isinstance(portfolio_id, bool) or not isinstance(portfolio_id, int) or portfolio_id < 1:
        raise ValueError("portfolio_id must be a positive integer")
    stamp = (day or date.today()).isoformat()
    return f"folioorb-{period}-review-bundle-{stamp}-p{portfolio_id}.zip"


def _frozen_loader(quotes: list[dict]) -> QuoteLoader:
    by_ticker = {
        str(quote.get("ticker") or ""): dict(quote)
        for quote in quotes
        if str(quote.get("ticker") or "")
    }

    def load(tickers: list[str]) -> list[dict]:
        return [dict(by_ticker[ticker]) for ticker in tickers if ticker in by_ticker]

    return load


def _encoded_members(report: dict, trust: dict, plan: dict, generated_at: str):
    return [
        ("review-pack.html", portfolio_review.report_html(report).encode("utf-8")),
        ("review-pack.csv", portfolio_review.report_csv(report).encode("utf-8")),
        ("data-health.csv", portfolio_review.trust_center_csv(trust).encode("utf-8")),
        (
            "target-plan.csv",
            portfolio_review.target_plan_csv(
                plan, generated_at=generated_at
            ).encode("utf-8"),
        ),
    ]


def build_review_bundle(
    db: Session,
    portfolio_id: int,
    period: str,
    *,
    quote_loader: QuoteLoader = get_all_quotes,
    generated_at: datetime | None = None,
) -> bytes:
    """Build a bounded ZIP of current Review Orbit receipts and their hashes."""
    bundle_filename(portfolio_id, period)
    _freeze_database_snapshot(db)
    exists = db.query(Portfolio.id).filter(Portfolio.id == portfolio_id).first()
    if exists is None:
        raise ValueError("Portfolio not found")

    tickers = [
        str(holding.ticker)
        for holding in holdings_repository.active(db, portfolio_id)
    ]
    quotes = quote_loader(tickers) if tickers else []
    frozen_quotes = _frozen_loader(quotes)
    generated = _utc_text(generated_at or datetime.now(timezone.utc))

    report = portfolio_review.build_review_report(
        db, portfolio_id, period, quote_loader=frozen_quotes
    )
    trust = portfolio_review.build_trust_center(
        db,
        portfolio_id,
        quote_loader=frozen_quotes,
        valuation_quote_loader=frozen_quotes,
    )
    plan = portfolio_planning.build_target_plan(
        db, portfolio_id, quote_loader=frozen_quotes
    )
    report["generated_at"] = generated
    trust["generated_at"] = generated

    members = _encoded_members(report, trust, plan, generated)
    uncompressed = sum(len(payload) for _name, payload in members)
    if uncompressed > MAX_BUNDLE_BYTES:
        raise ValueError("Review bundle exceeds the 8 MiB safety limit")

    files = [
        {
            "name": name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for name, payload in members
    ]
    trust_areas = [
        {
            "key": str(area.get("key") or ""),
            "quality": str(area.get("quality") or "unavailable"),
            "covered": area.get("covered"),
            "expected": area.get("expected"),
            "missing_tickers": sorted({
                str(ticker) for ticker in area.get("missing", []) if str(ticker)
            }),
            "foreign_currency_tickers": sorted({
                str(ticker)
                for ticker in area.get("foreign_currency_tickers", [])
                if str(ticker)
            }),
        }
        for area in trust.get("areas", [])
    ]
    trust_missing = [
        ticker
        for area in trust_areas
        for ticker in area["missing_tickers"]
    ]
    missing = sorted(set(
        report["data_quality"].get("missing_prices", [])
        + plan.get("missing_tickers", [])
        + trust_missing
    ))
    foreign = sorted(set(
        trust.get("foreign_currency_tickers", [])
        + plan.get("foreign_currency_tickers", [])
    ))
    manifest = {
        "format_version": BUNDLE_FORMAT_VERSION,
        "app_version": __version__,
        "generated_at_utc": generated,
        "portfolio_id": portfolio_id,
        "period": period,
        "period_start": report["period_start"],
        "period_end": report["period_end"],
        "reporting_currency": portfolio_valuation.REPORTING_CURRENCY,
        "data_quality": {
            "review_valuation": report["data_quality"]["valuation"],
            "review_history": report["data_quality"]["history"],
            "trust": trust["overall_quality"],
            "target_plan_valuation": plan["valuation_quality"],
        },
        "trust_areas": trust_areas,
        "target_course_complete": bool(plan["complete"]),
        "target_drift_available": bool(plan["drift_available"]),
        "missing_tickers": missing,
        "foreign_currency_tickers": foreign,
        "files": files,
        "member_order": [name for name, _payload in members] + ["manifest.json"],
        "manifest_included_in_files": False,
        "manifest_exclusion_reason": (
            "manifest.json is excluded from files and checksums to avoid self-reference."
        ),
        "warnings": [
            "This ZIP contains sensitive human-readable portfolio review material.",
            (
                "The review, trust, and target files share one in-memory quote "
                "response set."
            ),
            (
                "Foreign-priced positions are named but excluded from USD totals; "
                "no FX conversion is performed."
            ),
            (
                "Value change includes contributions and withdrawals and is not a "
                "time-weighted return."
            ),
            (
                "This is a review handoff, not a FolioOrb restore file, tax form, "
                "trade instruction, or recommendation."
            ),
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    if uncompressed + len(manifest_bytes) > MAX_BUNDLE_BYTES:
        raise ValueError("Review bundle exceeds the 8 MiB safety limit")

    buffer = io.BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in members:
            _zip_write(archive, name, payload)
        _zip_write(archive, "manifest.json", manifest_bytes)
    payload = buffer.getvalue()
    if len(payload) > MAX_BUNDLE_BYTES:
        raise ValueError("Review bundle exceeds the 8 MiB safety limit")
    return payload
