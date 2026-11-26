"""State-free v1 archive verification shared by export verification and comparison."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import math
import struct
import zlib
from datetime import date, datetime, timezone
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

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

MAX_COMPARISON_MANIFEST_BYTES = 64 * 1024
MAX_COMPARISON_DIRECTORY_BYTES = 64 * 1024


def _comparison_envelope(payload: bytes) -> None:
    """Bound metadata before ZipFile allocates it; this is not another ZIP parser.

    The v1 exporter emits single-disk, comment-free, non-ZIP64 archives. The
    terminal EOCD bounds the directory that the shared stdlib parser will read.
    Entry counts alone are insufficient: ZipFile reads all directory entries.
    """
    if len(payload) < 22 or payload[-22:-18] != b"PK\x05\x06":
        _fail("unsupported_envelope", "Comparison requires a conventional v1 bundle ZIP.")
    (_signature, disk, directory_disk, disk_count, total_count,
     size, offset, comment_size) = struct.unpack("<4s4H2LH", payload[-22:])
    ordinary_disk = (disk, directory_disk, disk_count, total_count, comment_size) == (0, 0, 5, 5, 0)
    zip64 = (size == 0xFFFFFFFF or offset == 0xFFFFFFFF
             or payload[-42:-38] == b"PK\x06\x07")
    if not ordinary_disk or zip64 or offset + size != len(payload) - 22:
        _fail("unsupported_envelope", "Comparison requires a conventional v1 bundle ZIP.")
    if size > MAX_COMPARISON_DIRECTORY_BYTES:
        _fail("size_limit", "The comparison ZIP directory exceeds the 64 KiB safety limit.")


def _utc_text(value: datetime) -> str:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


class BundleVerificationError(ValueError):
    """Bounded internal failure translated into the public result shape."""

    def __init__(self, code: str, message: str, *, checked_files: int = 0):
        super().__init__(message)
        self.code = code
        self.checked_files = checked_files


def _fail(code: str, message: str, *, checked_files: int = 0) -> None:
    raise BundleVerificationError(code, message, checked_files=checked_files)


def _validate_manifest_identity(manifest: object, *, comparison: bool = False) -> None:
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
            "unsupported_format" if comparison else "invalid_manifest",
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
    if (not isinstance(manifest.get("period"), str)
            or manifest["period"] not in SUPPORTED_PERIODS):
        _fail(
            "unsupported_period" if comparison else "invalid_manifest",
            "The Review Bundle manifest has an unsupported review period.",
        )
    if manifest.get("reporting_currency") != "USD":
        _fail(
            "unsupported_currency" if comparison else "invalid_manifest",
            "The Review Bundle manifest has an unsupported reporting currency.",
        )


def _validate_manifest_files(manifest: dict, max_bytes: int) -> None:
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
            or size > max_bytes
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


def _validate_archive_members(infos: list[ZipInfo], max_bytes: int) -> None:
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
    if sum(info.file_size for info in infos) > max_bytes:
        _fail(
            "size_limit", "The Review Bundle expands beyond the 8 MiB safety limit."
        )


def _read_archive_contents(
    archive: ZipFile, infos: list[ZipInfo], max_bytes: int,
) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    total_read = 0
    for info in infos:
        remaining = max_bytes - total_read
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


def _load_bundle_contents(payload: bytes, max_bytes: int, comparison: bool) -> dict[str, bytes]:
    if not isinstance(payload, bytes) or not payload:
        _fail("invalid_zip", "The selected file is not a readable Review Bundle ZIP.")
    if len(payload) > max_bytes:
        _fail(
            "size_limit", "The selected Review Bundle exceeds the 8 MiB safety limit."
        )
    if comparison:
        _comparison_envelope(payload)
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            _validate_archive_members(infos, max_bytes)
            return _read_archive_contents(archive, infos, max_bytes)
    except BundleVerificationError:
        raise
    except (BadZipFile, EOFError, OSError, RuntimeError, ValueError, zlib.error) as exc:
        raise BundleVerificationError(
            "invalid_zip", "The selected file is not a readable Review Bundle ZIP."
        ) from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Nonfinite JSON number")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        _reject_constant(value)
    return result


def _load_manifest(contents: dict[str, bytes], max_bytes: int, comparison: bool) -> dict:
    raw = contents["manifest.json"]
    if comparison and len(raw) > MAX_COMPARISON_MANIFEST_BYTES:
        _fail("size_limit", "The comparison manifest exceeds the 64 KiB safety limit.")
    options = ({"object_pairs_hook": _unique_object, "parse_constant": _reject_constant,
                "parse_float": _finite_float} if comparison else {})
    try:
        manifest = json.loads(raw.decode("utf-8"), **options)
    except (UnicodeDecodeError, RecursionError, ValueError) as exc:
        raise BundleVerificationError(
            "invalid_manifest", "manifest.json is not valid UTF-8 JSON."
        ) from exc
    _validate_manifest_identity(manifest, comparison=comparison)
    _validate_manifest_files(manifest, max_bytes)
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


def load_verified_bundle(
    payload: bytes, *, max_bytes: int = MAX_BUNDLE_BYTES, comparison: bool = False,
) -> tuple[dict, dict[str, bytes]]:
    """Load only verified bounded members; never extract or access application state."""
    contents = _load_bundle_contents(payload, max_bytes, comparison)
    manifest = _load_manifest(contents, max_bytes, comparison)
    _verify_receipts(contents, manifest)
    return manifest, contents


def verify_review_bundle(payload: bytes, *, max_bytes: int = MAX_BUNDLE_BYTES) -> dict:
    """Preserve the v1 public verification response and acceptance behavior."""
    try:
        manifest, _contents = load_verified_bundle(payload, max_bytes=max_bytes)
    except BundleVerificationError as exc:
        return _invalid_verification(exc.code, str(exc), checked_files=exc.checked_files)
    return _verification_result(
        True, "verified", "All four Review Bundle receipts match manifest.json.",
        checked_files=len(BUNDLE_FILE_NAMES), manifest=manifest,
    )
