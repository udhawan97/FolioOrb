"""Deterministic barriers prove CSV import never occupies the API event loop."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import get_db
from app.models import Base, DcaContribution, DcaPlan, Holding, Portfolio
from app.routers import portfolio as portfolio_router
from app.services import holdings_repository
from app.services.dca_ledger import DcaLedger


TEMPLATE_HEADER = "ticker,shares,avg_cost,is_watchlist,hold_class,notes"


def _client(tmp_path):
    database = tmp_path / "portfolio.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    with session_factory() as db:
        db.add(Portfolio(id=1, name="Test"))
        db.commit()

    def override_db():
        with session_factory() as db:
            app.state.request_db = db
            yield db

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    app.include_router(portfolio_router.router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), session_factory, engine


def _upload(ticker: str):
    csv_text = f"{TEMPLATE_HEADER}\n{ticker},1,,false,auto,\n"
    return {"file": ("holdings.csv", csv_text, "text/csv")}


def _assert_health_finishes_while_external_work_is_held(client, entered, release, request):
    health_finished = threading.Event()

    def check_health():
        response = client.get("/health")
        health_finished.set()
        return response

    with ThreadPoolExecutor(max_workers=2) as pool:
        import_future = pool.submit(request)
        assert entered.wait(3), "the controlled external segment was not reached"
        health_future = pool.submit(check_health)
        completed_before_release = health_finished.wait(1)
        release.set()
        import_response = import_future.result(timeout=10)
        health_response = health_future.result(timeout=10)

    assert completed_before_release, "health queued behind held synchronous import work"
    assert health_response.status_code == 200
    return import_response


@pytest.mark.parametrize("run_number", range(10))
def test_quote_warm_barrier_keeps_health_live(tmp_path, monkeypatch, run_number):
    client, _sessions, engine = _client(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def held_quote_warm(tickers):
        entered.set()
        assert release.wait(10)
        return [{"ticker": ticker, "current_price": 100.0} for ticker in tickers]

    monkeypatch.setattr(portfolio_router, "get_all_quotes", held_quote_warm)
    monkeypatch.setattr(
        portfolio_router,
        "validate_ticker_symbol",
        lambda ticker, **_kwargs: {
            "valid": True,
            "ticker": ticker,
            "suggestions": [],
        },
    )

    with client:
        response = _assert_health_finishes_while_external_work_is_held(
            client,
            entered,
            release,
            lambda: client.post(
                "/api/portfolio/holdings/import", files=_upload(f"TST{run_number}")
            ),
        )
    engine.dispose()

    assert response.status_code == 200
    assert response.json()["added"] == 1


def test_failed_quote_search_barrier_keeps_health_live(tmp_path, monkeypatch):
    client, _sessions, engine = _client(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(portfolio_router, "get_all_quotes", lambda _tickers: [])

    def held_failed_validation(ticker, **_kwargs):
        entered.set()
        assert release.wait(10)
        return {
            "valid": False,
            "ticker": ticker,
            "message": f"Couldn't find ticker {ticker}",
            "suggestions": [{"ticker": "GOOD"}],
        }

    monkeypatch.setattr(portfolio_router, "validate_ticker_symbol", held_failed_validation)

    with client:
        response = _assert_health_finishes_while_external_work_is_held(
            client,
            entered,
            release,
            lambda: client.post(
                "/api/portfolio/holdings/import", files=_upload("MISSING")
            ),
        )
    engine.dispose()

    assert response.status_code == 200
    assert response.json()["errors"] == 1


def test_database_mutation_never_runs_in_external_worker(tmp_path, monkeypatch):
    client, _sessions, engine = _client(tmp_path)
    provider_thread = {}
    sql_threads: set[int] = set()

    @event.listens_for(engine, "before_cursor_execute")
    def record_sql_thread(*_args):
        sql_threads.add(threading.get_ident())

    def quote_warm(tickers):
        provider_thread["id"] = threading.get_ident()
        return [{"ticker": ticker, "current_price": 100.0} for ticker in tickers]

    monkeypatch.setattr(portfolio_router, "get_all_quotes", quote_warm)
    monkeypatch.setattr(portfolio_router, "validate_ticker_symbol", _valid_ticker)

    with client:
        response = client.post(
            "/api/portfolio/holdings/import", files=_upload("THREAD")
        )
    engine.dispose()

    assert response.status_code == 200
    assert provider_thread["id"] not in sql_threads


def test_claude_remap_barrier_keeps_health_live(tmp_path, monkeypatch):
    client, _sessions, engine = _client(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")

    def held_remap(_header, _rows):
        entered.set()
        assert release.wait(10)
        return {
            "ticker": "symbol",
            "shares": "qty",
            "avg_cost": None,
            "is_watchlist": None,
            "hold_class": None,
            "notes": None,
        }

    monkeypatch.setattr(
        portfolio_router.holdings_csv, "remap_columns_with_claude", held_remap
    )
    monkeypatch.setattr(
        portfolio_router.holdings_csv, "narrate_import_summary", lambda _report: "Done"
    )
    monkeypatch.setattr(portfolio_router, "get_all_quotes", lambda _tickers: [])
    monkeypatch.setattr(
        portfolio_router,
        "validate_ticker_symbol",
        lambda ticker, **_kwargs: {
            "valid": True,
            "ticker": ticker,
            "suggestions": [],
        },
    )
    upload = {"file": ("broker.csv", "Symbol,Qty\nAAPL,1\n", "text/csv")}

    with client:
        response = _assert_health_finishes_while_external_work_is_held(
            client,
            entered,
            release,
            lambda: client.post("/api/portfolio/holdings/import", files=upload),
        )
    engine.dispose()

    assert response.status_code == 200
    assert response.json()["mode"] == "claude"


def test_claude_narration_barrier_keeps_health_live(tmp_path, monkeypatch):
    client, _sessions, engine = _client(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(
        portfolio_router.holdings_csv,
        "remap_columns_with_claude",
        lambda _header, _rows: {
            "ticker": "symbol",
            "shares": "qty",
            "avg_cost": None,
            "is_watchlist": None,
            "hold_class": None,
            "notes": None,
        },
    )

    def held_narration(_report):
        entered.set()
        assert release.wait(10)
        return "Done"

    monkeypatch.setattr(
        portfolio_router.holdings_csv, "narrate_import_summary", held_narration
    )
    monkeypatch.setattr(portfolio_router, "get_all_quotes", lambda _tickers: [])
    monkeypatch.setattr(portfolio_router, "validate_ticker_symbol", _valid_ticker)
    upload = {"file": ("broker.csv", "Symbol,Qty\nNARRATE,1\n", "text/csv")}

    with client:
        response = _assert_health_finishes_while_external_work_is_held(
            client,
            entered,
            release,
            lambda: client.post("/api/portfolio/holdings/import", files=upload),
        )
    engine.dispose()

    assert response.status_code == 200
    assert response.json()["summary"] == "Done"


def test_all_skipped_claude_import_ends_transaction_before_narration(
    tmp_path, monkeypatch
):
    client, sessions, engine = _client(tmp_path)
    with sessions() as db:
        db.add(Holding(portfolio_id=1, ticker="EXIST", shares=1))
        db.commit()
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(
        portfolio_router.holdings_csv,
        "remap_columns_with_claude",
        lambda _header, _rows: {
            "ticker": "symbol",
            "shares": "qty",
            "avg_cost": None,
            "is_watchlist": None,
            "hold_class": None,
            "notes": None,
        },
    )
    transaction_state = {}

    def inspect_narration_boundary(_report):
        transaction_state["open"] = client.app.state.request_db.in_transaction()
        return "Done"

    monkeypatch.setattr(
        portfolio_router.holdings_csv,
        "narrate_import_summary",
        inspect_narration_boundary,
    )
    upload = {"file": ("broker.csv", "Symbol,Qty\nEXIST,1\n", "text/csv")}

    with client:
        response = client.post("/api/portfolio/holdings/import", files=upload)
    engine.dispose()

    assert response.status_code == 200
    assert response.json()["added"] == 0
    assert response.json()["skipped"] == 1
    assert transaction_state == {"open": False}


def _valid_ticker(ticker, **_kwargs):
    return {"valid": True, "ticker": ticker, "suggestions": []}


def test_existing_holding_skips_all_provider_work(tmp_path, monkeypatch):
    client, sessions, engine = _client(tmp_path)
    with sessions() as db:
        db.add(Holding(portfolio_id=1, ticker="EXIST", shares=1))
        db.commit()

    def unexpected_provider(*_args, **_kwargs):
        pytest.fail("an existing holding must not invoke a provider")

    monkeypatch.setattr(portfolio_router, "get_all_quotes", unexpected_provider)
    monkeypatch.setattr(
        portfolio_router, "validate_ticker_symbol", unexpected_provider
    )

    with client:
        response = client.post(
            "/api/portfolio/holdings/import", files=_upload(" exist ")
        )
    engine.dispose()

    assert response.status_code == 200
    assert response.json()["added"] == 0
    assert response.json()["skipped"] == 1
    assert response.json()["rows"][0]["reason"] == "already in portfolio"


def test_unknown_portfolio_rejects_before_provider_work(tmp_path, monkeypatch):
    client, _sessions, engine = _client(tmp_path)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")

    def unexpected_provider(*_args, **_kwargs):
        pytest.fail("an unknown portfolio must not invoke a provider")

    monkeypatch.setattr(portfolio_router, "get_all_quotes", unexpected_provider)
    monkeypatch.setattr(
        portfolio_router, "validate_ticker_symbol", unexpected_provider
    )
    monkeypatch.setattr(
        portfolio_router.holdings_csv,
        "remap_columns_with_claude",
        unexpected_provider,
    )
    monkeypatch.setattr(
        portfolio_router.holdings_csv,
        "narrate_import_summary",
        unexpected_provider,
    )
    upload = {"file": ("broker.csv", "Symbol,Qty\nNEW,1\n", "text/csv")}

    with client:
        response = client.post(
            "/api/portfolio/holdings/import?portfolio_id=999",
            files=upload,
        )
    engine.dispose()

    assert response.status_code == 404


def test_concurrent_imports_commit_one_active_ticker(tmp_path, monkeypatch):
    client, sessions, engine = _client(tmp_path)
    validation_barrier = threading.Barrier(2)
    monkeypatch.setattr(portfolio_router, "get_all_quotes", lambda _tickers: [])

    def validate(ticker, **_kwargs):
        validation_barrier.wait(timeout=10)
        return _valid_ticker(ticker)

    monkeypatch.setattr(portfolio_router, "validate_ticker_symbol", validate)

    with client, ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                client.post,
                "/api/portfolio/holdings/import",
                files=_upload("RACE"),
            )
            for _ in range(2)
        ]
        responses = [future.result(timeout=15) for future in futures]

    with sessions() as db:
        active = (
            db.query(Holding)
            .filter(Holding.portfolio_id == 1, Holding.ticker == "RACE")
            .all()
        )
    engine.dispose()

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["added"] for response in responses) == [0, 1]
    assert sorted(response.json()["skipped"] for response in responses) == [0, 1]
    assert len(active) == 1


def test_import_racing_manual_add_commits_one_active_ticker(tmp_path, monkeypatch):
    client, sessions, engine = _client(tmp_path)
    validation_barrier = threading.Barrier(2)
    monkeypatch.setattr(portfolio_router, "get_all_quotes", lambda _tickers: [])

    def validate(ticker, **_kwargs):
        validation_barrier.wait(timeout=10)
        return _valid_ticker(ticker)

    monkeypatch.setattr(portfolio_router, "validate_ticker_symbol", validate)

    with client, ThreadPoolExecutor(max_workers=2) as pool:
        import_future = pool.submit(
            client.post,
            "/api/portfolio/holdings/import",
            files=_upload("RACE"),
        )
        add_future = pool.submit(
            client.post,
            "/api/portfolio/holdings",
            json={"ticker": "RACE", "shares": 1},
        )
        imported = import_future.result(timeout=15)
        added = add_future.result(timeout=15)

    with sessions() as db:
        active_count = (
            db.query(Holding)
            .filter(
                Holding.portfolio_id == 1,
                Holding.ticker == "RACE",
                Holding.is_active.is_(True),
            )
            .count()
        )
    engine.dispose()

    assert imported.status_code == 200
    assert added.status_code in (200, 400)
    assert imported.json()["added"] + (1 if added.status_code == 200 else 0) == 1
    assert active_count == 1


def test_import_racing_dca_apply_uses_one_active_holding(tmp_path, monkeypatch):
    client, sessions, engine = _client(tmp_path)
    with sessions() as db:
        plan = DcaPlan(
            portfolio_id=1,
            ticker="RACE",
            amount=50,
            frequency="weekly",
            start_date="2026-08-21",
            quote_currency="USD",
            quote_currency_source="ticker_validation",
        )
        db.add(plan)
        db.flush()
        contribution = DcaContribution(
            plan_id=plan.id,
            scheduled_date="2026-08-21",
            exec_date="2026-08-21",
            price=100,
            shares=0.5,
            amount=50,
            price_currency="USD",
            price_currency_source="validated_plan",
        )
        db.add(contribution)
        db.commit()
        contribution_id = contribution.id

    monkeypatch.setattr(portfolio_router, "get_all_quotes", lambda _tickers: [])
    monkeypatch.setattr(portfolio_router, "validate_ticker_symbol", _valid_ticker)
    creation_barrier = threading.Barrier(2)
    original_add_active = holdings_repository.add_active

    def synchronized_add_active(db, holding):
        creation_barrier.wait(timeout=10)
        return original_add_active(db, holding)

    monkeypatch.setattr(holdings_repository, "add_active", synchronized_add_active)

    def apply_dca():
        with sessions() as db:
            return DcaLedger(db).apply_contribution(contribution_id)

    with client, ThreadPoolExecutor(max_workers=2) as pool:
        import_future = pool.submit(
            client.post,
            "/api/portfolio/holdings/import",
            files=_upload("RACE"),
        )
        dca_future = pool.submit(apply_dca)
        imported = import_future.result(timeout=15)
        dca_result = dca_future.result(timeout=15)

    with sessions() as db:
        active = (
            db.query(Holding)
            .filter(
                Holding.portfolio_id == 1,
                Holding.ticker == "RACE",
                Holding.is_active.is_(True),
            )
            .all()
        )
    engine.dispose()

    assert imported.status_code == 200
    assert dca_result["contribution"]["status"] == "applied"
    assert len(active) == 1
