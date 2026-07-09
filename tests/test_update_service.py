# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
"""Update-check service: semver, asset selection, state machine, ETag caching.

The single HTTP seam (``update_service._http_get``) is monkeypatched in every
test, so no network is ever touched. The per-user data dir is redirected to a
temp path so the last-checked persistence never writes real user settings.
"""
import json

import pytest

from app import paths
from app.services import update_service
from app.version import __version__


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setenv("FOLIO_DISABLE_UPDATE_SCHEDULER", "1")
    update_service._reset_for_tests()
    yield
    update_service._reset_for_tests()


def _macos_assets(version="4.4.0"):
    return [
        {
            "name": f"FolioSenseAI-macOS-arm64-v{version}.dmg",
            "size": 100_663_296,
            "browser_download_url": f"https://github.com/x/releases/download/v{version}/a.dmg",
        },
        {
            "name": "SHA256SUMS.txt",
            "size": 200,
            "browser_download_url":
                f"https://github.com/x/releases/download/v{version}/SHA256SUMS.txt",
        },
    ]


def _release(tag, assets=None, body="What changed"):
    return {
        "tag_name": tag,
        "name": f"FolioSenseAI {tag}",
        "published_at": "2026-07-08T00:00:00Z",
        "body": body,
        "assets": assets if assets is not None else [],
    }


def _patch_response(monkeypatch, payload, status=200, etag="e1"):
    def fake_get(url, headers):
        return status, {"ETag": etag}, json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(update_service, "_http_get", fake_get)


# --------------------------- version parsing ------------------------------- #
def test_parse_version():
    assert update_service.parse_version("4.3.4") == (4, 3, 4)
    assert update_service.parse_version("v4.3.4") == (4, 3, 4)
    assert update_service.parse_version("4.3.4-rc1") == (4, 3, 4)
    assert update_service.parse_version("latest-main") is None
    assert update_service.parse_version("4.3") is None


def test_is_newer_is_downgrade_safe():
    assert update_service.is_newer("4.4.0", "4.3.4") is True
    assert update_service.is_newer("4.3.4", "4.3.4") is False
    assert update_service.is_newer("4.3.3", "4.3.4") is False
    assert update_service.is_newer("latest-main", "4.3.4") is False


# --------------------------- check_for_updates ----------------------------- #
def test_available_when_newer(monkeypatch):
    monkeypatch.setattr(update_service, "current_platform_key", lambda: "macos")
    _patch_response(monkeypatch, _release("v9.9.9", _macos_assets("9.9.9")))
    state = update_service.check_for_updates()
    assert state["status"] == "available"
    assert state["available"]["version"] == "9.9.9"
    assert state["available"]["download_url"].endswith("a.dmg")
    assert state["available"]["sha256_url"].endswith("SHA256SUMS.txt")
    assert state["available"]["size_bytes"] == 100_663_296
    assert state["last_checked_at"] is not None


def test_up_to_date_when_same_version(monkeypatch):
    _patch_response(monkeypatch, _release(f"v{__version__}", _macos_assets(__version__)))
    state = update_service.check_for_updates()
    assert state["status"] == "up_to_date"
    assert state["available"] is None


def test_older_release_is_not_offered(monkeypatch):
    _patch_response(monkeypatch, _release("v0.0.1"))
    state = update_service.check_for_updates()
    assert state["status"] == "up_to_date"


def test_other_platform_has_no_asset_but_still_available(monkeypatch):
    monkeypatch.setattr(update_service, "current_platform_key", lambda: "other")
    _patch_response(monkeypatch, _release("v9.9.9", _macos_assets("9.9.9")))
    state = update_service.check_for_updates()
    assert state["status"] == "available"
    assert state["available"]["download_url"] is None


def test_offline_maps_to_offline_state(monkeypatch):
    def boom(url, headers):
        raise update_service.UpdateOffline("no network")

    monkeypatch.setattr(update_service, "_http_get", boom)
    state = update_service.check_for_updates()
    assert state["status"] == "offline"


def test_rate_limit_maps_to_error_reason(monkeypatch):
    for code in (403, 429):
        monkeypatch.setattr(update_service, "_http_get", lambda u, h, c=code: (c, {}, b""))
        state = update_service.check_for_updates(force=True)
        assert state["status"] == "error"
        assert state["reason"] == "rate_limited"
        assert "rate limit" in state["error"].lower()
        update_service._reset_for_tests()


def test_server_error_maps_to_error_reason(monkeypatch):
    monkeypatch.setattr(update_service, "_http_get", lambda u, h: (503, {}, b""))
    state = update_service.check_for_updates()
    assert state["status"] == "error"
    assert state["reason"] == "server"


def test_malformed_json_maps_to_error_reason(monkeypatch):
    monkeypatch.setattr(
        update_service, "_http_get", lambda u, h: (200, {"ETag": "e"}, b"{not json")
    )
    state = update_service.check_for_updates()
    assert state["status"] == "error"
    assert state["reason"] == "malformed"


def test_tls_failure_is_error_not_offline(monkeypatch):
    """The frozen-app root cause: a cert failure must be an error/tls, not offline."""
    import ssl
    import urllib.error

    def tls_fail(url, headers):
        raise update_service.classify_network_error(
            urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer"))
        )

    monkeypatch.setattr(update_service, "_http_get", tls_fail)
    state = update_service.check_for_updates()
    assert state["status"] == "error"
    assert state["reason"] == "tls"
    assert "securely" in state["error"].lower()


def test_dns_and_timeout_are_offline_with_reason(monkeypatch):
    import socket
    import urllib.error

    for exc, reason in [
        (socket.gaierror("name resolution"), "dns"),
        (TimeoutError("timed out"), "timeout"),
        (ConnectionRefusedError("refused"), "unreachable"),
    ]:
        def boom(url, headers, e=exc):
            raise update_service.classify_network_error(urllib.error.URLError(e))

        monkeypatch.setattr(update_service, "_http_get", boom)
        state = update_service.check_for_updates(force=True)
        assert state["status"] == "offline", reason
        assert state["reason"] == reason
        update_service._reset_for_tests()


def test_error_messages_are_sanitized(monkeypatch):
    """A malicious detail with CRLF must not forge log lines / leak into the message."""
    import urllib.error

    def boom(url, headers):
        raise update_service.classify_network_error(
            urllib.error.URLError("boom\r\nFAKE LOG LINE injected")
        )

    monkeypatch.setattr(update_service, "_http_get", boom)
    state = update_service.check_for_updates()
    # The user-facing message is a fixed friendly string, never the raw detail.
    assert "\n" not in (state.get("error") or "")
    assert "FAKE LOG LINE" not in (state.get("error") or "")


def test_ssl_context_verifies_with_a_ca_bundle():
    """The frozen-app fix: the TLS context must actually verify and load CA certs.

    A context that verifies but has NO CA certs loaded is exactly the broken
    frozen state that produced the false "offline". certifi should give it certs.
    """
    import ssl

    ctx = update_service._build_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    # certifi is a dependency, so the context must have real CA certs loaded.
    assert len(ctx.get_ca_certs()) > 0


def test_classify_network_error_unit():
    import socket
    import ssl
    import urllib.error

    tls = update_service.classify_network_error(
        urllib.error.URLError(ssl.SSLError("handshake"))
    )
    assert isinstance(tls, update_service.UpdateTLSError)
    dns = update_service.classify_network_error(urllib.error.URLError(socket.gaierror("x")))
    assert isinstance(dns, update_service.UpdateOffline) and dns.reason == "dns"


# ------------------------------- caching ----------------------------------- #
def test_etag_cache_avoids_refetch_and_force_bypasses(monkeypatch):
    monkeypatch.setattr(update_service, "current_platform_key", lambda: "macos")
    calls = {"n": 0}

    def fake_get(url, headers):
        calls["n"] += 1
        if calls["n"] == 1:
            body = json.dumps(_release("v9.9.9", _macos_assets("9.9.9"))).encode("utf-8")
            return 200, {"ETag": "e1"}, body
        # A forced refetch must send the stored ETag and may get a 304.
        assert headers.get("If-None-Match") == "e1"
        return 304, {}, b""

    monkeypatch.setattr(update_service, "_http_get", fake_get)

    first = update_service.check_for_updates()
    assert first["status"] == "available"
    # Within TTL and not forced: served from cache, no second HTTP call.
    update_service.check_for_updates()
    assert calls["n"] == 1
    # Forced: hits the network, gets 304, still resolves to the cached release.
    forced = update_service.check_for_updates(force=True)
    assert calls["n"] == 2
    assert forced["status"] == "available"
    assert forced["available"]["version"] == "9.9.9"


def test_get_state_returns_snapshot():
    state = update_service.get_state()
    assert state["status"] == "idle"
    assert state["current_version"] == __version__


# ---------------------------- post-update launch --------------------------- #
def test_note_launch_detects_update():
    from app import app_settings

    app_settings.save_settings({"last_seen_version": "4.3.0"})
    info = update_service.note_launch()
    assert info["just_updated"] is True
    assert info["previous_version"] == "4.3.0"
    # last-seen is advanced so the confirmation shows only once.
    assert app_settings.load_settings()["last_seen_version"] == __version__


def test_note_launch_quiet_on_same_version():
    from app import app_settings

    app_settings.save_settings({"last_seen_version": __version__})
    info = update_service.note_launch()
    assert info["just_updated"] is False


def test_fetch_release_info_for_version(monkeypatch):
    monkeypatch.setattr(update_service, "current_platform_key", lambda: "macos")
    _patch_response(monkeypatch, _release("v4.3.0", _macos_assets("4.3.0")))
    info = update_service.fetch_release_info("4.3.0")
    assert info is not None
    assert info.version == "4.3.0"
    assert info.download_url.endswith("a.dmg")


def test_fetch_release_info_missing_tag_returns_none(monkeypatch):
    monkeypatch.setattr(update_service, "_http_get", lambda url, headers: (404, {}, b""))
    assert update_service.fetch_release_info("9.9.9") is None
