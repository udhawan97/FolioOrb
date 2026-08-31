"""Read-only Review Orbit handoff bundle with a checksummed manifest.

The bundle composes the existing review, trust, and target-plan contracts from
one frozen quote response set. It adds packaging and provenance only: no new
portfolio math, snapshots, targets, trades, or database rows are written.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import zlib
from datetime import date, datetime, timezone
from typing import Callable
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

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
BUNDLE_FILE_NAMES = (
    "review-pack.html",
    "review-pack.csv",
    "data-health.csv",
    "target-plan.csv",
)
BUNDLE_MEMBER_NAMES = (*BUNDLE_FILE_NAMES, "manifest.json")
INTEGRITY_ONLY_NOTE = (
    "Matching hashes detect changes against this bundle's manifest; they do not "
    "authenticate who created the bundle."
)
VERSION_TOKEN_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.+-_"
)


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


def _verification_result(
    valid: bool,
    code: str,
    message: str,
    *,
    checked_files: int = 0,
    manifest: dict | None = None,
) -> dict:
    """Return one stable, user-safe verification response shape."""
    result = {
        "valid": valid,
        "code": code,
        "message": message,
        "checked_files": checked_files,
        "expected_files": len(BUNDLE_FILE_NAMES),
        "integrity_only": True,
        "integrity_note": INTEGRITY_ONLY_NOTE,
    }
    if manifest is not None:
        result["manifest"] = {
            "format_version": manifest["format_version"],
            "app_version": manifest["app_version"],
            "generated_at_utc": manifest["generated_at_utc"],
            "portfolio_id": manifest["portfolio_id"],
            "period": manifest["period"],
            "period_start": manifest["period_start"],
            "period_end": manifest["period_end"],
            "reporting_currency": manifest["reporting_currency"],
        }
    return result


def _invalid_verification(code: str, message: str, *, checked_files: int = 0) -> dict:
    return _verification_result(
        False,
        code,
        message,
        checked_files=checked_files,
    )


class _VerificationFailure(ValueError):
    """Bounded internal failure translated into the public result shape."""

    def __init__(self, code: str, message: str, *, checked_files: int = 0):
        super().__init__(message)
        self.code = code
        self.checked_files = checked_files


def _fail(code: str, message: str, *, checked_files: int = 0) -> None:
    raise _VerificationFailure(code, message, checked_files=checked_files)


def _validate_manifest_identity(manifest: object) -> None:
    """Require bounded, parseable identity fields for one v1 bundle."""
    if not isinstance(manifest, dict):
        _fail("invalid_manifest", "manifest.json must contain a JSON object.")
    format_version = manifest.get("format_version")
    if (
        isinstance(format_version, bool)
        or not isinstance(format_version, int)
        or format_version != BUNDLE_FORMAT_VERSION
    ):
        _fail(
            "invalid_manifest",
            "This Review Bundle format is not supported by this FolioOrb version.",
        )
    app_version = manifest.get("app_version")
    generated = manifest.get("generated_at_utc")
    period_start = manifest.get("period_start")
    period_end = manifest.get("period_end")
    identity_fields = (
        (app_version, 64),
        (generated, 64),
        (period_start, 32),
        (period_end, 32),
    )
    if not all(
        isinstance(value, str) and value.strip() and len(value) <= limit
        for value, limit in identity_fields
    ):
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest is missing required identity fields.",
        )
    if any(character not in VERSION_TOKEN_CHARACTERS for character in app_version):
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest has an invalid app version.",
        )
    try:
        generated_time = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        start_day = date.fromisoformat(period_start)
        end_day = date.fromisoformat(period_end)
        canonical_generated = _utc_text(generated_time)
    except (OverflowError, ValueError):
        _fail(
            "invalid_manifest", "The Review Bundle manifest has invalid date metadata."
        )
    if (
        generated_time.tzinfo is None
        or canonical_generated != generated
        or start_day.isoformat() != period_start
        or end_day.isoformat() != period_end
        or start_day > end_day
    ):
        _fail(
            "invalid_manifest", "The Review Bundle manifest has invalid date metadata."
        )
    portfolio_id = manifest.get("portfolio_id")
    if (
        isinstance(portfolio_id, bool)
        or not isinstance(portfolio_id, int)
        or portfolio_id < 1
    ):
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest has an invalid portfolio identity.",
        )
    if manifest.get("period") not in SUPPORTED_PERIODS:
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest has an unsupported review period.",
        )
    if manifest.get("reporting_currency") != portfolio_valuation.REPORTING_CURRENCY:
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest has an unsupported reporting currency.",
        )


def _validate_manifest_files(manifest: dict) -> None:
    """Require the fixed v1 receipt list and bounded hash declarations."""
    if manifest.get("member_order") != list(BUNDLE_MEMBER_NAMES):
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest does not name the expected members in order.",
        )
    if manifest.get("manifest_included_in_files") is not False:
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest has an invalid self-reference rule.",
        )
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != len(BUNDLE_FILE_NAMES):
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest does not describe all four receipts.",
        )
    described_names = [item.get("name") for item in files if isinstance(item, dict)]
    if described_names != list(BUNDLE_FILE_NAMES):
        _fail(
            "invalid_manifest",
            "The Review Bundle manifest receipt list is incomplete or reordered.",
        )
    for item in files:
        size = item.get("bytes")
        digest = item.get("sha256")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or size > MAX_BUNDLE_BYTES
        ):
            _fail(
                "invalid_manifest",
                "The Review Bundle manifest contains an invalid receipt size.",
            )
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            _fail(
                "invalid_manifest",
                "The Review Bundle manifest contains an invalid SHA-256 digest.",
            )


def _validate_archive_members(infos: list[ZipInfo]) -> None:
    names = [info.filename for info in infos]
    if names != list(BUNDLE_MEMBER_NAMES) or len(set(names)) != len(names):
        _fail(
            "unexpected_members",
            "The ZIP does not contain exactly the five Review Bundle members.",
        )
    if any(info.is_dir() or info.flag_bits & 0x1 for info in infos):
        _fail(
            "unsafe_member",
            "The Review Bundle contains a directory or encrypted member.",
        )
    if any(info.compress_type not in (ZIP_STORED, ZIP_DEFLATED) for info in infos):
        _fail(
            "unsafe_member",
            "The Review Bundle uses an unsupported ZIP compression method.",
        )
    if sum(info.file_size for info in infos) > MAX_BUNDLE_BYTES:
        _fail(
            "size_limit", "The Review Bundle expands beyond the 8 MiB safety limit."
        )


def _read_archive_contents(archive: ZipFile, infos: list[ZipInfo]) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    total_read = 0
    for info in infos:
        remaining = MAX_BUNDLE_BYTES - total_read
        with archive.open(info, mode="r") as member:
            content = member.read(remaining + 1)
        if len(content) > remaining:
            _fail(
                "size_limit",
                "The Review Bundle expands beyond the 8 MiB safety limit.",
            )
        contents[info.filename] = content
        total_read += len(content)
    return contents


def _load_bundle_contents(payload: bytes) -> dict[str, bytes]:
    if not isinstance(payload, bytes) or not payload:
        _fail("invalid_zip", "The selected file is not a readable Review Bundle ZIP.")
    if len(payload) > MAX_BUNDLE_BYTES:
        _fail(
            "size_limit", "The selected Review Bundle exceeds the 8 MiB safety limit."
        )
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            _validate_archive_members(infos)
            return _read_archive_contents(archive, infos)
    except _VerificationFailure:
        raise
    except (BadZipFile, EOFError, OSError, RuntimeError, ValueError, zlib.error) as exc:
        raise _VerificationFailure(
            "invalid_zip", "The selected file is not a readable Review Bundle ZIP."
        ) from exc


def _load_manifest(contents: dict[str, bytes]) -> dict:
    try:
        manifest = json.loads(contents["manifest.json"].decode("utf-8"))
    except (UnicodeDecodeError, RecursionError, ValueError) as exc:
        raise _VerificationFailure(
            "invalid_manifest", "manifest.json is not valid UTF-8 JSON."
        ) from exc
    _validate_manifest_identity(manifest)
    _validate_manifest_files(manifest)
    return manifest


def _verify_receipts(contents: dict[str, bytes], manifest: dict) -> int:
    checked = 0
    for item in manifest["files"]:
        content = contents[item["name"]]
        if len(content) != item["bytes"]:
            _fail(
                "size_mismatch",
                f"{item['name']} does not match the size recorded in manifest.json.",
                checked_files=checked,
            )
        digest = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(digest, item["sha256"]):
            _fail(
                "hash_mismatch",
                f"{item['name']} does not match the SHA-256 in manifest.json.",
                checked_files=checked,
            )
        checked += 1
    return checked


def verify_review_bundle(payload: bytes) -> dict:
    """Verify one bounded Review Bundle without reading or changing portfolio state.

    The check proves that the four fixed receipts match the SHA-256 values in the
    included v1 manifest. It intentionally makes no publisher-authenticity claim.
    """
    try:
        contents = _load_bundle_contents(payload)
        manifest = _load_manifest(contents)
        checked = _verify_receipts(contents, manifest)
    except _VerificationFailure as exc:
        return _invalid_verification(
            exc.code,
            str(exc),
            checked_files=exc.checked_files,
        )

    return _verification_result(
        True,
        "verified",
        "All four Review Bundle receipts match manifest.json.",
        checked_files=checked,
        manifest=manifest,
    )


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
