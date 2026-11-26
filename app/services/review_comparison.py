"""Compare captured v1 facts without files, application state, providers, or writes.

The result is data, never rendered HTML. Callers must keep the integrity and
value notes visible and use text-only rendering for all returned strings.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import (
    Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext,
)

from app.services.review_bundle_verification import (
    BundleVerificationError, INTEGRITY_ONLY_NOTE, load_verified_bundle,
)
from app.services.ticker import validated_ticker_shape

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_CSV_ROWS = 4096
MAX_CELL_CHARS = 4096
MAX_TARGETS = 2000
MAX_COUNT = 1_000_000_000
_QUALITIES = frozenset({"complete", "partial", "unavailable", "not_applicable"})
_AREAS = ("prices", "fundamentals", "fees", "income", "overlap", "theses", "history")
_QUALITY_KEYS = ("review_valuation", "review_history", "trust", "target_plan_valuation")
_PERIOD_DAYS = {"month": 31, "quarter": 92}
_USD = re.compile(r"-?[0-9]+(?:\.[0-9]{1,2})?\Z")
_MONEY_CONTEXT = Context(
    prec=40, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
    capitals=1, clamp=0, flags=[], traps=[InvalidOperation, DivisionByZero, Overflow],
)
_TARGET_HEADER = [
    "ticker", "target_weight_bps", "target_weight_pct", "actual_weight_bps",
    "actual_weight_pct", "drift_bps", "drift_direction",
]
VALUE_NOTE = (
    "Recorded USD value change includes holdings and cash changes. It is not a return, "
    "tax gain, or trading recommendation. Saved targets describe recorded intent."
)


class _ComparisonFailure(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _invalid(message="The bundle contains inconsistent or unsupported comparison data."):
    raise _ComparisonFailure("invalid_receipt", message)


def _limit():
    raise _ComparisonFailure("size_limit", "The comparison data exceeds a parsing safety limit.")


def _quality(value):
    if value is not None and (not isinstance(value, str) or value not in _QUALITIES):
        _invalid()
    return value


def _count(value):
    if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_COUNT):
        _invalid()
    return value


def _ticker(value):
    if not isinstance(value, str):
        _invalid()
    # Spreadsheet export prefixes formula-leading symbols. Remove only that
    # escape; validate the remainder through the same pure symbol contract.
    raw = value[1:] if value.startswith("'-") else value
    try:
        symbol = validated_ticker_shape(raw)
    except ValueError:
        _invalid("The bundle contains an unsupported ticker symbol.")
    if raw != symbol:
        _invalid("The bundle contains a noncanonical ticker symbol.")
    return symbol


def _tickers(values):
    if values is None:
        return None
    if not isinstance(values, list):
        _invalid()
    if len(values) > MAX_TARGETS:
        _limit()
    result = [_ticker(value) for value in values]
    if len(set(result)) != len(result):
        _invalid("The bundle contains duplicate ticker entries.")
    return sorted(result)


def _csv_tickers(value):
    return None if value is None else _tickers(value.split(" | ") if value else [])


def _money(value):
    if value in (None, ""):
        return None
    if len(value) > 32 or not _USD.fullmatch(value):
        _invalid("The bundle contains an invalid recorded USD amount.")
    amount = Decimal(value)
    if amount.copy_abs() > Decimal("1000000000000000"):
        _invalid("The recorded USD amount is outside the supported comparison range.")
    return amount


def _money_text(value):
    if value is None:
        return None
    # Independent of an embedding application's ambient Decimal context.
    with localcontext(_MONEY_CONTEXT):
        return format((value if value else Decimal(0)).quantize(Decimal("0.01")), ".2f")


def _csv_rows(raw):
    if len(raw) > MAX_CSV_BYTES:
        _limit()
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        for index, row in enumerate(reader):
            if index >= MAX_CSV_ROWS or len(row) > 8:
                _limit()
            if any(len(cell) > MAX_CELL_CHARS for cell in row):
                _limit()
            yield row
    except (UnicodeError, csv.Error):
        _invalid("A comparison receipt is not valid bounded UTF-8 CSV.")


def _review_csv(raw):
    rows = _csv_rows(raw)
    if next(rows, None) != ["section", "metric", "value"]:
        _invalid("The review receipt has an unsupported header.")
    result = {}
    for row in rows:
        if len(row) != 3:
            _invalid("The review receipt has an invalid row shape.")
        section, key, value = row
        if section in {"current", "coverage", "period_activity"}:
            pair = (section, key)
            if pair in result:
                _invalid("The review receipt contains duplicate metric keys.")
            result[pair] = value
    return result


def _basis_points(value):
    if value == "":
        return None
    if not re.fullmatch(r"[0-9]{1,5}", value) or int(value) > 10000:
        _invalid("The target receipt contains an invalid whole-basis-point weight.")
    return int(value)


def _target_csv(raw):
    rows = _csv_rows(raw)
    if next(rows, None) != ["FolioOrb target plan snapshot"]:
        _invalid("The target receipt has an unsupported heading.")
    metadata, targets = {}, {}
    for row in rows:
        if row == _TARGET_HEADER:
            break
        if not row:
            continue
        if len(row) != 2 or row[0] in metadata:
            _invalid("The target receipt has invalid or duplicate metadata.")
        metadata[row[0]] = row[1]
    else:
        _invalid("The target receipt is missing its allocation header.")
    for row in rows:
        if len(row) != len(_TARGET_HEADER):
            _invalid("The target receipt has an invalid allocation row.")
        symbol = _ticker(row[0])
        if symbol in targets:
            _invalid("The target receipt contains duplicate ticker entries.")
        if len(targets) >= MAX_TARGETS:
            _limit()
        targets[symbol] = _basis_points(row[1])
    return metadata, targets


def _coverage(manifest):
    quality = manifest.get("data_quality", {})
    areas = manifest.get("trust_areas", [])
    if not isinstance(quality, dict) or not isinstance(areas, list) or len(areas) > len(_AREAS):
        _invalid()
    if set(quality) - set(_QUALITY_KEYS):
        _invalid()
    parsed = {key: None for key in _AREAS}
    for area in areas:
        if not isinstance(area, dict) or not isinstance(area.get("key"), str):
            _invalid()
        key = area["key"]
        if key not in parsed or parsed[key] is not None:
            _invalid()
        covered, expected = _count(area.get("covered")), _count(area.get("expected"))
        if covered is not None and expected is not None and covered > expected:
            _invalid()
        parsed[key] = {
            "quality": _quality(area.get("quality")), "covered": covered, "expected": expected,
            "missing_tickers": _tickers(area.get("missing_tickers")),
            "foreign_currency_tickers": _tickers(area.get("foreign_currency_tickers")),
        }
    return {
        "quality": {key: _quality(quality.get(key)) for key in _QUALITY_KEYS},
        "areas": parsed, "missing_tickers": _tickers(manifest.get("missing_tickers")),
        "foreign_currency_tickers": _tickers(manifest.get("foreign_currency_tickers")),
    }


def _agree(values):
    present = [value for value in values if value is not None]
    if present and any(value != present[0] for value in present[1:]):
        _invalid("Recorded comparison facts disagree between the bundle receipts.")
    return all(value is not None for value in values)


def _price_contract(coverage, review, target):
    prices = coverage["areas"]["prices"] or {}
    quality = coverage["quality"]
    qualities = [prices.get("quality"), quality["review_valuation"],
                 quality["target_plan_valuation"],
                 _quality(review.get(("coverage", "valuation"))),
                 _quality(target.get("valuation_quality"))]
    missing = [prices.get("missing_tickers"),
               _csv_tickers(review.get(("coverage", "missing_prices"))),
               _csv_tickers(target.get("missing_tickers"))]
    foreign = [prices.get("foreign_currency_tickers"), coverage["foreign_currency_tickers"],
               _csv_tickers(review.get(("coverage", "foreign_currency_tickers"))),
               _csv_tickers(target.get("foreign_currency_tickers"))]
    quality_present = _agree(qualities)
    missing_present = _agree(missing)
    foreign_present = _agree(foreign)
    _agree([quality["review_history"], _quality(review.get(("coverage", "history")))])
    covered, expected = prices.get("covered"), prices.get("expected")
    if "complete" in qualities and (
            any(value for value in missing + foreign if value is not None)
            or (covered is not None and expected is not None and covered != expected)):
        _invalid("Complete price coverage conflicts with recorded exclusions or counts.")
    return (quality_present and missing_present and foreign_present
            and all(value == "complete" for value in qualities)
            and covered is not None and expected is not None and covered == expected
            and missing[0] == [] and foreign[0] == [])


def _snapshot(payload):
    manifest, contents = load_verified_bundle(payload, comparison=True)
    start, end = (date.fromisoformat(manifest[key]) for key in ("period_start", "period_end"))
    if (end - start).days != _PERIOD_DAYS[manifest["period"]]:
        raise _ComparisonFailure("unsupported_period", "The recorded review window is unsupported.")
    coverage = _coverage(manifest)
    review = _review_csv(contents["review-pack.csv"])
    target, targets = _target_csv(contents["target-plan.csv"])
    for key, expected in (("portfolio_id", str(manifest["portfolio_id"])),
                          ("reporting_currency", manifest["reporting_currency"]),
                          ("generated_at", manifest["generated_at_utc"])):
        _agree([target.get(key), expected])
    _agree([review.get(("coverage", "generated_at")), manifest["generated_at_utc"]])
    known_value = _money(review.get(("current", "known_value")))
    target_value = _money(target.get("known_value"))
    _agree([known_value, target_value])
    eligible = _price_contract(coverage, review, target) and target_value is not None
    coverage["price_comparison_evidence_complete"] = eligible
    return {
        "identity": {key: manifest[key] for key in (
            "format_version", "app_version", "portfolio_id", "generated_at_utc", "period",
            "period_start", "period_end", "reporting_currency",
        )},
        "coverage": coverage, "known_value": known_value, "targets": targets,
        "value_eligible": eligible,
    }


def _value_comparison(before, after):
    left, right = before["known_value"], after["known_value"]
    result = {"before": _money_text(left), "after": _money_text(right), "unit": "USD",
              "delta": None, "status": "unavailable", "reason": "A recorded value is missing."}
    if left is None or right is None:
        return result
    result.update(status="incomparable",
                  reason="Price coverage is incomplete, missing, or different.")
    if (before["value_eligible"] and after["value_eligible"]
            and before["coverage"]["areas"]["prices"] == after["coverage"]["areas"]["prices"]):
        with localcontext(_MONEY_CONTEXT):
            result.update(delta=_money_text(right - left), status="comparable",
                          reason="Complete, matching recorded price coverage.")
    return result


def _target_comparison(before, after):
    rows = []
    for symbol in sorted(before.keys() | after.keys()):
        left, right = before.get(symbol), after.get(symbol)
        delta = None
        if symbol not in before:
            status = "added"
        elif symbol not in after:
            status = "removed"
        elif left is None or right is None:
            status = "unassigned"
        else:
            delta = right - left
            status = "changed" if delta else "unchanged"
        rows.append({"ticker": symbol, "before": left, "after": right, "delta": delta,
                     "unit": "bps", "status": status})
    return rows


def _compatible_identities(left, right):
    if left["portfolio_id"] != right["portfolio_id"]:
        raise _ComparisonFailure("identity_mismatch",
                                 "The saved bundles have different portfolio IDs.")
    if left["period"] != right["period"]:
        raise _ComparisonFailure("period_mismatch",
                                 "Choose two bundles with the same review period semantics.")
    if datetime.fromisoformat(left["generated_at_utc"]) > datetime.fromisoformat(
            right["generated_at_utc"]):
        raise _ComparisonFailure("reversed_chronology",
                                 "The before bundle was captured later. Swap the two files.")


def compare_review_bundles(
    before: bytes, after: bytes, *, same_portfolio_confirmed: bool = False,
) -> dict:
    """Return validated captured facts or a stable sanitized failure (never raise for input).

    Same numeric IDs are necessary but insufficient across independent profiles:
    the caller must first obtain explicit confirmation that these are the same book.
    Neither successful hashing nor that confirmation authenticates financial truth.
    """
    if same_portfolio_confirmed is not True:
        return {"ok": False, "code": "confirmation_required",
                "message": "Confirm that both saved bundles describe the same portfolio."}
    snapshots = []
    for side, payload in (("before", before), ("after", after)):
        try:
            snapshots.append(_snapshot(payload))
        except BundleVerificationError as exc:
            code = exc.code if exc.code in {
                "unsupported_format", "unsupported_currency", "unsupported_period", "size_limit",
            } else "invalid_bundle"
            return {"ok": False, "code": code, "message": str(exc),
                    "bundle": side, "validation_code": exc.code}
        except _ComparisonFailure as exc:
            return {"ok": False, "code": exc.code, "message": str(exc), "bundle": side}
    first, second = snapshots[0], snapshots[1]
    left, right = first["identity"], second["identity"]
    try:
        _compatible_identities(left, right)
    except _ComparisonFailure as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
    values = _value_comparison(first, second)
    coverage_changed = first["coverage"] != second["coverage"]
    return {
        "ok": True, "comparison_schema_version": 1,
        "before": left, "after": right, "integrity_only": True,
        "integrity_note": INTEGRITY_ONLY_NOTE, "value_note": VALUE_NOTE,
        "known_value": values, "targets": _target_comparison(first["targets"], second["targets"]),
        "coverage": {"before": first["coverage"], "after": second["coverage"],
                     "changed": coverage_changed},
        "changed": (values["before"] != values["after"] or coverage_changed
                    or first["targets"] != second["targets"]),
    }
