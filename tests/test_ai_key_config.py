"""Tests for the Anthropic API-key configure/remove endpoints and the .env write.

The endpoints are plain sync functions, so they're called directly with the
disk write, client swap, and network heartbeat monkeypatched — no real key,
no network, no .env touched.

_update_env_file is covered separately at the bottom, where the write runs for
real against tmp_path. The append and the in-place replace are only observable
on disk, and stubbing them out everywhere is what let a trailing-newline bug
sit here unnoticed.
"""
# pylint: disable=protected-access,redefined-outer-name
import pytest
from fastapi import HTTPException

from app.routers import ai as ai_router

_VALID_KEY = "sk-ant-api03-" + "A" * 40


def _stub_io(monkeypatch):
    monkeypatch.setattr(ai_router, "_update_env_file", lambda *a, **k: None)
    monkeypatch.setattr(ai_router, "reinitialize_client", lambda *a, **k: None)


def test_configure_key_reports_connected_when_heartbeat_live(monkeypatch):
    _stub_io(monkeypatch)
    monkeypatch.setattr(ai_router, "claude_api_heartbeat", lambda *a, **k: {"live": True})
    resp = ai_router.configure_api_key(ai_router._ApiKeyBody(api_key=_VALID_KEY))
    assert resp["success"] is True
    assert resp["connected"] is True


def test_configure_key_reports_unreachable_when_heartbeat_dead(monkeypatch):
    # A well-formed but revoked/mistyped key must NOT be reported as connected.
    _stub_io(monkeypatch)
    monkeypatch.setattr(ai_router, "claude_api_heartbeat", lambda *a, **k: {"live": False})
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
    monkeypatch.setattr(ai_router, "_update_env_file", lambda k, v: seen.update(env=(k, v)))
    monkeypatch.setattr(ai_router, "reinitialize_client", lambda v: seen.update(reinit=v))
    resp = ai_router.remove_api_key()
    assert resp["success"] is True
    assert seen["env"] == ("ANTHROPIC_API_KEY", "")  # key line cleared
    assert seen["reinit"] == ""                       # client dropped to local


# ── _update_env_file ──────────────────────────────────────────────────────────


@pytest.fixture
def env_path(tmp_path, monkeypatch):
    """Point the .env write at a throwaway data dir and hand back its path."""
    monkeypatch.setattr(ai_router, "data_dir", lambda: tmp_path)
    return tmp_path / ".env"


def test_an_absent_key_is_appended(env_path):
    env_path.write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    ai_router._update_env_file("ANTHROPIC_API_KEY", "abc")
    assert env_path.read_text(encoding="utf-8") == "LOG_LEVEL=INFO\nANTHROPIC_API_KEY=abc\n"


def test_a_file_with_no_trailing_newline_still_appends_cleanly(env_path):
    """A hand-edited .env often has no final newline; the appended key must start
    its own line instead of being glued onto the last entry, which would destroy
    both that entry and the key."""
    env_path.write_text("LOG_LEVEL=INFO", encoding="utf-8")
    ai_router._update_env_file("ANTHROPIC_API_KEY", "abc")
    assert env_path.read_text(encoding="utf-8") == "LOG_LEVEL=INFO\nANTHROPIC_API_KEY=abc\n"
