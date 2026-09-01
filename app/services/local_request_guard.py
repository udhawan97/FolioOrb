"""ASGI boundary that keeps FolioOrb's unauthenticated HTTP API device-local."""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlsplit


_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _header_values(scope: dict, name: bytes) -> list[str]:
    values = []
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            try:
                values.append(value.decode("ascii"))
            except UnicodeDecodeError:
                values.append("")
    return values


def _authority(value: str) -> tuple[str, int] | None:
    if (
        not value
        or any(character.isspace() for character in value)
        or any(separator in value for separator in ",/\\?#")
    ):
        return None
    try:
        parsed = urlsplit(f"//{value}")
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname not in _LOCAL_HOSTS:
        return None
    return hostname, port if port is not None else 80


def _origin(value: str) -> tuple[str, int] | None:
    if (
        not value
        or value.lower() == "null"
        or any(character.isspace() for character in value)
        or any(separator in value for separator in "\\?#")
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() != "http" or parsed.username is not None:
        return None
    if parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname not in _LOCAL_HOSTS:
        return None
    return hostname, port if port is not None else 80


def _referer_origin(value: str) -> tuple[str, int] | None:
    """Return the local HTTP origin carried by a same-origin Referer."""
    if not value or any(character.isspace() for character in value):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() != "http" or parsed.username is not None:
        return None
    if parsed.password is not None:
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname not in _LOCAL_HOSTS:
        return None
    return hostname, port if port is not None else 80


class LocalRequestGuardMiddleware:
    """Reject DNS rebinding and cross-origin API work before handlers run.

    FolioOrb historically used GET for a few operations that can persist caches,
    update state, or a daily portfolio snapshot. Protecting only HTTP write verbs
    therefore left those handlers reachable from a hostile page. Browser API reads
    must now prove same-origin provenance through Origin, Fetch Metadata, or the
    same-origin Referer fallback used by older WebKit builds. Non-API document and
    static reads remain directly navigable.
    """

    def __init__(self, app, allowed_origins: Iterable[str]):
        self.app = app
        self.allowed_origins = frozenset(
            parsed
            for configured in allowed_origins
            if (parsed := _origin(configured)) is not None
        )

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        hosts = _header_values(scope, b"host")
        host = None
        if len(hosts) == 1:
            host = _authority(hosts[0])
        if host is None:
            await self._reject(send, 400, "invalid_local_host")
            return
        _hostname, host_port = host

        method = str(scope.get("method", "GET")).upper()
        if method in _MUTATION_METHODS:
            if not self._has_same_origin_provenance(scope, host_port, origin_only=True):
                await self._reject(send, 403, "local_mutation_origin_required")
                return
        elif method in _READ_METHODS and self._is_api_path(scope):
            if not self._has_same_origin_provenance(scope, host_port):
                await self._reject(send, 403, "local_api_provenance_required")
                return

        await self.app(scope, receive, send)

    @staticmethod
    def _is_api_path(scope: dict) -> bool:
        path = str(scope.get("path", ""))
        return path == "/api" or path.startswith("/api/")

    def _has_same_origin_provenance(
        self,
        scope: dict,
        host_port: int,
        *,
        origin_only: bool = False,
    ) -> bool:
        origins = _header_values(scope, b"origin")
        if origins:
            if len(origins) != 1:
                return False
            origin = _origin(origins[0])
            return bool(
                origin is not None
                and origin in self.allowed_origins
                and origin[1] == host_port
            )
        if origin_only:
            return False

        fetch_sites = _header_values(scope, b"sec-fetch-site")
        if fetch_sites:
            return len(fetch_sites) == 1 and fetch_sites[0].lower() == "same-origin"

        referers = _header_values(scope, b"referer")
        if len(referers) != 1:
            return False
        referer = _referer_origin(referers[0])
        return bool(
            referer is not None
            and referer in self.allowed_origins
            and referer[1] == host_port
        )

    @staticmethod
    async def _reject(send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
