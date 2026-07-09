"""
Unit tests for app/services/holdings_csv.py — parse, strict validation, cell
cleaning, injection escaping, export round-trip, and the Claude remapper /
narration. The Anthropic client is always mocked; no real API calls.
"""
# pylint: disable=protected-access,redefined-outer-name
import json
from unittest.mock import MagicMock

import pytest

from app.services import ai_service, holdings_csv as hc


# ── Fixtures / helpers ──────────────────────────────────────────────────────

class _Holding:
    """Minimal stand-in for the SQLAlchemy Holding row (export reads attributes)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _mock_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    msg.usage.input_tokens = 40
    msg.usage.output_tokens = 12
    return msg


@pytest.fixture
def mock_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ai_service, "client", client)
    return client


def _ok(ticker, **_):
    return {"valid": True, "ticker": ticker, "suggestions": []}


def _bad(ticker, **_):
    return {
        "valid": False,
        "ticker": ticker,
        "message": f"Couldn't find ticker {ticker} — check the symbol",
        "suggestions": [{"ticker": "MARA"}],
    }


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_strict_parse_happy_shuffled_columns():
    text = "notes,hold_class,is_watchlist,avg_cost,shares,ticker\nlong,core,false,412.5,10,voo\n"
    header, rows = hc.parse_csv_text(text)
    assert set(header) == set(hc.CSV_COLUMNS)
    kwargs = hc.strict_row_to_create_kwargs(rows[0])
    assert kwargs["ticker"] == "VOO"
    assert kwargs["shares"] == 10.0
    assert kwargs["avg_cost"] == 412.5
    assert kwargs["hold_class"] == "core"


def test_optional_columns_default():
    header, rows = hc.parse_csv_text("ticker,shares\nAAPL,5\n")
    assert not hc.unrecognized_columns(header)
    kwargs = hc.strict_row_to_create_kwargs(rows[0])
    assert kwargs["is_watchlist"] is False
    assert "hold_class" not in kwargs  # HoldingCreate defaults it to auto


def test_blank_lines_skipped():
    _header, rows = hc.parse_csv_text("ticker,shares\n\nAAPL,5\n   \nMSFT,2\n")
    assert len(rows) == 2


def test_whitespace_only_file_has_no_rows():
    _header, rows = hc.parse_csv_text("ticker,shares\n   \n\n")
    assert not rows


# ── Decoding ────────────────────────────────────────────────────────────────

def test_bom_stripped():
    raw = "﻿ticker,shares\nAAPL,5\n".encode("utf-8")
    text = hc.decode_csv_bytes(raw)
    header, _rows = hc.parse_csv_text(text)
    assert header[0] == "ticker"  # BOM gone


def test_cp1252_fallback():
    raw = "ticker,notes\nAAPL,caf\xe9\n".encode("cp1252")
    text = hc.decode_csv_bytes(raw)
    assert "caf" in text


def test_nul_bytes_rejected():
    with pytest.raises(ValueError):
        hc.decode_csv_bytes(b"ticker,shares\x00\nAAPL,5")


# ── unrecognized_columns ────────────────────────────────────────────────────

def test_clean_header_recognized():
    header, _ = hc.parse_csv_text("ticker,shares,avg_cost,is_watchlist,hold_class,notes\n")
    assert not hc.unrecognized_columns(header)


def test_messy_header_flagged_case_insensitive():
    header, _ = hc.parse_csv_text(" Symbol , Qty \nAAPL,10\n")
    assert hc.unrecognized_columns(header) == ["symbol", "qty"]


# ── Strict numbers vs Claude cleaning ───────────────────────────────────────

def test_strict_currency_is_row_error():
    from app.schemas import HoldingCreate
    from pydantic import ValidationError
    kwargs = hc.strict_row_to_create_kwargs({"ticker": "AAPL", "shares": "$1,234.56"})
    with pytest.raises(ValidationError):
        HoldingCreate(**kwargs)


def test_clean_cell_number_variants():
    assert hc.clean_cell_number("$1,234.56") == "1234.56"
    assert hc.clean_cell_number("(50)") == "-50"
    assert hc.clean_cell_number("12%") == "12"
    assert hc.clean_cell_number("  ") == ""


def test_clean_cell_number_unicode_minus():
    assert hc.clean_cell_number("−50") == "-50"        # U+2212 minus
    assert hc.clean_cell_number("(−50)") == "-50"      # parens + unicode minus


def test_num_str_no_scientific_notation():
    # A tiny fractional share count must render as a plain decimal, not '1e-06'.
    holds = [_Holding(ticker="BTC", shares=0.000001, avg_cost=30000.0,
                      is_watchlist=False, hold_class="auto", notes="")]
    out = "".join(hc.build_export_csv(holds))
    assert "e-" not in out.lower()
    assert "0.000001" in out


def test_num_str_preserves_satoshi_precision():
    # 1e-8 (a satoshi of BTC) must NOT collapse to '0' — that would lose the position.
    holds = [_Holding(ticker="BTC", shares=0.00000001, avg_cost=30000.0,
                      is_watchlist=False, hold_class="auto", notes="")]
    out = "".join(hc.build_export_csv(holds))
    assert "0.00000001" in out
    # And it round-trips back to the same value.
    _header, rows = hc.parse_csv_text(hc.decode_csv_bytes(out.encode("utf-8")))
    assert hc.strict_row_to_create_kwargs(rows[0])["shares"] == 0.00000001


def test_num_str_large_fraction_no_float_artifacts():
    holds = [_Holding(ticker="X", shares=1234567.89, avg_cost=1.0,
                      is_watchlist=False, hold_class="auto", notes="")]
    out = "".join(hc.build_export_csv(holds))
    assert "1234567.89" in out and "1234567.889" not in out


def test_duplicate_columns():
    assert hc.duplicate_columns(["ticker", "shares", "ticker", "notes"]) == ["ticker"]
    assert hc.duplicate_columns(["ticker", "shares"]) == []
    assert hc.duplicate_columns(["", "", "ticker"]) == []  # empty names ignored


def test_num_str_non_finite_is_blank():
    # A corrupt nan/inf must export as blank, never crash the stream.
    assert hc._num_str(float("nan")) == ""
    assert hc._num_str(float("inf")) == ""
    holds = [_Holding(ticker="X", shares=float("inf"), avg_cost=float("nan"),
                      is_watchlist=True, hold_class="auto", notes="")]
    out = "".join(hc.build_export_csv(holds))  # must not raise
    assert "X,,," in out


def test_clean_cell_bool_variants():
    assert hc.clean_cell_bool("Yes") == "true"
    assert hc.clean_cell_bool("TRUE") == "true"
    assert hc.clean_cell_bool("0") == "false"
    assert hc.clean_cell_bool("N") == "false"
    assert hc.clean_cell_bool("maybe") == ""


# ── Injection escaping ──────────────────────────────────────────────────────

@pytest.mark.parametrize("cell", ["=SUM(A1)", "+1", "-X", "@cmd", "\ttab", "\rcr"])
def test_escape_dangerous_cells(cell):
    assert hc.escape_csv_cell(cell).startswith("'")


@pytest.mark.parametrize("cell", ["VOO", "10", "café", ""])
def test_escape_benign_cells_untouched(cell):
    assert hc.escape_csv_cell(cell) == cell


# ── Export + round-trip ─────────────────────────────────────────────────────

def test_export_header_bom_and_quoting():
    holds = [
        _Holding(ticker="VOO", shares=10.0, avg_cost=412.5,
                 is_watchlist=False, hold_class="auto", notes='hi, "there"\nline'),
        _Holding(ticker="NVDA", shares=0.0, avg_cost=None,
                 is_watchlist=True, hold_class="auto", notes="=danger"),
    ]
    out = "".join(hc.build_export_csv(holds))
    assert out.startswith("﻿")
    assert "ticker,shares,avg_cost,is_watchlist,hold_class,notes" in out
    assert "'=danger" in out          # formula neutralized
    assert '"hi, ""there""' in out    # comma+quote survived quoted


def test_round_trip_export_import():
    holds = [
        _Holding(ticker="VOO", shares=10.0, avg_cost=412.5,
                 is_watchlist=False, hold_class="core", notes="keep, forever"),
        _Holding(ticker="NVDA", shares=2.5, avg_cost=None,
                 is_watchlist=True, hold_class="auto", notes=""),
    ]
    out = "".join(hc.build_export_csv(holds))
    header, rows = hc.parse_csv_text(hc.decode_csv_bytes(out.encode("utf-8")))
    assert not hc.unrecognized_columns(header)
    first = hc.strict_row_to_create_kwargs(rows[0])
    assert first["ticker"] == "VOO"
    assert first["shares"] == 10.0
    assert first["avg_cost"] == 412.5
    assert first["hold_class"] == "core"
    assert first["notes"] == "keep, forever"
    second = hc.strict_row_to_create_kwargs(rows[1])
    assert second["ticker"] == "NVDA"
    assert second["is_watchlist"] is True
    assert second["shares"] == 2.5


# ── Remapper ────────────────────────────────────────────────────────────────

_GOOD_MAP = (
    '```json\n{"mapping":{"ticker":"symbol","shares":"qty","avg_cost":"cost",'
    '"is_watchlist":null,"hold_class":null,"notes":"desc"}}\n```'
)


def test_remap_happy_strips_fences_and_applies(mock_client):
    mock_client.messages.create.return_value = _mock_response(_GOOD_MAP)
    header = ["symbol", "qty", "cost", "desc"]
    rows = [{"symbol": "AAPL", "qty": "$1,000", "cost": "150.5", "desc": "core"},
            {"symbol": "MSFT", "qty": "3", "cost": "200", "desc": ""}]
    mapping = hc.remap_columns_with_claude(header, rows)
    assert mapping["ticker"] == "symbol"
    applied = hc.apply_mapping(mapping, rows)
    assert applied[0]["shares"] == "1000"      # cleaned on ALL rows, not just the sample
    assert applied[1]["shares"] == "3"
    assert applied[0]["notes"] == "core"


def test_remap_garbage_raises(mock_client):
    mock_client.messages.create.return_value = _mock_response("sorry, cannot help")
    with pytest.raises(hc.RemapError):
        hc.remap_columns_with_claude(["symbol"], [{"symbol": "AAPL"}])


def test_remap_null_ticker_raises(mock_client):
    mock_client.messages.create.return_value = _mock_response('{"mapping":{"ticker":null}}')
    with pytest.raises(hc.RemapError):
        hc.remap_columns_with_claude(["symbol"], [{"symbol": "AAPL"}])


def test_remap_source_not_in_header_raises(mock_client):
    mock_client.messages.create.return_value = _mock_response('{"mapping":{"ticker":"nope"}}')
    with pytest.raises(hc.RemapError):
        hc.remap_columns_with_claude(["symbol"], [{"symbol": "AAPL"}])


def test_remap_api_exception_raises(mock_client):
    mock_client.messages.create.side_effect = RuntimeError("boom")
    with pytest.raises(hc.RemapError):
        hc.remap_columns_with_claude(["symbol"], [{"symbol": "AAPL"}])


def test_remap_payload_caps_rows_and_cells(mock_client):
    mock_client.messages.create.return_value = _mock_response(
        '{"mapping":{"ticker":"symbol"}}'
    )
    header = ["symbol"]
    rows = [{"symbol": f"T{i}"} for i in range(20)]
    rows[5]["symbol"] = "ROW6MARKER"
    hc.remap_columns_with_claude(header, rows)
    sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "ROW6MARKER" not in sent  # only REMAP_SAMPLE_ROWS (5) rows serialized


def test_remap_long_cell_truncated(mock_client):
    mock_client.messages.create.return_value = _mock_response(
        '{"mapping":{"ticker":"symbol"}}'
    )
    long = "A" * 200
    hc.remap_columns_with_claude(["symbol"], [{"symbol": long}])
    sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert long not in sent  # cell truncated to REMAP_CELL_CHARS


def test_remap_freetext_cell_placeholdered(mock_client):
    mock_client.messages.create.return_value = _mock_response(
        '{"mapping":{"ticker":"symbol"}}'
    )
    hc.remap_columns_with_claude(
        ["symbol", "junk"],
        [{"symbol": "AAPL", "junk": "buy 50 @ open <secret> {note}"}],
    )
    sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "secret" not in sent
    payload = json.loads(sent)
    assert payload["rows"][0]["junk"] == hc._SAMPLE_PLACEHOLDER


# ── Narration ───────────────────────────────────────────────────────────────

def test_narrate_happy(mock_client):
    mock_client.messages.create.return_value = _mock_response("Two aboard, one skipped.")
    out = hc.narrate_import_summary(
        {"added": 2, "skipped": 1, "errors": 0,
         "rows": [{"reason": "already in portfolio"}]}
    )
    assert out == "Two aboard, one skipped."


def test_narrate_failure_returns_none(mock_client):
    mock_client.messages.create.side_effect = RuntimeError("down")
    assert hc.narrate_import_summary({"added": 0}) is None


# ── process_import_rows ─────────────────────────────────────────────────────

def test_process_dedupe_and_errors():
    rows = [
        {"ticker": "VOO", "shares": "10", "avg_cost": "412.5",
         "is_watchlist": "false", "hold_class": "auto", "notes": ""},
        {"ticker": "voo", "shares": "5", "is_watchlist": "false"},   # in-file dup
        {"ticker": "MSFT", "shares": "3", "is_watchlist": "false"},  # already in portfolio
        {"ticker": "AAPL", "shares": "0", "is_watchlist": "false"},  # pydantic error
    ]
    report, to_insert = hc.process_import_rows(rows, {"MSFT"}, _ok)
    by_row = {r["row"]: r for r in report}
    assert by_row[2]["status"] == "added"
    assert by_row[3]["status"] == "skipped" and "duplicate of row 2" in by_row[3]["reason"]
    assert by_row[4]["status"] == "skipped" and by_row[4]["reason"] == "already in portfolio"
    assert by_row[5]["status"] == "error"
    assert [c.ticker for c in to_insert] == ["VOO"]


def test_process_invalid_ticker_includes_suggestions_and_date_hint():
    rows = [{"ticker": "26-MAR", "shares": "1", "is_watchlist": "false"}]
    report, to_insert = hc.process_import_rows(rows, set(), _bad)
    assert not to_insert
    reason = report[0]["reason"]
    assert "MARA" in reason
    assert "Excel may have reformatted" in reason


def test_process_watchlist_zero_shares_ok():
    rows = [{"ticker": "NVDA", "shares": "0", "is_watchlist": "true"}]
    report, to_insert = hc.process_import_rows(rows, set(), _ok)
    assert report[0]["status"] == "added"
    assert to_insert[0].is_watchlist is True


def test_summarize_counts():
    report = [
        {"status": "added"}, {"status": "added"},
        {"status": "skipped"}, {"status": "error"},
    ]
    assert hc.summarize(report) == {"added": 2, "skipped": 1, "errors": 1}
