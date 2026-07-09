"""HTTP-level tests for the CSV export/import endpoints.

Mounts only the portfolio router on a bare FastAPI app (pattern from
tests/test_earnings_radar_router.py) with an in-memory SQLite DB, so the full
app lifespan never runs. Network ticker validation and quote warming are
monkeypatched in the router namespace; Claude is mocked at the ai_service
client — no live API calls.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import get_db
from app.models import Base, Holding, Portfolio
from app.routers import portfolio as portfolio_router
from app.services import ai_service


TEMPLATE_HEADER = "ticker,shares,avg_cost,is_watchlist,hold_class,notes"


def _make_db(seed=("MSFT",)):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)  # pylint: disable=invalid-name
    db = Session()
    db.add(Portfolio(id=1, name="Test"))
    for ticker in seed:
        db.add(Holding(portfolio_id=1, ticker=ticker, shares=10, avg_cost=100,
                       is_active=True, is_watchlist=False, hold_class="auto"))
    db.commit()
    return db


@pytest.fixture
def db():
    return _make_db()


@pytest.fixture
def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(portfolio_router.router)
    app.dependency_overrides[get_db] = lambda: db
    # Keep everything offline: pretend every ticker validates, and no-op the warm.
    monkeypatch.setattr(
        portfolio_router, "validate_ticker_symbol",
        lambda t, **k: {"valid": True, "ticker": t, "suggestions": []},
    )
    monkeypatch.setattr(portfolio_router, "get_all_quotes", lambda ts: [])
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")  # default: no key
    return TestClient(app)


def _upload(csv_text, filename="holdings.csv", content_type="text/csv"):
    return {"file": (filename, csv_text, content_type)}


def _mock_response(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    msg.usage.input_tokens = 20
    msg.usage.output_tokens = 8
    return msg


# ── Export ───────────────────────────────────────────────────────────────────

def test_export_headers_and_content(db, client):
    db.add(Holding(portfolio_id=1, ticker="VOO", shares=3, avg_cost=400,
                   is_active=True, is_watchlist=True, hold_class="auto", notes="=danger"))
    db.commit()
    res = client.get("/api/portfolio/holdings/export")
    assert res.status_code == 200
    disp = res.headers["content-disposition"]
    assert disp.startswith("attachment; filename=\"foliosense-holdings-p1-")
    body = res.content.decode("utf-8")
    assert body.startswith("﻿")
    assert TEMPLATE_HEADER in body
    assert "'=danger" in body          # formula neutralized on export
    assert "VOO,3,400,true,auto" in body


def test_export_unknown_portfolio_404(client):
    assert client.get("/api/portfolio/holdings/export?portfolio_id=999").status_code == 404


# ── Import: local (no key) ───────────────────────────────────────────────────

def test_import_local_happy(db, client):
    csv_text = (f"{TEMPLATE_HEADER}\n"
                "VOO,10,412.5,false,auto,\n"
                "AAPL,3,180,false,core,my note\n")
    res = client.post("/api/portfolio/holdings/import", files=_upload(csv_text))
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "local"
    assert body["summary"] is None
    assert body["added"] == 2
    added = db.query(Holding).filter(Holding.ticker.in_(["VOO", "AAPL"])).all()
    assert {h.ticker for h in added} == {"VOO", "AAPL"}
    aapl = db.query(Holding).filter(Holding.ticker == "AAPL").first()
    assert aapl.hold_class == "core"
    assert aapl.notes == "my note"


def test_import_dup_skip_infile_and_portfolio(client):
    csv_text = (f"{TEMPLATE_HEADER}\n"
                "VOO,10,,false,auto,\n"
                "VOO,5,,false,auto,\n"      # in-file duplicate
                "MSFT,2,,false,auto,\n")    # already in portfolio
    body = client.post("/api/portfolio/holdings/import", files=_upload(csv_text)).json()
    by_row = {r["row"]: r for r in body["rows"]}
    assert by_row[2]["status"] == "added"
    assert by_row[3]["status"] == "skipped" and "duplicate" in by_row[3]["reason"]
    assert by_row[4]["status"] == "skipped" and by_row[4]["reason"] == "already in portfolio"
    assert body["added"] == 1 and body["skipped"] == 2


def test_import_bad_rows_reported_partial_success(db, client):
    csv_text = (f"{TEMPLATE_HEADER}\n"
                "GOOD,4,,false,auto,\n"
                "BAD$,4,,false,auto,\n"        # bad ticker shape
                "ZERO,0,,false,auto,\n"        # non-watchlist shares=0
                "WRONG,4,,false,badclass,\n")  # bad hold_class
    body = client.post("/api/portfolio/holdings/import", files=_upload(csv_text)).json()
    assert body["added"] == 1
    assert body["errors"] == 3
    assert db.query(Holding).filter(Holding.ticker == "GOOD").first() is not None


def test_import_header_mismatch_local_400(client):
    body = client.post("/api/portfolio/holdings/import", files=_upload("Symbol,Qty\nAAPL,10\n"))
    assert body.status_code == 400
    detail = body.json()["detail"]
    assert detail["mode"] == "local"
    assert detail["unrecognized_columns"] == ["symbol", "qty"]
    assert detail["expected_columns"] == list(portfolio_router.holdings_csv.CSV_COLUMNS)


def test_import_oversize_413(client):
    big = f"{TEMPLATE_HEADER}\n" + ("AAPL,1,,false,auto,\n" * 40000)
    assert client.post("/api/portfolio/holdings/import",
                       files=_upload(big)).status_code == 413


def test_import_row_cap_400(client):
    rows = f"{TEMPLATE_HEADER}\n" + ("AAPL,1,,false,auto,\n" * 201)
    res = client.post("/api/portfolio/holdings/import", files=_upload(rows))
    assert res.status_code == 400
    assert "Too many rows" in res.json()["detail"]


def test_import_wrong_content_type_415(client):
    res = client.post("/api/portfolio/holdings/import",
                      files=_upload("data", filename="x.png", content_type="image/png"))
    assert res.status_code == 415


def test_import_empty_content_type_with_csv_name_accepted(client):
    # Some browsers send no MIME type for a .csv; a .csv filename should still pass.
    csv_text = f"{TEMPLATE_HEADER}\nAAPL,1,,false,auto,\n"
    res = client.post("/api/portfolio/holdings/import",
                      files=_upload(csv_text, filename="holdings.csv", content_type=""))
    assert res.status_code == 200


def test_import_duplicate_columns_400(client):
    res = client.post("/api/portfolio/holdings/import",
                      files=_upload("ticker,shares,ticker\nAAPL,10,MSFT\n"))
    assert res.status_code == 400
    assert "Duplicate column" in res.json()["detail"]


def test_import_overflow_shares_rejected_not_stored(db, client):
    # A cell like '1e400' overflows to inf; it must be a row error, never stored.
    csv_text = f"{TEMPLATE_HEADER}\nBIG,1e400,,false,auto,\nGOOD,5,,false,auto,\n"
    body = client.post("/api/portfolio/holdings/import", files=_upload(csv_text)).json()
    by_ticker = {r["ticker"]: r for r in body["rows"]}
    assert by_ticker["BIG"]["status"] == "error"
    assert db.query(Holding).filter(Holding.ticker == "BIG").first() is None
    assert db.query(Holding).filter(Holding.ticker == "GOOD").first() is not None


def test_import_empty_400(client):
    assert client.post("/api/portfolio/holdings/import",
                       files=_upload(f"{TEMPLATE_HEADER}\n")).status_code == 400


def test_import_unknown_portfolio_404(client):
    csv_text = f"{TEMPLATE_HEADER}\nAAPL,1,,false,auto,\n"
    assert client.post("/api/portfolio/holdings/import?portfolio_id=999",
                       files=_upload(csv_text)).status_code == 404


def test_import_unsafe_ticker_never_warmed(client, monkeypatch):
    """A shape-unsafe ticker must not reach the quote warm (yfinance)."""
    warmed = {}
    monkeypatch.setattr(portfolio_router, "get_all_quotes",
                        lambda ts: warmed.setdefault("tickers", ts))
    # Long/garbage ticker fails ticker_shape_is_safe; GOOD is fine.
    csv_text = f"{TEMPLATE_HEADER}\nGOOD,1,,false,auto,\nWAYTOOLONGTICKER,1,,false,auto,\n"
    client.post("/api/portfolio/holdings/import", files=_upload(csv_text))
    assert warmed.get("tickers") == ["GOOD"]  # unsafe symbol filtered out pre-warm


# ── Import: Claude path (key configured, mocked) ─────────────────────────────

def test_import_claude_path(db, client, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    mock = MagicMock()
    mock.messages.create.side_effect = [
        _mock_response('{"mapping":{"ticker":"symbol","shares":"qty","avg_cost":null,'
                       '"is_watchlist":null,"hold_class":null,"notes":null}}'),
        _mock_response("Two names mapped and safely aboard."),
    ]
    monkeypatch.setattr(ai_service, "client", mock)

    body = client.post("/api/portfolio/holdings/import",
                       files=_upload("Symbol,Qty\nAAPL,10\nNVDA,5\n", filename="broker.csv")).json()
    assert body["mode"] == "claude"
    assert body["added"] == 2
    assert body["column_mapping"]["ticker"] == "symbol"
    assert body["summary"] == "Two names mapped and safely aboard."


def test_import_clean_file_with_key_stays_local(client, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    mock = MagicMock()
    mock.messages.create.side_effect = AssertionError("Claude must not be called on a clean file")
    monkeypatch.setattr(ai_service, "client", mock)

    csv_text = f"{TEMPLATE_HEADER}\nAAPL,1,,false,auto,\n"
    body = client.post("/api/portfolio/holdings/import", files=_upload(csv_text)).json()
    assert body["mode"] == "local"
    assert mock.messages.create.called is False


def test_import_remap_failure_falls_back(client, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    mock = MagicMock()
    mock.messages.create.side_effect = RuntimeError("boom")
    monkeypatch.setattr(ai_service, "client", mock)

    res = client.post("/api/portfolio/holdings/import",
                      files=_upload("Symbol,Qty\nAAPL,10\n", filename="broker.csv"))
    assert res.status_code == 400
    assert res.json()["detail"]["mode"] == "claude_fallback"


def test_import_force_local_skips_claude(client, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    mock = MagicMock()
    mock.messages.create.side_effect = AssertionError("force_local must skip Claude")
    monkeypatch.setattr(ai_service, "client", mock)

    res = client.post("/api/portfolio/holdings/import?force_local=true",
                      files=_upload("Symbol,Qty\nAAPL,10\n", filename="broker.csv"))
    assert res.status_code == 400
    assert res.json()["detail"]["mode"] == "local"
    assert mock.messages.create.called is False
