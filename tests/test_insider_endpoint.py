"""The insider-activity endpoint is a thin, lazy wrapper over the service.

Like move-explanation it is per-ticker and user-initiated, so it may spend the
EDGAR round trips the batch paths avoid. The endpoint itself holds no logic
worth duplicating — these tests pin the contract: it passes the ticker through,
returns the service payload, and never raises for a ticker with no insiders.

Exercised through the router rather than by calling the handler as a function.
The ticker-shape check is now the ``deps.safe_ticker`` dependency shared by every
``/{ticker}`` route (see tests/test_ticker_path_shape_guard.py), and a
dependency only runs when FastAPI resolves the request — calling the handler
directly would skip the very guard these tests exist to pin.
"""
# pylint: disable=protected-access
from app.routers import ai as ai_router


def test_endpoint_returns_the_service_payload(monkeypatch, api_client):
    captured = {}

    def _fake(ticker, **_kw):
        captured["ticker"] = ticker
        return {"ticker": ticker, "buys": 2, "sells": 1, "transactions": [],
                "data_quality": "live"}

    monkeypatch.setattr(ai_router, "get_insider_activity", _fake)
    response = api_client(ai_router.router).get("/api/ai/insider-activity/aapl")

    assert response.status_code == 200
    assert captured["ticker"] == "AAPL"  # normalized before the service sees it
    body = response.json()
    assert body["buys"] == 2
    assert body["data_quality"] == "live"


def test_endpoint_is_calm_about_a_ticker_with_no_insiders(monkeypatch, api_client):
    monkeypatch.setattr(
        ai_router,
        "get_insider_activity",
        lambda t, **_kw: {"ticker": t, "buys": 0, "sells": 0,
                          "transactions": [], "data_quality": "live"},
    )
    response = api_client(ai_router.router).get("/api/ai/insider-activity/VOO")

    assert response.status_code == 200
    body = response.json()
    assert body["transactions"] == []
    assert body["data_quality"] == "live"


def test_endpoint_rejects_a_malformed_ticker(monkeypatch, api_client):
    # Guard the EDGAR round trip behind the same ticker-shape check the rest of
    # the app uses, so junk never reaches the network layer.
    called = []
    monkeypatch.setattr(
        ai_router, "get_insider_activity", lambda t, **_kw: called.append(t) or {}
    )
    # A single path segment that survives routing but fails TICKER_PATTERN, so
    # the guard — not the router's 404 — is what rejects it.
    response = api_client(ai_router.router).get("/api/ai/insider-activity/AAPL;rm")

    assert response.status_code == 422
    assert not called


# --- fundamentals endpoint (same lazy, non-filer-safe contract) ---


def test_fundamentals_endpoint_returns_the_service_payload(monkeypatch, api_client):
    captured = {}

    def _fake(ticker, **_kw):
        captured["ticker"] = ticker
        return {"ticker": ticker, "periods": [{"year": 2025, "revenue": 1.0}],
                "data_quality": "live"}

    monkeypatch.setattr(ai_router, "get_fundamentals", _fake)
    response = api_client(ai_router.router).get("/api/ai/fundamentals/aapl")

    assert response.status_code == 200
    assert captured["ticker"] == "AAPL"
    assert response.json()["periods"][0]["year"] == 2025


def test_fundamentals_endpoint_rejects_a_malformed_ticker(monkeypatch, api_client):
    called = []
    monkeypatch.setattr(
        ai_router, "get_fundamentals", lambda t, **_kw: called.append(t) or {}
    )
    response = api_client(ai_router.router).get("/api/ai/fundamentals/AAPL;rm")

    assert response.status_code == 422
    assert not called
