"""Tests for the Anthropic API-key configure/remove endpoints and the .env write.

The endpoints are plain sync functions, so they're called directly with the
disk write, client swap, and network heartbeat monkeypatched — no real key,
no network, no .env touched.

Those three now live behind ``app.services.api_key_store``, so that is what the
stubs replace; the endpoints themselves are still driven for real, which is what
these tests are about.  The store's own behaviour — including the on-disk write,
where the append and the in-place replace are only observable on disk, and where
stubbing everything out once let a trailing-newline bug sit unnoticed — is
covered for real against tmp_path in tests/test_api_key_store.py.
"""
# pylint: disable=protected-access,redefined-outer-name
import pytest
from fastapi import HTTPException

from app.routers import ai as ai_router
from app.services import api_key_store

_VALID_KEY = "sk-ant-api03-" + "A" * 40


def _stub_io(monkeypatch):
    monkeypatch.setattr(api_key_store, "_update_env_file", lambda *a, **k: None)
    monkeypatch.setattr(api_key_store, "reinitialize_client", lambda *a, **k: None)


def test_configure_key_reports_connected_when_heartbeat_live(monkeypatch):
    _stub_io(monkeypatch)
    monkeypatch.setattr(api_key_store, "claude_api_heartbeat", lambda *a, **k: {"live": True})
    resp = ai_router.configure_api_key(ai_router._ApiKeyBody(api_key=_VALID_KEY))
    assert resp["success"] is True
    assert resp["connected"] is True


def test_configure_key_reports_unreachable_when_heartbeat_dead(monkeypatch):
    # A well-formed but revoked/mistyped key must NOT be reported as connected.
    _stub_io(monkeypatch)
    monkeypatch.setattr(api_key_store, "claude_api_heartbeat", lambda *a, **k: {"live": False})
    resp = ai_router.configure_api_key(ai_router._ApiKeyBody(api_key=_VALID_KEY))
    assert resp["success"] is True
    assert resp["connected"] is False
    assert "couldn't reach" in resp["message"].lower()


def test_configure_key_rejects_malformed():
    with pytest.raises(HTTPException) as exc:
        ai_router.configure_api_key(ai_router._ApiKeyBody(api_key="not-a-key"))
    assert exc.value.status_code == 422


def test_remove_key_clears_and_resets_client(monkeypatch):
    seen = {}
    monkeypatch.setattr(api_key_store, "_update_env_file", lambda k, v: seen.update(env=(k, v)))
    monkeypatch.setattr(api_key_store, "reinitialize_client", lambda v: seen.update(reinit=v))
    resp = ai_router.remove_api_key()
    assert resp["success"] is True
    assert seen["env"] == ("ANTHROPIC_API_KEY", "")  # key line cleared
    assert seen["reinit"] == ""                       # client dropped to local
