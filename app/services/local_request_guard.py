"""ASGI boundary that keeps FolioOrb's unauthenticated HTTP API device-local."""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlsplit


_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


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


class LocalRequestGuardMiddleware:
    """Reject DNS rebinding and cross-origin mutations before route handlers run."""

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
            origins = _header_values(scope, b"origin")
            origin = None
            if len(origins) == 1:
                origin = _origin(origins[0])
            if origin is None:
                await self._reject(send, 403, "local_mutation_origin_required")
                return
            _origin_hostname, origin_port = origin
            if origin not in self.allowed_origins or origin_port != host_port:
                await self._reject(send, 403, "local_mutation_origin_required")
                return

        await self.app(scope, receive, send)

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
