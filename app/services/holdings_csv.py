"""
app/services/holdings_csv.py

CSV import/export of portfolio holdings. Pure logic plus the two optional Claude
calls (column remapper + import narration) — no DB access and no FastAPI imports,
so the whole module is unit-testable offline.

Two import paths share one validation choke point (`process_import_rows`):
  • Local  — strict, exact-schema parse. Works with no API key.
  • Claude — when a key is configured, Claude remaps a messy third-party CSV onto
             the template schema; the cleaned rows STILL go through the same strict
             validation before any caller writes them. Claude widens accepted input;
             it never bypasses validation and never touches the DB.

The Claude helpers import the `ai_service` module (not its symbols) so a runtime key
swap via `ai_service.reinitialize_client` is always seen — see ai_service.py:33.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
from decimal import Decimal
from typing import Callable, Iterator, Optional

from pydantic import ValidationError

from app.schemas import HoldingCreate
from app.services.log_safety import sanitize_for_log

logger = logging.getLogger(__name__)

# ── Format contract ────────────────────────────────────────────────────────────

# Exact export order; also the strict-import template. `company_name` is derived
# from live quotes everywhere, so it is intentionally not a CSV column.
CSV_COLUMNS: tuple[str, ...] = (
    "ticker", "shares", "avg_cost", "is_watchlist", "hold_class", "notes"
)

# ── Caps (bytes/rows/token footprint) ──────────────────────────────────────────

MAX_IMPORT_BYTES = 256 * 1024   # 256 KB upload cap
MAX_IMPORT_ROWS = 200           # per-file data-row cap
MAX_HEADER_COLUMNS = 30         # above this, don't even ask Claude to remap
REMAP_SAMPLE_ROWS = 5           # data rows sent to Claude
REMAP_CELL_CHARS = 40           # per-cell truncation for the Claude sample
REMAP_TIMEOUT_S = 15.0          # hard timeout on the remap call

# Cell values Claude is allowed to see verbatim (ticker-ish / numeric / short);
# anything else in the sample is replaced with a placeholder so free text never leaves.
_SAMPLE_CELL_SAFE = re.compile(r"^[\w .,$%^()/:'\"+-]{0,40}$")
_SAMPLE_PLACEHOLDER = "…"

# Truthy/falsey spellings accepted for is_watchlist.
_TRUE_TOKENS = {"true", "t", "yes", "y", "1"}
_FALSE_TOKENS = {"false", "f", "no", "n", "0", ""}

# A ticker cell that looks like Excel reformatted it into a date (MAR26 → 26-Mar).
_DATE_MANGLED = re.compile(r"^(\d{1,2}[-/][A-Za-z]{3}|[A-Za-z]{3}[-/]\d{1,2})$")

# Cells Excel/formula-injection guidance says to neutralize on export.
_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# ── Decoding & parsing ──────────────────────────────────────────────────────────

def decode_csv_bytes(raw: bytes) -> str:
    """Decode an uploaded CSV, stripping a UTF-8 BOM; fall back to cp1252.

    Rejects binary (NUL byte) and anything neither codec can decode.
    """
    if b"\x00" in raw:
        raise ValueError("File looks binary, not CSV.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Couldn't read the file as text — save it as UTF-8 CSV.")


def parse_csv_text(text: str) -> tuple[list[str], list[dict]]:
    """Parse CSV text into (header, rows). Blank lines are skipped.

    Header cells are trimmed and lower-cased so column *names* match the template
    case-insensitively; row values are returned verbatim for downstream cleaning.
    """
    reader = csv.reader(io.StringIO(text))
    header: list[str] = []
    rows: list[dict] = []
    for record in reader:
        if not any((cell or "").strip() for cell in record):
            continue  # blank line
        if not header:
            header = [(cell or "").strip().lower() for cell in record]
            continue
        row = {
            header[i]: (record[i] if i < len(record) else "")
            for i in range(len(header))
        }
        rows.append(row)
    return header, rows


def unrecognized_columns(header: list[str]) -> list[str]:
    """Header columns outside the template set (already lower-cased by the parser).

    Empty list means the file is a clean template file — the Claude remap is skipped.
    """
    known = set(CSV_COLUMNS)
    seen: list[str] = []
    for col in header:
        if col and col not in known and col not in seen:
            seen.append(col)
    return seen


def duplicate_columns(header: list[str]) -> list[str]:
    """Non-empty header names that appear more than once.

    A duplicate column is ambiguous — DictReader-style parsing keeps only the last
    occurrence, silently dropping the first — so the caller rejects such files.
    """
    counts: dict[str, int] = {}
    for col in header:
        if col:
            counts[col] = counts.get(col, 0) + 1
    return [col for col, n in counts.items() if n > 1]


# ── Cell cleaning ────────────────────────────────────────────────────────────────

def clean_cell_number(value: str) -> str:
    """Normalize a messy numeric cell to a plain decimal string.

    Handles currency symbols, thousands separators, a trailing percent sign, and
    accounting-style negatives: "$1,234.56" → "1234.56", "(50)" → "-50", "12%" → "12".
    Only used on the Claude path; the strict local parser rejects such cells instead.
    """
    text = (value or "").strip().replace("−", "-")  # normalize Unicode minus
    if not text:
        return ""
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace(",", "").replace("$", "").replace("%", "").strip()
    if negative and text and not text.startswith("-"):
        text = f"-{text}"
    return text


def clean_cell_bool(value: str) -> str:
    """Normalize a messy boolean cell to 'true'/'false'; blank/unknown → ''."""
    token = (value or "").strip().lower()
    if token in _TRUE_TOKENS:
        return "true"
    if token in _FALSE_TOKENS:
        return "false"
    return ""


def _parse_bool_cell(value: str) -> bool:
    return (value or "").strip().lower() in _TRUE_TOKENS


def escape_csv_cell(value: object) -> str:
    """Neutralize spreadsheet formula injection.

    A cell whose text begins with =, +, -, @, tab, or CR is prefixed with a single
    quote so a spreadsheet treats it as text, not a formula (OWASP guidance). The
    csv writer still handles comma/quote/newline quoting on top of this.
    """
    text = "" if value is None else str(value)
    if text and text.startswith(_INJECTION_PREFIXES):
        return f"'{text}"
    return text


# ── Export ───────────────────────────────────────────────────────────────────────

def build_export_csv(holdings: list) -> Iterator[str]:
    """Yield a UTF-8-BOM CSV: header then one row per holding, in CSV_COLUMNS order.

    Streams so the router can hand it straight to a StreamingResponse. Every field
    is run through escape_csv_cell first. Excel opens the BOM as UTF-8 cleanly, and
    the importer strips it right back via utf-8-sig.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def _flush() -> str:
        out = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return out

    yield "﻿"  # BOM
    writer.writerow(CSV_COLUMNS)
    yield _flush()

    for holding in holdings:
        shares = getattr(holding, "shares", 0) or 0
        avg_cost = getattr(holding, "avg_cost", None)
        writer.writerow([
            escape_csv_cell(getattr(holding, "ticker", "")),
            escape_csv_cell(_num_str(shares)),
            escape_csv_cell(_num_str(avg_cost) if avg_cost else ""),
            "true" if getattr(holding, "is_watchlist", False) else "false",
            escape_csv_cell(getattr(holding, "hold_class", None) or "auto"),
            escape_csv_cell(getattr(holding, "notes", None) or ""),
        ])
        yield _flush()


def _num_str(value) -> str:
    """Render a float as a plain decimal — no trailing '.0', no scientific notation.

    Uses repr() for the shortest exact round-trip, then expands any scientific
    notation (very small/large magnitudes) to plain decimal via Decimal, so a tiny
    fractional share count like 1e-8 of a crypto position exports as '0.00000001'
    instead of '1e-08' — and without the precision loss a fixed '.6f' would cause.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):  # a corrupt nan/inf must not 500 the export
        return ""
    if number == int(number):
        return str(int(number))
    text = repr(number)
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text


# ── Strict local row parsing ─────────────────────────────────────────────────────

def strict_row_to_create_kwargs(row: dict) -> dict:
    """Map a template-shaped row to HoldingCreate kwargs using strict local rules.

    Plain values only — currency symbols and thousands separators are NOT cleaned
    here (that's the Claude path); a bad number simply becomes an invalid kwarg and
    HoldingCreate rejects it downstream with a clear message.
    """
    ticker = (row.get("ticker") or "").strip().upper()
    is_watchlist = _parse_bool_cell(row.get("is_watchlist", ""))
    kwargs: dict = {"ticker": ticker, "is_watchlist": is_watchlist}

    shares = (row.get("shares") or "").strip()
    if shares:
        kwargs["shares"] = _to_float_or_raw(shares)
    elif is_watchlist:
        kwargs["shares"] = 0.0

    avg_cost = (row.get("avg_cost") or "").strip()
    if avg_cost:
        kwargs["avg_cost"] = _to_float_or_raw(avg_cost)

    hold_class = (row.get("hold_class") or "").strip()
    if hold_class:
        kwargs["hold_class"] = hold_class

    notes = (row.get("notes") or "").strip()
    if notes:
        kwargs["notes"] = notes

    return kwargs


def _to_float_or_raw(value: str):
    """Float if it parses, else the raw string (so pydantic emits the type error)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


# ── Claude column remapper ───────────────────────────────────────────────────────

_REMAP_SYSTEM = (
    "You map a messy brokerage CSV onto a fixed schema. Target columns and meaning:\n"
    "ticker: stock symbol; shares: quantity held; avg_cost: average purchase price "
    "per share; is_watchlist: research-only flag; hold_class: auto|anchor|trade|core; "
    "notes: free text.\n"
    "Given the source header and a few sample rows, reply with JSON only "
    "(no prose, no markdown):\n"
    '{"mapping": {"ticker": <source header or null>, "shares": ..., "avg_cost": ..., '
    '"is_watchlist": ..., "hold_class": ..., "notes": ...}}\n'
    "Each value must be an EXACT source header string or null when no column fits. "
    "ticker must not be null."
)


class RemapError(Exception):
    """Raised when the Claude remap is unusable — callers fall back to strict parse."""


def _sample_cell(value: str) -> str:
    text = (value or "").strip().replace("\r", " ").replace("\n", " ")[:REMAP_CELL_CHARS]
    return text if _SAMPLE_CELL_SAFE.match(text) else _SAMPLE_PLACEHOLDER


def _build_remap_payload(header: list[str], rows: list[dict]) -> str:
    sample = []
    for row in rows[:REMAP_SAMPLE_ROWS]:
        sample.append({col: _sample_cell(row.get(col, "")) for col in header})
    return json.dumps({"header": header, "rows": sample}, separators=(",", ":"))


def remap_columns_with_claude(header: list[str], rows: list[dict]) -> dict:
    """Ask Claude to map source headers onto CSV_COLUMNS. Returns {target: source|None}.

    Raises RemapError on any failure (exception, non-JSON, invalid shape) so the
    caller falls back to the strict local parse. Never sends more than
    REMAP_SAMPLE_ROWS rows, and truncates/《placeholders》 every sampled cell.
    """
    from app.services import ai_service  # module import — respects runtime key swap

    payload = _build_remap_payload(header, rows)
    try:
        message = ai_service.client.messages.create(
            model=ai_service.MODEL,
            max_tokens=500,
            temperature=0,
            timeout=REMAP_TIMEOUT_S,
            system=ai_service.cached_system(_REMAP_SYSTEM),
            messages=[{"role": "user", "content": payload}],
        )
        ai_service.track_usage(ai_service.MODEL, message.usage)
        text_block = next((b for b in message.content if b.type == "text"), None)
        raw = text_block.text.strip() if text_block else ""
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("CSV remap call failed; exception_type=%s", type(exc).__name__)
        raise RemapError(str(exc)) from exc

    raw = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RemapError("remap response was not JSON") from exc

    mapping_raw = parsed.get("mapping") if isinstance(parsed, dict) else None
    if not isinstance(mapping_raw, dict):
        raise RemapError("remap response missing 'mapping'")

    header_set = set(header)
    mapping: dict = {}
    for target in CSV_COLUMNS:
        source = mapping_raw.get(target)
        if source is None:
            mapping[target] = None
            continue
        source = str(source).strip().lower()
        if source not in header_set:
            raise RemapError(f"mapping for {target} not in header")
        mapping[target] = source

    if not mapping.get("ticker"):
        raise RemapError("remap did not map a ticker column")
    return mapping


def apply_mapping(mapping: dict, rows: list[dict]) -> list[dict]:
    """Project source rows onto template-shaped rows, cleaning numeric/bool cells.

    Runs on ALL rows locally (Claude only saw the sample), so no Claude output
    reaches the DB — only its column mapping is trusted, and even that re-enters
    the strict validator via process_import_rows.
    """
    result: list[dict] = []
    for row in rows:
        template: dict = {}
        for target in CSV_COLUMNS:
            source = mapping.get(target)
            raw = row.get(source, "") if source else ""
            if target in ("shares", "avg_cost"):
                template[target] = clean_cell_number(raw)
            elif target == "is_watchlist":
                template[target] = clean_cell_bool(raw)
            else:
                template[target] = (raw or "").strip()
        result.append(template)
    return result


# ── Import narration (Claude mode only) ──────────────────────────────────────────

_NARRATE_SYSTEM = (
    "You are Senpai, FolioOrb's dry-witted portfolio companion. In 1-2 sentences, "
    "recap this CSV import for the user. Use only the supplied counts and reasons. "
    "Precise, warm, lightly amused; no financial advice; no markdown; no invented numbers."
)


def narrate_import_summary(report: dict) -> Optional[str]:
    """One tiny Claude call recapping an import in Senpai's voice; None on any failure."""
    from app.services import ai_service  # module import — respects runtime key swap

    reasons: list[str] = []
    for row in report.get("rows", []):
        reason = row.get("reason")
        if reason and reason not in reasons:
            reasons.append(reason)
        if len(reasons) >= 3:
            break

    payload = json.dumps({
        "added": report.get("added", 0),
        "skipped": report.get("skipped", 0),
        "errors": report.get("errors", 0),
        "top_reasons": reasons,
        "unmapped_columns": report.get("unmapped_columns", []),
    }, separators=(",", ":"))

    try:
        message = ai_service.client.messages.create(
            model=ai_service.MODEL,
            max_tokens=120,
            timeout=REMAP_TIMEOUT_S,
            system=ai_service.cached_system(_NARRATE_SYSTEM),
            messages=[{"role": "user", "content": payload}],
        )
        ai_service.track_usage(ai_service.MODEL, message.usage)
        text_block = next((b for b in message.content if b.type == "text"), None)
        text = text_block.text.strip() if text_block else ""
        return text or None
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("CSV import narration failed; exception_type=%s", type(exc).__name__)
        return None


# ── The shared validation choke point ────────────────────────────────────────────

def _validation_message(exc: ValidationError) -> str:
    """First human-readable message from a pydantic error, minus its 'Value error,' prefix."""
    errors = exc.errors()
    if not errors:
        return "Invalid row"
    msg = str(errors[0].get("msg") or "Invalid row")
    return re.sub(r"^Value error,\s*", "", msg)


def process_import_rows(
    raw_rows: list[dict],
    existing_tickers: set,
    validate_fn: Callable[[str], dict],
) -> tuple[list[dict], list[HoldingCreate]]:
    """Validate template-shaped rows; return (per-row report, holdings to insert).

    Both import modes funnel through here — Claude output and strict-parsed rows
    alike — so nothing reaches the DB without passing, in cheap→expensive order:
      1. HoldingCreate  — pydantic shape/rules.
      2. in-file dedupe — a ticker already accepted earlier in THIS file.
      3. portfolio dedupe against existing active tickers.
      4. validate_fn    — the injected network ticker check (validate_ticker_symbol).
    Never touches the DB. `existing_tickers` must be upper-cased by the caller.
    """
    report: list[dict] = []
    to_insert: list[HoldingCreate] = []
    accepted: dict[str, int] = {}  # ticker → the report row number that first claimed it

    for offset, raw in enumerate(raw_rows):
        row_num = offset + 2  # header is row 1; first data row is row 2 (Excel-style)
        raw_ticker = (raw.get("ticker") or "").strip().upper()

        try:
            create = HoldingCreate(**strict_row_to_create_kwargs(raw))
        except ValidationError as exc:
            report.append({
                "row": row_num, "ticker": raw_ticker or None,
                "status": "error", "reason": _validation_message(exc),
            })
            continue

        ticker = create.ticker
        if ticker in accepted:
            report.append({
                "row": row_num, "ticker": ticker, "status": "skipped",
                "reason": f"duplicate of row {accepted[ticker]} in this file",
            })
            continue
        if ticker in existing_tickers:
            report.append({
                "row": row_num, "ticker": ticker, "status": "skipped",
                "reason": "already in portfolio",
            })
            continue

        validation = validate_fn(ticker)
        if not validation.get("valid"):
            report.append({
                "row": row_num, "ticker": ticker,
                "status": "error", "reason": _ticker_error_reason(ticker, validation),
            })
            continue

        accepted[ticker] = row_num
        to_insert.append(create)
        report.append({
            "row": row_num, "ticker": ticker, "status": "added", "reason": None,
        })

    return report, to_insert


def _ticker_error_reason(ticker: str, validation: dict) -> str:
    """Build a row-error reason, with an Excel hint for date-mangled tickers."""
    reason = str(validation.get("message") or f"Couldn't validate ticker {ticker}")
    suggestions = validation.get("suggestions") or []
    symbols = [s.get("ticker") for s in suggestions if isinstance(s, dict) and s.get("ticker")]
    if symbols:
        reason = f"{reason} (did you mean {', '.join(symbols[:3])}?)"
    if _DATE_MANGLED.match(ticker):
        reason += (
            " — this looks like a date; Excel may have reformatted the ticker. "
            "Re-export with the column formatted as Text."
        )
    return reason


def summarize(report_rows: list[dict]) -> dict:
    """Roll a per-row report into {added, skipped, errors} counts."""
    counts = {"added": 0, "skipped": 0, "errors": 0}
    for row in report_rows:
        status = row.get("status")
        if status == "added":
            counts["added"] += 1
        elif status == "skipped":
            counts["skipped"] += 1
        elif status == "error":
            counts["errors"] += 1
    return counts


def log_import(portfolio_id, mode: str, counts: dict) -> None:
    """Emit a single sanitized summary line for an import."""
    logger.info(
        "CSV import portfolio=%s mode=%s added=%s skipped=%s errors=%s",
        sanitize_for_log(portfolio_id), sanitize_for_log(mode),
        counts.get("added", 0), counts.get("skipped", 0), counts.get("errors", 0),
    )
