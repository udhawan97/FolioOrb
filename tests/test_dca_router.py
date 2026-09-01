"""HTTP-level tests for the DCA plan endpoints.

Mounts only the DCA router on a bare FastAPI app with an in-memory SQLite DB
(pattern from tests/test_holdings_csv_router.py). Ticker validation and the
historical price fetch are monkeypatched in the router namespace — no network.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, DcaContribution, DcaPlan, Holding, Portfolio
from app.routers import dca as dca_router


# Freeze "today" to a known Friday so scheduled buys always land on trading
# days regardless of the real calendar (a buy scheduled on a real-world
# Saturday would snap to a future Monday and correctly not book yet).
FIXED_TODAY = date(2026, 6, 12)


class _FixedDate(date):
    @classmethod
    def today(cls):
        return cls(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day)


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)  # pylint: disable=invalid-name
    db = Session()
    db.add(Portfolio(id=1, name="Test"))
    db.commit()
    return db


@pytest.fixture
def db():
    return _make_db()


def _fake_closes(ticker, start, end):
    """Deterministic weekday 'closes': every weekday in [start, end] at $100."""
    out = {}
    d = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while d <= stop:
        if d.weekday() < 5:
            out[d.isoformat()] = 100.0
        d += timedelta(days=1)
    return out


@pytest.fixture
def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(dca_router.router)
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(
        dca_router,
        "validate_ticker_symbol",
        lambda t, **k: {
            "valid": True,
            "ticker": t,
            "quote": {"currency": "USD", "source_currency": "USD"},
            "suggestions": [],
        },
    )
    monkeypatch.setattr(dca_router, "get_daily_closes", _fake_closes)
    monkeypatch.setattr(dca_router, "date", _FixedDate)
    return TestClient(app)


def _days_ago(n):
    return (FIXED_TODAY - timedelta(days=n)).isoformat()


def _create_weekly_plan(client, days_back=21, amount=50.0):
    return client.post(
        "/api/dca/plans?portfolio_id=1",
        json={
            "ticker": "VOO",
            "amount": amount,
            "frequency": "weekly",
            "start_date": _days_ago(days_back),
        },
    )


def _seed_portfolio_dca(db, status, portfolio_id=2):
    """Return IDs and persisted state owned entirely by one portfolio."""
    if db.get(Portfolio, portfolio_id) is None:
        db.add(Portfolio(id=portfolio_id, name=f"Portfolio {portfolio_id}"))
    holding = Holding(
        portfolio_id=portfolio_id,
        ticker="OWNED",
        shares=10.5 if status == "applied" else 10.0,
        avg_cost=(2050.0 / 10.5) if status == "applied" else 200.0,
        is_active=True,
        is_watchlist=False,
        hold_class="auto",
    )
    db.add(holding)
    plan = DcaPlan(
        portfolio_id=portfolio_id,
        ticker="OWNED",
        amount=50.0,
        frequency="weekly",
        start_date=FIXED_TODAY.isoformat(),
        quote_currency="USD",
        quote_currency_source="ticker_validation",
        is_active=True,
    )
    db.add(plan)
    db.flush()
    contribution = DcaContribution(
        plan_id=plan.id,
        scheduled_date=FIXED_TODAY.isoformat(),
        exec_date=FIXED_TODAY.isoformat(),
        price=100.0,
        shares=0.5,
        amount=50.0,
        price_currency="USD",
        price_currency_source="validated_plan",
        status=status,
        applied_holding_id=holding.id if status == "applied" else None,
    )
    db.add(contribution)
    db.commit()
    return plan.id, contribution.id, holding.id


@pytest.mark.parametrize(
    "case",
    [
        ("PATCH", "/api/dca/plans/{plan_id}", "pending",
         {"amount": 75, "is_active": False}, "DCA plan not found"),
        ("DELETE", "/api/dca/plans/{plan_id}", "pending", None,
         "DCA plan not found"),
        ("POST", "/api/dca/contributions/{contribution_id}/apply", "pending",
         None, "Contribution not found"),
        ("POST", "/api/dca/contributions/{contribution_id}/skip", "pending",
         None, "Contribution not found"),
        ("POST", "/api/dca/contributions/{contribution_id}/restore", "dismissed",
         None, "Contribution not found"),
        ("POST", "/api/dca/contributions/{contribution_id}/undo", "applied",
         None, "Contribution not found"),
        ("POST", "/api/dca/plans/{plan_id}/apply-pending", "pending",
         None, "DCA plan not found"),
        ("POST", "/api/dca/plans/{plan_id}/skip-pending", "pending",
         None, "DCA plan not found"),
        ("POST", "/api/dca/plans/{plan_id}/undo-applied", "applied",
         None, "DCA plan not found"),
    ],
    ids=[
        "update-plan", "delete-plan", "apply", "skip", "restore", "undo",
        "apply-all", "skip-all", "undo-all",
    ],
)
def test_id_mutations_cannot_cross_portfolios(client, db, case):
    method, path, status, payload, detail = case
    plan_id, contribution_id, holding_id = _seed_portfolio_dca(db, status)
    plan = db.get(DcaPlan, plan_id)
    contribution = db.get(DcaContribution, contribution_id)
    holding = db.get(Holding, holding_id)
    before = {
        "plan": (plan.amount, plan.is_active, plan.catchup_floor),
        "contribution": (contribution.status, contribution.applied_holding_id),
        "holding": (holding.shares, holding.avg_cost, holding.is_active),
    }
    target = path.format(plan_id=plan_id, contribution_id=contribution_id)

    response = client.request(
        method,
        f"{target}?portfolio_id=1",
        json=payload,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": detail}
    db.expire_all()
    plan = db.get(DcaPlan, plan_id)
    contribution = db.get(DcaContribution, contribution_id)
    holding = db.get(Holding, holding_id)
    assert plan is not None
    assert contribution is not None
    assert holding is not None
    assert (plan.amount, plan.is_active, plan.catchup_floor) == before["plan"]
    assert (contribution.status, contribution.applied_holding_id) == before["contribution"]
    assert (holding.shares, holding.avg_cost, holding.is_active) == before["holding"]


@pytest.mark.parametrize(
    "query, expected_status",
    [("", 422), ("?portfolio_id=999", 404)],
    ids=["missing-portfolio", "unknown-portfolio"],
)
@pytest.mark.parametrize(
    "case",
    [
        ("PATCH", "/api/dca/plans/{plan_id}", "pending",
         {"amount": 75, "is_active": False}),
        ("DELETE", "/api/dca/plans/{plan_id}", "pending", None),
        ("POST", "/api/dca/contributions/{contribution_id}/apply", "pending", None),
        ("POST", "/api/dca/contributions/{contribution_id}/skip", "pending", None),
        ("POST", "/api/dca/contributions/{contribution_id}/restore", "dismissed", None),
        ("POST", "/api/dca/contributions/{contribution_id}/undo", "applied", None),
        ("POST", "/api/dca/plans/{plan_id}/apply-pending", "pending", None),
        ("POST", "/api/dca/plans/{plan_id}/skip-pending", "pending", None),
        ("POST", "/api/dca/plans/{plan_id}/undo-applied", "applied", None),
    ],
    ids=[
        "update-plan", "delete-plan", "apply", "skip", "restore", "undo",
        "apply-all", "skip-all", "undo-all",
    ],
)
def test_id_mutations_require_a_known_portfolio(client, db, case, query, expected_status):
    method, path, status, payload = case
    plan_id, contribution_id, holding_id = _seed_portfolio_dca(
        db, status, portfolio_id=1
    )
    plan = db.get(DcaPlan, plan_id)
    contribution = db.get(DcaContribution, contribution_id)
    holding = db.get(Holding, holding_id)
    before = {
        "plan": (plan.amount, plan.is_active, plan.catchup_floor),
        "contribution": (contribution.status, contribution.applied_holding_id),
        "holding": (holding.shares, holding.avg_cost, holding.is_active),
    }
    target = path.format(plan_id=plan_id, contribution_id=contribution_id)

    response = client.request(method, f"{target}{query}", json=payload)

    assert response.status_code == expected_status
    db.expire_all()
    plan = db.get(DcaPlan, plan_id)
    contribution = db.get(DcaContribution, contribution_id)
    holding = db.get(Holding, holding_id)
    assert plan is not None
    assert contribution is not None
    assert holding is not None
    assert (plan.amount, plan.is_active, plan.catchup_floor) == before["plan"]
    assert (contribution.status, contribution.applied_holding_id) == before["contribution"]
    assert (holding.shares, holding.avg_cost, holding.is_active) == before["holding"]


@pytest.mark.parametrize(
    "path, payload",
    [
        (
            "/api/dca/plans",
            {
                "ticker": "VOO",
                "amount": 50,
                "frequency": "weekly",
                "start_date": FIXED_TODAY.isoformat(),
            },
        ),
        ("/api/dca/run", None),
    ],
    ids=["create-plan", "run-catchup"],
)
@pytest.mark.parametrize(
    "query, expected_status",
    [("", 422), ("?portfolio_id=999", 404)],
    ids=["missing-portfolio", "unknown-portfolio"],
)
def test_other_dca_writes_require_a_known_portfolio(
    client, db, path, payload, query, expected_status
):
    response = client.post(f"{path}{query}", json=payload)

    assert response.status_code == expected_status
    assert db.query(DcaPlan).count() == 0
    assert db.query(DcaContribution).count() == 0


# ── Plan creation + backfill ─────────────────────────────────────────────────

def test_create_plan_backfills_pending_buys(client):
    res = _create_weekly_plan(client, days_back=21)
    assert res.status_code == 200
    body = res.json()
    # 21 days back, weekly → 4 intended buys (day 0, 7, 14, 21).
    assert body["buys_added"] == 4
    assert body["plan"]["pending_count"] == 4
    assert body["plan"]["applied_count"] == 0
    assert body["plan"]["is_active"] is True


def test_create_plan_rejects_invalid_ticker(client, monkeypatch):
    monkeypatch.setattr(
        dca_router,
        "validate_ticker_symbol",
        lambda t, **k: {"valid": False, "message": "nope", "suggestions": []},
    )
    res = _create_weekly_plan(client)
    assert res.status_code == 400


def test_create_plan_rejects_exact_duplicate(client):
    assert _create_weekly_plan(client, amount=50.0).status_code == 200
    # Same ticker + cadence + amount → rejected as a double-book.
    dup = _create_weekly_plan(client, amount=50.0)
    assert dup.status_code == 400
    assert "already have" in dup.json()["detail"].lower()
    # A different amount is a distinct plan and is allowed.
    assert _create_weekly_plan(client, amount=75.0).status_code == 200


def test_create_plan_rejects_future_start(client):
    res = client.post(
        "/api/dca/plans?portfolio_id=1",
        json={
            "ticker": "VOO",
            "amount": 50,
            "frequency": "weekly",
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
        },
    )
    assert res.status_code == 422


def test_create_plan_rejects_bad_frequency(client):
    res = client.post(
        "/api/dca/plans?portfolio_id=1",
        json={
            "ticker": "VOO",
            "amount": 50,
            "frequency": "hourly",
            "start_date": _days_ago(7),
        },
    )
    assert res.status_code == 422


# ── Catch-up idempotency ─────────────────────────────────────────────────────

def test_run_catchup_is_idempotent(client):
    _create_weekly_plan(client, days_back=21)
    res = client.post("/api/dca/run?portfolio_id=1")
    assert res.status_code == 200
    body = res.json()
    assert body["buys_added"] == 0  # backfill already booked everything
    assert body["plans"][0]["price_data"] is True


def test_run_catchup_reports_missing_price_data(client, db, monkeypatch):
    # Stub before creating, so the plan is left with genuinely unbooked dates.
    # Catch-up only reaches the price fetch when a buy is actually due; a plan
    # that is already caught up needs no prices and must not claim they were
    # missing.
    monkeypatch.setattr(dca_router, "get_daily_closes", lambda *a: {})
    _create_weekly_plan(client)
    res = client.post("/api/dca/run?portfolio_id=1")
    assert res.json()["plans"][0]["price_data"] is False


def test_a_caught_up_plan_reports_priced_without_fetching(client, monkeypatch):
    """Nothing due is not a pricing failure, so it must not be reported as one."""
    _create_weekly_plan(client, days_back=21)

    def _explode(*_args):
        raise AssertionError("a caught-up plan must not fetch prices")

    monkeypatch.setattr(dca_router, "get_daily_closes", _explode)
    body = client.post("/api/dca/run?portfolio_id=1").json()
    assert body["buys_added"] == 0
    assert body["plans"][0]["price_data"] is True


def test_paused_plan_is_skipped_by_catchup(client, db):
    plan_id = _create_weekly_plan(client).json()["plan"]["id"]
    client.patch(f"/api/dca/plans/{plan_id}?portfolio_id=1", json={"is_active": False})
    res = client.post("/api/dca/run?portfolio_id=1")
    assert res.json()["plans_checked"] == 0


def test_catchup_reports_legacy_plan_but_books_trusted_plan(client, db):
    db.add_all([
        DcaPlan(
            portfolio_id=1, ticker="LEGACY", amount=50, frequency="weekly",
            start_date=FIXED_TODAY.isoformat(), quote_currency=None,
            quote_currency_source="legacy_unknown", is_active=True,
        ),
        DcaPlan(
            portfolio_id=1, ticker="VOO", amount=50, frequency="weekly",
            start_date=FIXED_TODAY.isoformat(), quote_currency="USD",
            quote_currency_source="ticker_validation", is_active=True,
        ),
    ])
    db.commit()

    response = client.post("/api/dca/run?portfolio_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["buys_added"] == 1
    assert payload["plans_blocked"] == 1
    by_ticker = {row["ticker"]: row for row in payload["plans"]}
    assert by_ticker["LEGACY"]["status"] == "needs_currency"
    assert by_ticker["LEGACY"]["price_data"] is None
    assert by_ticker["VOO"]["status"] == "ready"
    assert [row.plan.ticker for row in db.query(DcaContribution).all()] == ["VOO"]

    plans = {row["ticker"]: row for row in client.get("/api/dca/plans").json()["plans"]}
    assert plans["LEGACY"]["currency_status"] == "needs_currency"
    assert plans["LEGACY"]["next_date"] is None


# ── Apply / skip / undo / restore ────────────────────────────────────────────

def _first_pending_id(client):
    rows = client.get("/api/dca/contributions?status=pending").json()["contributions"]
    return rows[0]["id"]


def test_apply_creates_holding_and_updates_average(client, db):
    _create_weekly_plan(client, days_back=7, amount=50.0)  # 2 buys @ $100
    cid = _first_pending_id(client)
    res = client.post(f"/api/dca/contributions/{cid}/apply?portfolio_id=1")
    assert res.status_code == 200
    holding = res.json()["holding"]
    assert holding["shares"] == pytest.approx(0.5)
    assert holding["avg_cost"] == pytest.approx(100.0)
    # Applying the same buy twice is rejected.
    assert client.post(
        f"/api/dca/contributions/{cid}/apply?portfolio_id=1"
    ).status_code == 400


def test_apply_adds_to_existing_holding(client, db):
    db.add(Holding(portfolio_id=1, ticker="VOO", shares=10, avg_cost=200,
                   is_active=True, is_watchlist=False, hold_class="auto"))
    db.commit()
    _create_weekly_plan(client, days_back=0, amount=50.0)  # 1 buy: 0.5 sh @ $100
    cid = _first_pending_id(client)
    holding = client.post(
        f"/api/dca/contributions/{cid}/apply?portfolio_id=1"
    ).json()["holding"]
    assert holding["shares"] == pytest.approx(10.5)
    # New basis: 10*200 + 50 = 2050 → avg 2050 / 10.5
    assert holding["avg_cost"] == pytest.approx(2050.0 / 10.5)


def test_undo_restores_holding_exactly(client, db):
    db.add(Holding(portfolio_id=1, ticker="VOO", shares=10, avg_cost=200,
                   is_active=True, is_watchlist=False, hold_class="auto"))
    db.commit()
    _create_weekly_plan(client, days_back=0)
    cid = _first_pending_id(client)
    client.post(f"/api/dca/contributions/{cid}/apply?portfolio_id=1")
    res = client.post(f"/api/dca/contributions/{cid}/undo?portfolio_id=1")
    assert res.status_code == 200
    assert res.json()["contribution"]["status"] == "pending"
    holding = db.query(Holding).filter(Holding.ticker == "VOO").one()
    assert holding.shares == pytest.approx(10.0)
    assert holding.avg_cost == pytest.approx(200.0)


def test_undo_requires_applied_status(client):
    _create_weekly_plan(client, days_back=0)
    cid = _first_pending_id(client)
    assert client.post(
        f"/api/dca/contributions/{cid}/undo?portfolio_id=1"
    ).status_code == 400


def test_undo_to_zero_deactivates_dca_created_holding(client, db):
    # No pre-existing holding: apply creates one, undo empties it → soft-deleted,
    # so it never lingers as a $0 active position.
    _create_weekly_plan(client, days_back=0, amount=50.0)
    cid = _first_pending_id(client)
    client.post(f"/api/dca/contributions/{cid}/apply?portfolio_id=1")
    holding = db.query(Holding).filter(Holding.ticker == "VOO").one()
    assert holding.is_active is True and holding.shares > 0
    client.post(f"/api/dca/contributions/{cid}/undo?portfolio_id=1")
    db.refresh(holding)
    assert holding.shares == pytest.approx(0.0)
    assert holding.is_active is False


def test_skip_then_restore_roundtrip(client):
    _create_weekly_plan(client, days_back=0)
    cid = _first_pending_id(client)
    assert client.post(
        f"/api/dca/contributions/{cid}/skip?portfolio_id=1"
    ).status_code == 200
    rows = client.get("/api/dca/contributions?status=dismissed").json()["contributions"]
    assert [r["id"] for r in rows] == [cid]
    assert client.post(
        f"/api/dca/contributions/{cid}/restore?portfolio_id=1"
    ).status_code == 200
    assert _first_pending_id(client) == cid


def test_skipped_buy_does_not_reappear_after_catchup(client):
    _create_weekly_plan(client, days_back=0)
    cid = _first_pending_id(client)
    client.post(f"/api/dca/contributions/{cid}/skip?portfolio_id=1")
    client.post("/api/dca/run?portfolio_id=1")
    rows = client.get("/api/dca/contributions?status=pending").json()["contributions"]
    assert rows == []  # unique (plan, scheduled_date) blocks re-booking


# ── Bulk operations ──────────────────────────────────────────────────────────

def test_apply_all_pending(client, db):
    plan_id = _create_weekly_plan(client, days_back=21, amount=50.0).json()["plan"]["id"]
    res = client.post(f"/api/dca/plans/{plan_id}/apply-pending?portfolio_id=1")
    assert res.json()["applied"] == 4
    holding = db.query(Holding).filter(Holding.ticker == "VOO").one()
    assert holding.shares == pytest.approx(2.0)      # 4 × $50 @ $100
    assert holding.avg_cost == pytest.approx(100.0)
    summary = client.get("/api/dca/plans").json()["plans"][0]
    assert summary["applied_count"] == 4
    assert summary["applied_amount"] == pytest.approx(200.0)


def test_skip_all_pending(client):
    plan_id = _create_weekly_plan(client, days_back=21).json()["plan"]["id"]
    res = client.post(f"/api/dca/plans/{plan_id}/skip-pending?portfolio_id=1")
    assert res.json()["skipped"] == 4
    assert client.get("/api/dca/contributions?status=pending").json()["contributions"] == []


def test_undo_all_applied_reverses_everything(client, db):
    plan_id = _create_weekly_plan(client, days_back=21, amount=50.0).json()["plan"]["id"]
    client.post(
        f"/api/dca/plans/{plan_id}/apply-pending?portfolio_id=1"
    )  # 4 buys → 2.0 sh
    res = client.post(f"/api/dca/plans/{plan_id}/undo-applied?portfolio_id=1")
    assert res.json()["undone"] == 4
    # Every buy back to pending, and the DCA-created holding is emptied + retired.
    assert len(client.get("/api/dca/contributions?status=pending").json()["contributions"]) == 4
    assert client.get("/api/dca/contributions?status=applied").json()["contributions"] == []
    holding = db.query(Holding).filter(Holding.ticker == "VOO").one()
    assert holding.shares == pytest.approx(0.0)
    assert holding.is_active is False


def test_undo_all_keeps_holding_with_manual_shares(client, db):
    # A pre-existing manual position must survive undo-all of the plan's buys.
    db.add(Holding(portfolio_id=1, ticker="VOO", shares=10, avg_cost=200,
                   is_active=True, is_watchlist=False, hold_class="auto"))
    db.commit()
    plan_id = _create_weekly_plan(client, days_back=21, amount=50.0).json()["plan"]["id"]
    client.post(f"/api/dca/plans/{plan_id}/apply-pending?portfolio_id=1")
    client.post(f"/api/dca/plans/{plan_id}/undo-applied?portfolio_id=1")
    holding = db.query(Holding).filter(Holding.ticker == "VOO").one()
    assert holding.shares == pytest.approx(10.0)
    assert holding.avg_cost == pytest.approx(200.0)
    assert holding.is_active is True


# ── Pause / resume catch-up floor ────────────────────────────────────────────

def test_catchup_respects_floor(client, db):
    # A plan whose floor sits after its start must only book from the floor
    # onward — the pre-floor (paused) intervals are never retroactively bought.
    db.add(DcaPlan(portfolio_id=1, ticker="VOO", amount=50.0, frequency="weekly",
                   start_date="2026-05-13", catchup_floor="2026-06-05", is_active=True,
                   quote_currency="USD", quote_currency_source="ticker_validation"))
    db.commit()
    assert client.post("/api/dca/run?portfolio_id=1").status_code == 200
    rows = client.get("/api/dca/contributions?status=pending").json()["contributions"]
    # Weekly from 05-13 → 05-13, 05-20, 05-27, 06-03, 06-10; only 06-10 ≥ floor.
    assert [r["scheduled_date"] for r in rows] == ["2026-06-10"]


def test_resume_advances_floor_and_skips_paused_period(client, db):
    plan_id = _create_weekly_plan(client, days_back=21).json()["plan"]["id"]
    client.patch(
        f"/api/dca/plans/{plan_id}?portfolio_id=1", json={"is_active": False}
    )  # pause
    client.patch(
        f"/api/dca/plans/{plan_id}?portfolio_id=1", json={"is_active": True}
    )  # resume
    plan = db.query(DcaPlan).filter(DcaPlan.id == plan_id).one()
    assert plan.catchup_floor == FIXED_TODAY.isoformat()
    # Resuming does not retroactively book anything (floor is today).
    assert client.post("/api/dca/run?portfolio_id=1").json()["buys_added"] == 0


# ── Plan update / delete ─────────────────────────────────────────────────────

def test_update_plan_amount_and_pause(client):
    plan_id = _create_weekly_plan(client).json()["plan"]["id"]
    res = client.patch(
        f"/api/dca/plans/{plan_id}?portfolio_id=1",
        json={"amount": 75, "is_active": False},
    )
    plan = res.json()["plan"]
    assert plan["amount"] == 75
    assert plan["is_active"] is False
    assert plan["next_date"] is None  # paused plans show no next buy


def test_delete_plan_cascades_contributions(client, db):
    plan_id = _create_weekly_plan(client).json()["plan"]["id"]
    assert client.delete(f"/api/dca/plans/{plan_id}?portfolio_id=1").status_code == 200
    assert db.query(DcaPlan).count() == 0
    assert db.query(DcaContribution).count() == 0


def test_delete_plan_surfaces_applied_buy_conflict(client, db):
    plan_id = _create_weekly_plan(client).json()["plan"]["id"]
    contribution = db.query(DcaContribution).filter(
        DcaContribution.plan_id == plan_id
    ).first()
    contribution.status = "applied"
    db.commit()

    response = client.delete(f"/api/dca/plans/{plan_id}?portfolio_id=1")

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Undo applied buys before deleting this plan so its holding changes "
            "remain traceable."
        )
    }
    assert db.query(DcaPlan).filter(DcaPlan.id == plan_id).count() == 1


def test_delete_missing_plan_404(client):
    assert client.delete("/api/dca/plans/999?portfolio_id=1").status_code == 404
