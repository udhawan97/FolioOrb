"""Fictional saved bundles: exact units, honest coverage, and inert input."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tracemalloc
from datetime import datetime, timezone
from decimal import Inexact, InvalidOperation, localcontext
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from app.services.review_comparison import compare_review_bundles


def _csv(rows):
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    return ("\ufeff" + output.getvalue()).encode()


def _bundle(*, value="1000.00", targets=None, mutate=None):
    """A small explicit v1 fixture; mutate before checksumming untrusted receipts."""
    generated = "2026-11-25T12:00:00Z"
    manifest = {
        "format_version": 1, "app_version": "5.16.1", "portfolio_id": 1,
        "generated_at_utc": generated, "period": "month",
        "period_start": "2026-10-25", "period_end": "2026-11-25",
        "reporting_currency": "USD", "manifest_included_in_files": False,
        "data_quality": {"review_valuation": "complete", "review_history": "unavailable",
                         "target_plan_valuation": "complete", "trust": "unavailable"},
        "trust_areas": [
            {"key": "prices", "quality": "complete", "covered": 1, "expected": 1,
             "missing_tickers": [], "foreign_currency_tickers": []},
            {"key": "history", "quality": "unavailable", "covered": 0, "expected": None,
             "missing_tickers": [], "foreign_currency_tickers": []},
        ],
        "missing_tickers": [], "foreign_currency_tickers": [],
    }
    review = [
        ["section", "metric", "value"], ["coverage", "generated_at", generated],
        ["current", "known_value", value], ["coverage", "valuation", "complete"],
        ["coverage", "history", "unavailable"], ["coverage", "missing_prices", ""],
        ["coverage", "foreign_currency_tickers", ""],
    ]
    target = [
        ["FolioOrb target plan snapshot"], ["generated_at", generated],
        ["portfolio_id", "1"], ["reporting_currency", "USD"], ["known_value", value],
        ["valuation_quality", "complete"], ["missing_tickers", ""],
        ["foreign_currency_tickers", ""], [],
        ["ticker", "target_weight_bps", "target_weight_pct", "actual_weight_bps",
         "actual_weight_pct", "drift_bps", "drift_direction"],
    ]
    for ticker, bps in (targets if targets is not None else {"AAA": "10000"}).items():
        target.append([ticker, bps, "", "", "", "", ""])
    if mutate:
        mutate(manifest, review, target)
    contents = {
        "review-pack.html": b"<html><script>throw 'must not execute'</script></html>",
        "review-pack.csv": _csv(review), "data-health.csv": b"Fictional receipt\n",
        "target-plan.csv": _csv(target),
    }
    return _archive(manifest, contents)


def _archive(manifest, contents, *, compression=ZIP_DEFLATED):
    manifest["files"] = [
        {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in contents.items()
    ]
    manifest["member_order"] = list(contents) + ["manifest.json"]
    output = io.BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest).encode())
    return output.getvalue()


def _compare(before=None, after=None, **kwargs):
    return compare_review_bundles(
        before or _bundle(), after or _bundle(), same_portfolio_confirmed=True, **kwargs
    )


def test_identical_and_exact_cents():
    result = _compare()
    assert result["ok"] and result["changed"] is False
    assert result["known_value"] == {
        "before": "1000.00", "after": "1000.00", "delta": "0.00", "unit": "USD",
        "status": "comparable", "reason": "Complete, matching recorded price coverage.",
    }
    changed = _compare(after=_bundle(value="1010.23"))
    assert changed["known_value"]["delta"] == "10.23"
    assert changed["changed"] is True
    assert "not a return" in changed["value_note"]
    assert changed["integrity_only"] is True


@pytest.mark.parametrize("confirmation", [False, None, 1, "true"])
def test_confirmation_is_explicit_even_for_matching_ids(confirmation):
    result = compare_review_bundles(_bundle(), _bundle(),
                                   same_portfolio_confirmed=confirmation)
    assert result["code"] == "confirmation_required"


def test_saved_target_differences_never_treat_absence_as_zero():
    result = _compare(
        _bundle(targets={"AAA": "6000", "OLD": "4000", "WAIT": ""}),
        _bundle(targets={"AAA": "5000", "NEW": "5000", "WAIT": ""}),
    )
    rows = {row["ticker"]: row for row in result["targets"]}
    assert rows["AAA"]["delta"] == -1000
    assert rows["AAA"]["unit"] == "bps"
    assert rows["OLD"]["status"] == "removed" and rows["OLD"]["delta"] is None
    assert rows["NEW"]["status"] == "added" and rows["NEW"]["before"] is None
    assert rows["WAIT"]["status"] == "unassigned" and rows["WAIT"]["delta"] is None


def test_missing_known_value_is_unavailable():
    result = _compare(after=_bundle(value=""))
    assert result["ok"]
    assert result["known_value"]["after"] is None
    assert result["known_value"]["delta"] is None
    assert result["known_value"]["status"] == "unavailable"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e999999", "=1+2", "0.001",
                                   "1000000000000001", "0" * 33])
def test_malformed_values_fail_closed_without_echo(value):
    result = _compare(after=_bundle(value=value))
    assert result["ok"] is False and result["code"] == "invalid_receipt"
    assert value not in result["message"]


def test_conflicting_rehashed_valuation_metadata_fails_closed():
    def contradict(manifest, _review, _target):
        manifest["data_quality"]["review_valuation"] = "partial"
    result = _compare(after=_bundle(mutate=contradict))
    assert result["code"] == "invalid_receipt"


def _change_row(rows, key, value, *, section=None):
    for row in rows:
        if (section is None and row and row[0] == key) or (
                section is not None and row[:2] == [section, key]):
            row[-1] = value
            return
    raise AssertionError("Fixture row not found")


def _set_prices(manifest, review, target, *, quality="partial", foreign=None, missing=None):
    foreign, missing = foreign or [], missing or []
    prices = manifest["trust_areas"][0]
    prices.update(quality=quality, covered=0, expected=1,
                  missing_tickers=missing, foreign_currency_tickers=foreign)
    manifest["foreign_currency_tickers"] = foreign
    manifest["data_quality"].update(review_valuation=quality, target_plan_valuation=quality)
    for key, value in (("valuation", quality), ("missing_prices", " | ".join(missing)),
                       ("foreign_currency_tickers", " | ".join(foreign))):
        _change_row(review, key, value, section="coverage")
    for key, value in (("valuation_quality", quality), ("missing_tickers", " | ".join(missing)),
                       ("foreign_currency_tickers", " | ".join(foreign))):
        _change_row(target, key, value)


@pytest.mark.parametrize("mode", ["foreign", "missing", "all_missing", "empty"])
def test_incomplete_prices_keep_values_but_never_supply_a_delta(mode):
    def change(manifest, review, target):
        _set_prices(manifest, review, target,
                    quality="not_applicable" if mode == "empty" else "unavailable",
                    foreign=["VOD.L"] if mode == "foreign" else [],
                    missing=["AAA"] if mode in {"missing", "all_missing"} else [])
        if mode == "empty":
            manifest["trust_areas"][0]["expected"] = 0
    result = _compare(after=_bundle(value="0.00", mutate=change))
    assert result["ok"]
    assert result["known_value"]["after"] == "0.00"
    assert result["known_value"]["delta"] is None
    assert result["known_value"]["status"] == "incomparable"
    assert result["coverage"]["changed"] is True


def test_nonprice_coverage_changes_are_independent():
    def change(manifest, _review, _target):
        manifest["missing_tickers"] = ["AAA"]
        manifest["trust_areas"].append({
            "key": "theses", "quality": "partial", "covered": 0, "expected": 1,
            "missing_tickers": ["AAA"], "foreign_currency_tickers": [],
        })
    result = _compare(after=_bundle(value="1001.00", mutate=change))
    assert result["known_value"]["delta"] == "1.00"
    assert result["coverage"]["changed"] is True


@pytest.mark.parametrize("field", ["quality", "covered", "expected", "missing_tickers",
                                   "foreign_currency_tickers"])
def test_missing_price_contract_fields_do_not_infer_completeness(field):
    def change(manifest, _review, _target):
        manifest["trust_areas"][0].pop(field)
    result = _compare(after=_bundle(mutate=change))
    assert result["ok"] and result["known_value"]["delta"] is None


@pytest.mark.parametrize("field", ["covered", "expected"])
def test_null_price_counts_never_qualify(field):
    def change(manifest, _review, _target):
        manifest["trust_areas"][0][field] = None
    result = _compare(after=_bundle(mutate=change))
    assert result["ok"] and result["known_value"]["status"] == "incomparable"


@pytest.mark.parametrize("kind", ["price_count", "price_missing", "quality_csv", "target_quality",
                                  "foreign_manifest", "negative_count", "bool_count",
                                  "unknown_quality", "duplicate_area", "unknown_area",
                                  "duplicate_ticker", "target_value", "target_identity"])
def test_contradictory_or_malformed_receipts_fail_closed(kind):
    def change(manifest, review, target):
        prices = manifest["trust_areas"][0]
        if kind == "price_count":
            prices["covered"] = 2
        elif kind == "price_missing":
            prices["missing_tickers"] = ["AAA"]
        elif kind == "quality_csv":
            _change_row(review, "valuation", "partial", section="coverage")
        elif kind == "target_quality":
            _change_row(target, "valuation_quality", "partial")
        elif kind == "foreign_manifest":
            manifest["foreign_currency_tickers"] = ["VOD.L"]
        elif kind in {"negative_count", "bool_count"}:
            prices["covered"] = -1 if kind == "negative_count" else True
        elif kind == "unknown_quality":
            prices["quality"] = "probably fine"
        elif kind == "duplicate_area":
            manifest["trust_areas"].append(dict(prices))
        elif kind == "unknown_area":
            prices["key"] = "mystery"
        elif kind == "duplicate_ticker":
            target.append(list(target[-1]))
        elif kind == "target_value":
            _change_row(target, "known_value", "999.00")
        elif kind == "target_identity":
            _change_row(target, "portfolio_id", "2")
    result = _compare(after=_bundle(mutate=change))
    assert result["ok"] is False and result["code"] == "invalid_receipt"


@pytest.mark.parametrize("field,value,code", [
    ("format_version", 2, "unsupported_format"),
    ("reporting_currency", "GBp", "unsupported_currency"),
    ("period", "year", "unsupported_period"), ("period", [], "unsupported_period"),
    ("period_start", "2026-10-24", "unsupported_period"),
])
def test_rejects_unsupported_bundle_semantics(field, value, code):
    result = _compare(after=_bundle(mutate=lambda m, _r, _t: m.update({field: value})))
    assert result["code"] == code


def test_identity_mismatch_and_period_mismatch():
    def identity(manifest, _review, target):
        manifest["portfolio_id"] = 2
        _change_row(target, "portfolio_id", "2")
    assert _compare(after=_bundle(mutate=identity))["code"] == "identity_mismatch"
    def quarter(manifest, _review, _target):
        manifest.update(period="quarter", period_start="2026-08-25")
    assert _compare(after=_bundle(mutate=quarter))["code"] == "period_mismatch"


def _later(manifest, review, target):
    generated = "2026-11-26T12:00:00Z"
    manifest.update(generated_at_utc=generated, period_start="2026-10-26", period_end="2026-11-26")
    _change_row(review, "generated_at", generated, section="coverage")
    _change_row(target, "generated_at", generated)


def test_dates_remain_visible_and_reverse_is_actionable():
    before, after = _bundle(), _bundle(mutate=_later)
    result = _compare(before, after)
    assert result["before"]["period_start"] == "2026-10-25"
    assert result["after"]["generated_at_utc"] == "2026-11-26T12:00:00Z"
    assert result["changed"] is False  # A capture date is not a changed financial fact.
    assert _compare(before=after, after=before)["code"] == "reversed_chronology"


@pytest.mark.parametrize("weight", ["NaN", "1.2", "-1", "10001", "=2000", "True"])
def test_targets_require_whole_bounded_basis_points(weight):
    assert _compare(after=_bundle(targets={"AAA": weight}))["code"] == "invalid_receipt"


@pytest.mark.parametrize("ticker", ["<script>", "=1+1", "AAA\n", "aaa", "AAA\x00"])
def test_hostile_tickers_are_not_echoed(ticker):
    result = _compare(after=_bundle(targets={ticker: "1"}))
    assert result["code"] == "invalid_receipt"
    assert ticker not in result["message"]


def test_decimal_arithmetic_is_independent_of_the_caller_context():
    with localcontext() as context:
        context.prec = 2
        result = _compare(_bundle(value="999999999999999.99"),
                          _bundle(value="1000000000000000.00"))
    assert result["known_value"]["delta"] == "0.01"


@pytest.mark.parametrize("invalid_trap", [True, False])
def test_decimal_exponent_limits_and_traps_cannot_corrupt_a_valid_comparison(invalid_trap):
    before, after = _bundle(value="1000.00"), _bundle(value="1000.01")
    with localcontext() as context:
        context.prec = 2
        context.Emax, context.Emin, context.clamp = 2, -2, 1
        context.traps[InvalidOperation] = invalid_trap
        context.traps[Inexact] = True
        context.clear_flags()
        result = _compare(before, after)
        assert context.Emax == 2 and context.Emin == -2 and context.prec == 2
        assert context.traps[InvalidOperation] is invalid_trap
        assert not any(context.flags.values())
    assert result["known_value"]["before"] == "1000.00"
    assert result["known_value"]["after"] == "1000.01"
    assert result["known_value"]["delta"] == "0.01"
    assert result["known_value"]["status"] == "comparable"


def _rewrite(payload, edit, *, compression=ZIP_DEFLATED):
    output = io.BytesIO()
    with (ZipFile(io.BytesIO(payload)) as source,
          ZipFile(output, "w", compression=compression) as out):
        for name in source.namelist():
            changed = edit(name, source.read(name))
            if changed is not None:
                out.writestr(name, changed)
    return output.getvalue()


@pytest.mark.parametrize("manifest", [b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":1e999}',
                                      b"[" * 2000 + b"]" * 2000])
def test_strict_manifest_parsing_rejects_ambiguous_and_nested_json(manifest):
    raw = _rewrite(_bundle(), lambda name, data: manifest if name == "manifest.json" else data)
    assert _compare(after=raw)["validation_code"] == "invalid_manifest"


@pytest.mark.parametrize("kind", ["corrupt", "hash", "missing", "bzip", "extra", "comment",
                                  "directory", "false_count", "manifest_size", "input_size"])
def test_archive_failures_are_bounded_and_sanitized(kind):
    payload = _bundle()
    if kind == "corrupt":
        payload = b"not a ZIP"
    elif kind == "hash":
        payload = _rewrite(payload, lambda name, data: (
            data[:-1] + b"!" if name.endswith("html") else data))
    elif kind == "missing":
        payload = _rewrite(payload, lambda name, data: None if name.endswith("html") else data)
    elif kind == "bzip":
        payload = _rewrite(payload, lambda _name, data: data, compression=ZIP_BZIP2)
    elif kind in {"extra", "directory", "comment"}:
        output = io.BytesIO(payload)
        with ZipFile(output, "a") as archive:
            if kind == "comment":
                archive.comment = b"unsupported"
            else:
                archive.writestr("extra/" if kind == "directory" else "extra", b"x")
        payload = output.getvalue()
    elif kind == "false_count":
        raw = bytearray(payload)
        raw[-12:-10] = (4).to_bytes(2, "little")
        payload = bytes(raw)
    elif kind == "manifest_size":
        payload = _rewrite(payload, lambda name, data: (
            b" " * 65537 if name == "manifest.json" else data))
    else:
        payload = b"x" * (8 * 1024 * 1024 + 1)
    result = _compare(after=payload)
    assert not result["ok"] and result["code"] in {"invalid_bundle", "size_limit"}


@pytest.mark.parametrize("kind", ["columns", "cell", "rows", "bytes", "duplicate", "utf8"])
def test_csv_boundaries_and_duplicate_keys(kind):
    def change(_manifest, review, _target):
        if kind == "columns":
            review.append(["x"] * 9)
        elif kind == "cell":
            review.append(["ignored", "key", "x" * 4097])
        elif kind == "rows":
            review.extend([["ignored", "key", "x"]] * 4096)
        elif kind == "bytes":
            review.extend([["ignored", "key", "x" * 4096]] * 520)
        else:
            review.append(["current", "known_value", "1000.00"])
    if kind == "utf8":
        with ZipFile(io.BytesIO(_bundle())) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            contents = {name: archive.read(name) for name in archive.namelist()[:-1]}
        contents["review-pack.csv"] = b"\xff"
        raw = _archive(manifest, contents)
    else:
        raw = _bundle(mutate=change)
    result = _compare(after=raw)
    assert not result["ok"] and result["code"] in {"size_limit", "invalid_receipt"}


def test_actual_exporter_bundles_compare_read_only(db):
    from sqlalchemy import event
    from app.models import Holding
    from app.services import review_bundle

    db.add(Holding(portfolio_id=1, ticker="AAA", shares=10, avg_cost=80,
                   is_active=True, target_weight_bps=10000))
    db.commit()
    def readonly(_conn, _cursor, statement, _params, _context, _many):
        assert statement.lstrip().split()[0].upper() in {"SELECT", "BEGIN", "PRAGMA"}
    event.listen(db.get_bind(), "before_cursor_execute", readonly)
    def capture(price):
        return review_bundle.build_review_bundle(
            db, 1, "month", generated_at=datetime(2026, 11, 25, 12, tzinfo=timezone.utc),
            quote_loader=lambda tickers: [
                {"ticker": ticker, "current_price": price, "currency": "USD"} for ticker in tickers
            ],
        )
    try:
        result = _compare(capture(100), capture(101.023))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", readonly)
    assert result["ok"] and result["known_value"]["delta"] == "10.23"


def test_pure_module_never_initializes_a_profile_database_or_network(tmp_path):
    script = """
import json, os, socket, sqlite3, sys
from pathlib import Path
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external access')
socket.socket.connect = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
profile = Path(os.environ['FOLIOORB_DATA_DIR'])
assert list(profile.iterdir()) == []
from app.services.review_comparison import compare_review_bundles
raw = sys.stdin.buffer.read()
result = compare_review_bundles(raw, raw, same_portfolio_confirmed=True)
assert result['ok']
assert not {'app.config', 'app.database', 'app.models', 'sqlalchemy'} & sys.modules.keys()
assert list(profile.iterdir()) == []
print(json.dumps(result))
"""
    env = dict(os.environ, FOLIOORB_DATA_DIR=str(tmp_path), ANTHROPIC_API_KEY="",
               DATABASE_URL="sqlite:///" + str(tmp_path / "database" / "test.db"),
               PYTHONDONTWRITEBYTECODE="1", FOLIO_DISABLE_UPDATE_SCHEDULER="1")
    result = subprocess.run([sys.executable, "-S", "-c", script], input=_bundle(),
                            capture_output=True, env=env, check=True,
                            cwd=Path(__file__).resolve().parents[1])
    assert json.loads(result.stdout)["changed"] is False


def test_many_entry_directory_is_rejected_before_zipfile_allocation(monkeypatch):
    from app.services import review_bundle_verification as verifier
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for index in range(1200):
            archive.writestr(f"entry-{index:05d}-padding", b"")
    raw = bytearray(output.getvalue())
    raw[-14:-10] = b"\x05\x00\x05\x00"  # Dishonest entry counts.
    def forbidden(*_args, **_kwargs):
        raise AssertionError("ZipFile must not allocate this directory")
    monkeypatch.setattr(verifier, "ZipFile", forbidden)
    result = compare_review_bundles(bytes(raw), bytes(raw), same_portfolio_confirmed=True)
    assert result["code"] == "size_limit"


def test_maximum_sized_pair_memory_budget():
    """Include fixture bytes retained by the caller; traced peak is not an RSS guarantee."""
    tracemalloc.start()
    try:
        raw = _bundle(targets={f"T{index:04d}": "5" for index in range(2000)})
        with ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            contents = {name: archive.read(name) for name in archive.namelist()[:-1]}
        # Inert HTML reaches the aggregate decompression boundary; neither parsed nor rendered.
        contents["review-pack.html"] = b"x" * (8 * 1024 * 1024 - 256 * 1024)
        raw = _archive(manifest, contents, compression=ZIP_STORED)
        other = bytes(bytearray(raw))
        result = _compare(raw, other)
        assert result["ok"] and len(result["targets"]) == 2000
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 96 * 1024 * 1024
    print(f"accepted_pair_traced_peak_bytes={peak}; input_bytes={len(raw) + len(other)}")


@pytest.mark.parametrize("kind", ["directory", "wide_csv", "long_csv", "nested_json"])
def test_rejected_input_memory_budget(kind):
    if kind == "directory":
        output = io.BytesIO()
        with ZipFile(output, "w", compression=ZIP_STORED) as archive:
            for index in range(50000):
                archive.writestr(f"{index:05d}", b"")
        raw_bytes = bytearray(output.getvalue())
        raw_bytes[-14:-10] = b"\x05\x00\x05\x00"
        raw = bytes(raw_bytes)
    else:
        with ZipFile(io.BytesIO(_bundle())) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            contents = {name: archive.read(name) for name in archive.namelist()[:-1]}
        if kind == "nested_json":
            raw = _rewrite(_bundle(), lambda name, data: (
                b"[" * 30000 + b"]" * 30000 if name == "manifest.json" else data))
        else:
            contents["review-pack.csv"] = (
                b"," * (2 * 1024 * 1024 - 1) if kind == "wide_csv"
                else b"x" * (2 * 1024 * 1024)
            )
            raw = _archive(manifest, contents, compression=ZIP_STORED)
    other = bytes(bytearray(raw))
    # Inputs are already allocated: add their exact live sizes to the measured
    # allocations during comparison. Fixture-building overhead is not acceptance.
    tracemalloc.start()
    try:
        result = _compare(raw, other)
        peak = tracemalloc.get_traced_memory()[1] + sys.getsizeof(raw) + sys.getsizeof(other)
    finally:
        tracemalloc.stop()
    assert not result["ok"] and peak < 96 * 1024 * 1024
    print(f"rejected_{kind}_traced_peak_with_inputs={peak}; input_bytes={len(raw) + len(other)}")


def test_supported_csv_and_target_boundaries_and_excess_target_row():
    def at_limit(_manifest, review, _target):
        review.extend([["ignored", "key", "x"] for _ in range(4096 - len(review))])
        review[-1][-1] = "x" * 4096
    assert _compare(after=_bundle(mutate=at_limit))["ok"]
    result = _compare(after=_bundle(targets={f"T{i:04d}": "0" for i in range(2001)}))
    assert result["code"] == "size_limit"


@pytest.mark.parametrize("receipt", ["review", "target"])
def test_missing_value_receipt_is_not_filled_from_the_other(receipt):
    def change(_manifest, review, target):
        rows = review if receipt == "review" else target
        rows[:] = [row for row in rows if not (
            row[:2] == ["current", "known_value"] if receipt == "review"
            else row and row[0] == "known_value")]
    result = _compare(after=_bundle(mutate=change))
    assert result["ok"] and result["known_value"]["delta"] is None
    if receipt == "review":
        assert result["known_value"]["after"] is None
    else:
        assert result["coverage"]["changed"]


def test_extra_decompressed_bytes_are_rejected():
    raw = _rewrite(_bundle(), lambda name, data: (
        b"x" * (8 * 1024 * 1024) if name.endswith("html") else data))
    result = _compare(after=raw)
    assert result["code"] == "size_limit"


@pytest.mark.parametrize("payload", [None, b"", bytearray(b"zip"), "zip", 2])
def test_invalid_input_types_return_safe_results(payload):
    result = compare_review_bundles(payload, _bundle(), same_portfolio_confirmed=True)
    assert not result["ok"] and result["code"] == "invalid_bundle"
