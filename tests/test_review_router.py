"""HTTP contract and portfolio scoping for the Review Orbit."""
# pylint: disable=redefined-outer-name
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, Holding, Portfolio
from app.routers import review as review_router
from app.services import backup_service, portfolio_planning, portfolio_review


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)  # pylint: disable=invalid-name
    db = Session()
    db.add(Portfolio(id=1, name="Test"))
    db.add(Holding(
        id=1, portfolio_id=1, ticker="AAPL", shares=0, avg_cost=0,
        is_active=True, is_watchlist=True,
    ))
    db.commit()

    monkeypatch.setattr(
        portfolio_review,
        "build_review_inbox",
        lambda _db, portfolio_id: {
            "portfolio_id": portfolio_id, "count": 0, "items": [],
        },
    )
    app = FastAPI()
    app.include_router(review_router.router)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    db.close()


def test_inbox_is_portfolio_scoped(client):
    assert client.get("/api/review/inbox").json()["portfolio_id"] == 1
    assert client.get("/api/review/inbox?portfolio_id=999").status_code == 404


def test_thesis_review_is_local_and_scoped(client):
    response = client.put(
        "/api/review/thesis/1",
        json={"notes": "Watch services growth", "review_interval_days": 90},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "current"
    assert response.json()["review_interval_days"] == 90
    assert client.put(
        "/api/review/thesis/1?portfolio_id=999",
        json={"notes": "No", "review_interval_days": None},
    ).status_code == 404


def test_report_period_and_compare_selection_are_validated(client, monkeypatch):
    assert client.get("/api/review/report?period=year").status_code == 422
    monkeypatch.setattr(
        portfolio_review,
        "compare_watchlist",
        lambda _db, portfolio_id, tickers: {
            "portfolio_id": portfolio_id, "tickers": tickers,
        },
    )
    response = client.get("/api/review/compare?tickers=AAPL,MSFT")
    assert response.status_code == 200
    assert response.json()["tickers"] == ["AAPL", "MSFT"]


def test_plan_overview_and_rehearsal_routes_are_scoped(client, monkeypatch):
    monkeypatch.setattr(
        portfolio_planning,
        "build_target_plan",
        lambda _db, portfolio_id: {"portfolio_id": portfolio_id, "items": []},
    )
    monkeypatch.setattr(
        portfolio_planning,
        "rehearse_buy",
        lambda _db, portfolio_id, holding_id, cash: {
            "portfolio_id": portfolio_id,
            "holding_id": holding_id,
            "cash_usd": float(cash),
        },
    )
    monkeypatch.setattr(
        portfolio_planning,
        "build_all_books_overview",
        lambda _db: {"known_value_usd": 0, "items": []},
    )

    assert client.get("/api/review/plan").json()["portfolio_id"] == 1
    assert client.get("/api/review/plan?portfolio_id=999").status_code == 404
    response = client.post(
        "/api/review/plan/rehearsal",
        json={"holding_id": 1, "cash_usd": "25.00"},
    )
    assert response.status_code == 200
    assert response.json()["cash_usd"] == 25
    assert client.get("/api/review/overview").status_code == 200


def test_target_payload_requires_integer_basis_points(client):
    response = client.put(
        "/api/review/plan/targets",
        json={"items": [{"holding_id": 1, "target_weight_bps": 5000.5}]},
    )
    assert response.status_code == 422


def test_realized_export_has_fixed_safe_download_name(client):
    recap = client.get("/api/review/records/realized.csv?year=2026")
    assert recap.status_code == 200
    assert recap.headers["content-disposition"] == (
        'attachment; filename="folioorb-average-cost-recap-2026-p1.csv"'
    )
    assert "not a tax form" in recap.text


def test_portable_export_has_fixed_safe_download_name(client):
    archive = client.get("/api/review/records/archive")
    assert archive.status_code == 200
    assert archive.headers["content-disposition"] == (
        'attachment; filename="folioorb-portable-export.zip"'
    )
    assert archive.headers["content-type"] == "application/zip"


def test_backup_policy_route_precedes_dynamic_download_route(client, monkeypatch):
    monkeypatch.setattr(
        backup_service,
        "backup_protection_status",
        lambda: {"automatic": {"auto_backup_enabled": False}},
    )
    monkeypatch.setattr(
        backup_service,
        "set_auto_backup_enabled",
        lambda enabled: {"auto_backup_enabled": enabled},
    )

    assert client.get("/api/review/backups/policy").status_code == 200
    response = client.put("/api/review/backups/policy", json={"enabled": True})
    assert response.status_code == 200
