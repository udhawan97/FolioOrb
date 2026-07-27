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
from app.services import portfolio_review


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
