# pylint: disable=protected-access,redefined-outer-name
"""Tests for app/services/api_key_store.py — the app's one Anthropic credential.

The .env write runs for real against tmp_path, which is the point: the 0600 mode
and the single-line replace used to be reachable only through a route handler and
were always stubbed there, so nothing covered them.  The client swap and the
Anthropic heartbeat stay recorded stubs — no network, and the process-wide client
is never touched.

The tmp_path redirect is autouse so no test in this file can reach the developer's
real .env even by omission.
"""
import logging
import stat

import pytest

from app.services import api_key_store as store

_VALID_KEY = "sk-ant-api03-" + "A" * 40


@pytest.fixture(autouse=True)
def env_path(tmp_path, monkeypatch):
    """Point the store at a throwaway data dir and hand back its .env path."""
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path / ".env"


@pytest.fixture
def calls(monkeypatch):
    """Record the client swap; answer the heartbeat live unless a test says otherwise."""
    recorded: dict = {"reinit": [], "heartbeats": 0, "live": True}
    monkeypatch.setattr(store, "reinitialize_client", recorded["reinit"].append)

    def _heartbeat(*_args, **_kwargs):
        recorded["heartbeats"] += 1
        return {"live": recorded["live"]}

    monkeypatch.setattr(store, "claude_api_heartbeat", _heartbeat)
    return recorded


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ── The .env line ─────────────────────────────────────────────────────────────


def test_a_new_file_is_created_owner_only(env_path):
    store._update_env_file("ANTHROPIC_API_KEY", "abc")
    assert env_path.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=abc\n"
    assert _mode(env_path) == 0o600


def test_a_loosened_file_is_retightened_on_every_write(env_path):
    """0600 is re-applied, not just set once — a chmod 644 must not survive a save."""
    env_path.write_text("ANTHROPIC_API_KEY=old\n", encoding="utf-8")
    env_path.chmod(0o644)
    store._update_env_file("ANTHROPIC_API_KEY", "new")
    assert _mode(env_path) == 0o600


def test_the_key_line_is_replaced_in_place_leaving_neighbours_alone(env_path):
    env_path.write_text(
        "DEFAULT_HOLDINGS=VOO,QQQ\nANTHROPIC_API_KEY=old\nLOG_LEVEL=INFO\n",
        encoding="utf-8",
    )
    store._update_env_file("ANTHROPIC_API_KEY", "new")
    assert env_path.read_text(encoding="utf-8") == (
        "DEFAULT_HOLDINGS=VOO,QQQ\nANTHROPIC_API_KEY=new\nLOG_LEVEL=INFO\n"
    )


def test_an_absent_key_is_appended(env_path):
    env_path.write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    store._update_env_file("ANTHROPIC_API_KEY", "abc")
    assert env_path.read_text(encoding="utf-8") == "LOG_LEVEL=INFO\nANTHROPIC_API_KEY=abc\n"


def test_a_padded_key_line_still_matches(env_path):
    """Hand-edited .env files indent and space out; that is still the same key."""
    env_path.write_text("  ANTHROPIC_API_KEY = old\n", encoding="utf-8")
    store._update_env_file("ANTHROPIC_API_KEY", "new")
    assert env_path.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=new\n"


def test_only_the_first_duplicate_line_is_rewritten(env_path):
    env_path.write_text("ANTHROPIC_API_KEY=a\nANTHROPIC_API_KEY=b\n", encoding="utf-8")
    store._update_env_file("ANTHROPIC_API_KEY", "c")
    assert env_path.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=c\nANTHROPIC_API_KEY=b\n"


def test_a_file_with_no_trailing_newline_still_appends_cleanly(env_path):
    """A hand-edited .env often has no final newline; both entries must survive."""
    env_path.write_text("LOG_LEVEL=INFO", encoding="utf-8")
    store._update_env_file("ANTHROPIC_API_KEY", "abc")
    assert env_path.read_text(encoding="utf-8") == "LOG_LEVEL=INFO\nANTHROPIC_API_KEY=abc\n"


# ── save() ────────────────────────────────────────────────────────────────────


def test_save_persists_swaps_the_client_and_reports_connected(env_path, calls):
    assert store.save(_VALID_KEY) is True
    assert env_path.read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY={_VALID_KEY}\n"
    assert calls["reinit"] == [_VALID_KEY]
    assert calls["heartbeats"] == 1


def test_save_reports_not_connected_when_anthropic_does_not_answer(calls):
    """A well-formed key can still be revoked: saved is not the same as working."""
    calls["live"] = False
    assert store.save(_VALID_KEY) is False
    assert calls["reinit"] == [_VALID_KEY]


def test_save_strips_surrounding_whitespace_before_storing(env_path, calls):
    store.save(f"  {_VALID_KEY}\n")
    assert env_path.read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY={_VALID_KEY}\n"
    assert calls["reinit"] == [_VALID_KEY]


@pytest.mark.parametrize("bad", ["", "   ", "not-a-key", "sk-ant-short", "sk-ant-" + "A" * 400])
def test_save_rejects_a_malformed_key_before_touching_anything(bad, env_path, calls):
    with pytest.raises(store.InvalidKeyError):
        store.save(bad)
    assert not env_path.exists()
    assert calls["reinit"] == []
    assert calls["heartbeats"] == 0


def test_save_leaves_the_client_alone_when_the_write_fails(monkeypatch, calls):
    def _boom(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(store, "_update_env_file", _boom)
    with pytest.raises(store.KeyStorageError):
        store.save(_VALID_KEY)
    assert calls["reinit"] == []
    assert calls["heartbeats"] == 0


@pytest.mark.usefixtures("calls")
def test_save_never_writes_the_key_to_the_log(caplog):
    caplog.set_level(logging.DEBUG)
    store.save(_VALID_KEY)
    assert _VALID_KEY not in caplog.text
    assert "A" * 40 not in caplog.text


# ── clear() ───────────────────────────────────────────────────────────────────


def test_clear_blanks_the_line_and_drops_the_client_to_local(env_path, calls):
    env_path.write_text(f"ANTHROPIC_API_KEY={_VALID_KEY}\nLOG_LEVEL=INFO\n", encoding="utf-8")
    store.clear()
    assert env_path.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=\nLOG_LEVEL=INFO\n"
    assert calls["reinit"] == [""]
    assert calls["heartbeats"] == 0


@pytest.mark.usefixtures("calls")
def test_clear_keeps_one_line_so_a_later_save_edits_it(env_path):
    store.save(_VALID_KEY)
    store.clear()
    store.save(_VALID_KEY)
    assert env_path.read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY={_VALID_KEY}\n"


def test_clear_leaves_claude_connected_when_the_write_fails(monkeypatch, calls):
    """Dropping the client on a failed write would report a disconnect that did not happen."""
    def _boom(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(store, "_update_env_file", _boom)
    with pytest.raises(store.KeyStorageError):
        store.clear()
    assert calls["reinit"] == []
