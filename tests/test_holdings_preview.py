"""Read-only CSV acceptance against real routing, validation and disposable SQL."""

import csv
import hashlib
import io
import re
from contextlib import contextmanager

import pytest
from sqlalchemy import event, select

from app.config import settings
from app.models import Base, Holding, Portfolio
from app.routers import portfolio as routes
from app.services import holdings_csv, stock_service

HEADER = "ticker,shares,avg_cost,is_watchlist,hold_class,notes"
URL = "/api/portfolio/holdings/preview"


@pytest.fixture(name="validator", autouse=True)
def _validator(monkeypatch, db):
    calls = []

    def validate(ticker):
        assert not db.in_transaction(), "provider must not retain the read transaction"
        calls.append(ticker)
        return {"valid": True}

    monkeypatch.setattr(routes, "validate_ticker_symbol", validate)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "synthetic-configured-key")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Preview must never invoke Claude")

    monkeypatch.setattr(holdings_csv, "remap_columns_with_claude", forbidden)
    monkeypatch.setattr(holdings_csv, "narrate_import_summary", forbidden)
    return calls


def snapshot(db):
    return {
        table.name: list(db.execute(select(table)).all()) for table in Base.metadata.sorted_tables
    }


@contextmanager
def no_writes(db):
    before = snapshot(db)
    writes = []

    def inspect(_conn, _cursor, statement, _params, _context, _many):
        if re.match(
            r"\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM|ATTACH)\b", statement, re.I
        ):
            writes.append(statement)
            raise AssertionError("Preview attempted a SQL write")

    event.listen(db.bind, "before_cursor_execute", inspect)
    try:
        yield
    finally:
        event.remove(db.bind, "before_cursor_execute", inspect)
    assert not writes
    assert snapshot(db) == before


def preview(client, db, text, *, portfolio_id=1, filename="fictional.csv", media="text/csv"):
    with no_writes(db):
        with client(routes.router) as http:
            return http.post(
                URL, params={"portfolio_id": portfolio_id}, files={"file": (filename, text, media)}
            )


def test_preview_normalizes_and_skips_without_any_table_write(api_client, db, validator, caplog):
    db.add(Holding(portfolio_id=1, ticker="MSFT", shares=1, avg_cost=10, is_active=True))
    db.commit()
    text = (
        HEADER + "\n syn ,0.125,2.50,false,CORE,  =1+1  \n"
        "SYN,5,2,false,auto,duplicate\nMSFT,2,3,false,auto,existing\n"
        "WATCH,0,,true,trade,Research\nBAD,-1,2,false,auto,bad\n"
    )
    response = preview(api_client, db, text)
    assert response.status_code == 200
    data = response.json()
    assert data["portfolio"] == {"id": 1, "name": "Test Portfolio"}
    assert data["input_digest"] == hashlib.sha256(text.encode()).hexdigest()
    assert data["mode"] == "local" and data["saved"] is False
    assert (data["would_add"], data["skipped"], data["errors"]) == (2, 2, 1)
    assert "added" not in data
    first = data["rows"][0]
    assert first["status"] == "would_add" and first["normalized"] is True
    assert first["values"] == {
        "ticker": "SYN",
        "shares": 0.125,
        "avg_cost": 2.5,
        "is_watchlist": False,
        "hold_class": "core",
        "notes": "=1+1",
    }
    assert data["rows"][1]["values"]["shares"] == 5
    assert data["rows"][3]["values"]["is_watchlist"] is True
    assert data["rows"][4]["normalized"] is False
    assert data["rows"][4]["values"]["shares"] == "-1"
    assert validator == ["SYN", "WATCH"]
    assert "=1+1" not in caplog.text and "fictional.csv" not in caplog.text


@pytest.mark.parametrize(
    "text,status",
    [
        ("", 400),
        ("ticker,shares\n", 400),
        ("ticker,ticker\nA,B\n", 400),
        ("ticker,,shares\nSYN,x,1\n", 400),
        (",\nSYN,1\n", 400),
        ("Symbol,Qty\nSYN,1\n", 400),
        ("ticker,shares\nSYN\n", 400),
        ("ticker,shares\nSYN,1,extra\n", 400),
        ('ticker,notes\nSYN,"unterminated\n', 400),
        (b"\x81", 415),
        ("ticker,shares\nSYN,1".encode("utf-16"), 415),
        (b"x" * (holdings_csv.MAX_IMPORT_BYTES + 1), 413),
    ],
)
def test_bad_files_do_not_write_or_reach_provider(api_client, db, validator, text, status):
    assert preview(api_client, db, text).status_code == status
    assert not validator


@pytest.mark.parametrize(
    "shares,cost,ticker",
    [
        ("nan", "1", "SYN"),
        ("inf", "1", "SYN"),
        ("1", "NaN", "SYN"),
        ("1", "Infinity", "SYN"),
        ("-1", "1", "SYN"),
        ("1", "1", "BAD/TICKER"),
    ],
)
def test_invalid_values_are_row_errors(api_client, db, validator, *, shares, cost, ticker):
    data = preview(api_client, db, f"ticker,shares,avg_cost\n{ticker},{shares},{cost}\n").json()
    assert data["errors"] == 1 and data["would_add"] == 0
    assert not validator


def test_provider_failure_is_uncertain_using_actual_validator(
    api_client, db, monkeypatch, fake_market_data
):
    fake = fake_market_data()
    monkeypatch.setattr(routes, "validate_ticker_symbol", stock_service.validate_ticker_symbol)
    data = preview(api_client, db, "ticker,shares,notes\nSYN,1,private-note-sentinel\n").json()
    assert data["errors"] == 1
    assert "provider unavailable" in data["rows"][0]["reason"]
    assert "Couldn't find ticker" not in data["rows"][0]["reason"]
    assert fake.calls and all("private-note-sentinel" not in str(c) for c in fake.calls)


def test_missing_default_is_not_seeded(api_client, db, validator):
    db.query(Portfolio).delete()
    db.commit()
    assert preview(api_client, db, "ticker,shares\nSYN,1\n").status_code == 404
    assert db.query(Portfolio).count() == 0 and validator == []


def test_wrong_portfolio_and_existing_tickers_are_scoped(api_client, db):
    db.add(Portfolio(id=2, name="Other fictional portfolio"))
    db.add(Holding(portfolio_id=2, ticker="SYN", shares=1, is_active=True))
    db.commit()
    assert preview(api_client, db, "ticker,shares\nSYN,1\n", portfolio_id=999).status_code == 404
    one = preview(api_client, db, "ticker,shares\nSYN,1\n").json()
    two = preview(api_client, db, "ticker,shares\nSYN,1\n", portfolio_id=2).json()
    assert one["would_add"] == 1 and two["skipped"] == 1
    assert two["portfolio"]["name"] == "Other fictional portfolio"


def test_row_cap_boundary_and_all_rows_available(api_client, db, validator):
    text = "ticker,shares\n" + "".join(f"T{i:03},1\n" for i in range(200))
    data = preview(api_client, db, text).json()
    assert data["would_add"] == len(data["rows"]) == 200
    validator.clear()
    assert preview(api_client, db, text + "EXTRA,1\n").status_code == 400
    assert not validator


@pytest.mark.parametrize("prefix", ["", "\ufeff"])
def test_quoted_and_multiline_notes_and_bom(api_client, db, prefix):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(HEADER.split(","))
    writer.writerow(["SYN", "1.25", "2.5", "false", "auto", 'Comma, "quote"\nand line'])
    data = preview(api_client, db, prefix + output.getvalue()).json()
    assert data["rows"][0]["values"]["notes"] == 'Comma, "quote"\nand line'


@pytest.mark.parametrize("length,errors", [(500, 0), (501, 1)])
def test_note_length_boundary(api_client, db, length, errors):
    data = preview(api_client, db, f'ticker,shares,notes\nSYN,1,{"n" * length}\n').json()
    assert data["errors"] == errors


def test_inherited_normalization_is_displayed(api_client, db):
    data = preview(
        api_client, db, "ticker,shares,avg_cost,is_watchlist\nSYN,1e308,1e308,nonsense\n"
    ).json()
    assert data["would_add"] == 1
    assert data["rows"][0]["values"]["shares"] == 1e308
    assert data["rows"][0]["values"]["is_watchlist"] is False


@pytest.mark.parametrize(
    "media,filename,status",
    [
        ("application/pdf", "a.csv", 415),
        ("text/plain", "a.txt", 415),
        ("text/plain", "a.csv", 200),
        ("application/octet-stream", "a.csv", 200),
    ],
)
def test_mime_and_extension(api_client, db, *, media, filename, status):
    assert (
        preview(
            api_client, db, "ticker,shares\nSYN,1\n", media=media, filename=filename
        ).status_code
        == status
    )


def test_legacy_parser_and_default_report_contract_remain_unchanged():
    raw = b"ticker,shares\nSYN,1,discarded\n"
    _header, rows = holdings_csv.parse_import_upload(raw, "a.csv", "text/csv")
    assert rows == [{"ticker": "SYN", "shares": "1"}]
    report, _ = holdings_csv.process_import_rows(rows, set(), lambda _ticker: {"valid": True})
    assert report == [{"row": 2, "ticker": "SYN", "status": "added", "reason": None}]
    with pytest.raises(holdings_csv.ImportFileError):
        holdings_csv.parse_import_upload(raw, "a.csv", "text/csv", strict=True)
