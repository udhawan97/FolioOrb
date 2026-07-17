"""The insider-activity endpoint is a thin, lazy wrapper over the service.

Like move-explanation it is per-ticker and user-initiated, so it may spend the
EDGAR round trips the batch paths avoid. The endpoint itself holds no logic
worth duplicating — these tests pin the contract: it passes the ticker through,
returns the service payload, and never raises for a ticker with no insiders.
"""
# pylint: disable=protected-access
import asyncio

from app.routers import ai as ai_router


def test_endpoint_returns_the_service_payload(monkeypatch):
    captured = {}

    def _fake(ticker, **_kw):
        captured["ticker"] = ticker
        return {"ticker": ticker, "buys": 2, "sells": 1, "transactions": [],
                "data_quality": "live"}

    monkeypatch.setattr(ai_router, "get_insider_activity", _fake)
    result = asyncio.run(ai_router.get_insider_activity_endpoint("aapl"))
    assert captured["ticker"] == "AAPL"  # normalized before the service sees it
    assert result["buys"] == 2
    assert result["data_quality"] == "live"


def test_endpoint_is_calm_about_a_ticker_with_no_insiders(monkeypatch):
    monkeypatch.setattr(
        ai_router,
        "get_insider_activity",
        lambda t, **_kw: {"ticker": t, "buys": 0, "sells": 0,
                          "transactions": [], "data_quality": "live"},
    )
    result = asyncio.run(ai_router.get_insider_activity_endpoint("VOO"))
    assert result["transactions"] == []
    assert result["data_quality"] == "live"


def test_endpoint_rejects_a_malformed_ticker(monkeypatch):
    # Guard the EDGAR round trip behind the same ticker-shape check the rest of
    # the app uses, so junk never reaches the network layer.
    called = []
    monkeypatch.setattr(
        ai_router, "get_insider_activity", lambda t, **_kw: called.append(t) or {}
    )
    from fastapi import HTTPException  # local: only this test needs it

    try:
        asyncio.run(ai_router.get_insider_activity_endpoint("../etc/passwd"))
        raised = False
    except HTTPException as exc:
        raised = exc.status_code == 422
    assert raised
    assert not called
