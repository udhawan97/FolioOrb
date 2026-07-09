"""System/update API endpoints.

Mounts only the system router on a bare FastAPI app so the full application
lifespan (DB migration, cache warmup, update scheduler) is not triggered. The
data dir is redirected so settings writes stay in a temp path.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import paths
from app.routers import system
from app.services import update_service
from app.version import __version__


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setenv("FOLIO_DISABLE_UPDATE_SCHEDULER", "1")
    app = FastAPI()
    app.include_router(system.router)
    return TestClient(app)


def test_version_endpoint(client):
    body = client.get("/api/system/version").json()
    assert body["version"] == __version__
    assert body["is_frozen"] is False
    assert body["platform"] in {"macos", "windows", "other"}


def test_check_endpoint_returns_state(client, monkeypatch):
    monkeypatch.setattr(
        update_service,
        "check_for_updates",
        lambda force=False: {"status": "up_to_date", "current_version": __version__},
    )
    body = client.get("/api/system/update/check").json()
    assert body["status"] == "up_to_date"


def test_status_endpoint(client, monkeypatch):
    monkeypatch.setattr(update_service, "get_state", lambda: {"status": "idle"})
    assert client.get("/api/system/update/status").json()["status"] == "idle"


def test_settings_get_and_put_roundtrip(client):
    defaults = client.get("/api/system/update/settings").json()
    assert defaults["auto_check_updates"] is True

    updated = client.put(
        "/api/system/update/settings", json={"auto_check_updates": False}
    ).json()
    assert updated["auto_check_updates"] is False
    # Persisted across requests.
    assert client.get("/api/system/update/settings").json()["auto_check_updates"] is False


def test_put_settings_ignores_unknown_fields(client):
    updated = client.put(
        "/api/system/update/settings",
        json={"notify_updates": False, "skipped_version": "9.9.9"},
    ).json()
    assert updated["notify_updates"] is False
    # skipped_version is not a settable preference on this endpoint.
    assert updated["skipped_version"] is None


def test_skip_version_endpoint(client):
    body = client.post("/api/system/update/skip", json={"version": "4.4.0"}).json()
    assert body["skipped_version"] == "4.4.0"
