# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
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
    # Post-update signals surfaced for the UI toast.
    assert body["just_updated"] is False
    assert body["update_failed"] is False


def test_check_endpoint_surfaces_reason(client, monkeypatch):
    monkeypatch.setattr(
        update_service, "check_for_updates",
        lambda force=False: {"status": "error", "reason": "tls", "error": "nope"},
    )
    body = client.get("/api/system/update/check").json()
    assert body["status"] == "error"
    assert body["reason"] == "tls"


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


def test_download_cancel_install_endpoints_return_state(client, monkeypatch):
    from app.services import update_installer

    monkeypatch.setattr(update_installer, "start_download", lambda: {"status": "downloading"})
    monkeypatch.setattr(update_installer, "cancel_download", lambda: {"status": "available"})
    monkeypatch.setattr(update_installer, "install", lambda: {"status": "installing"})

    assert client.post("/api/system/update/download").json()["status"] == "downloading"
    assert client.post("/api/system/update/cancel").json()["status"] == "available"
    assert client.post("/api/system/update/install").json()["status"] == "installing"


def test_rollback_endpoints(client, monkeypatch):
    from app.services import launch_health, rollback_service

    monkeypatch.setattr(rollback_service, "can_rollback", lambda: True)
    monkeypatch.setattr(launch_health, "should_offer_rollback", lambda: False)
    status = client.get("/api/system/rollback/status").json()
    assert status["can_rollback"] is True
    assert status["offer_rollback"] is False

    monkeypatch.setattr(
        rollback_service,
        "rollback",
        lambda restore_data=False: {"status": "installing", "restore": restore_data},
    )
    body = client.post("/api/system/rollback", json={"restore_data": True}).json()
    assert body["status"] == "installing"
    assert body["restore"] is True
