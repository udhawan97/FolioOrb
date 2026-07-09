"""Download and integrity-verify an update package.

Downloads stream to a ``.part`` file in ``data_dir()/updates/pending`` and resume
with an HTTP ``Range`` request if interrupted, so a dropped connection costs only
the un-fetched bytes. Before an installer is ever handed off, the file's SHA-256
is checked against the ``SHA256SUMS.txt`` published in the *same* release — a
corrupted or tampered download fails here and is discarded.

The HTTP seam (:func:`_open`) is injected in tests, so verification and resume
logic run without the network. Authenticity signing (minisign of the checksum
manifest) is layered on in a later phase; this module provides the integrity
foundation it builds on.
"""
from __future__ import annotations

import hashlib
import logging
import urllib.request
from pathlib import Path

from app import paths

logger = logging.getLogger(__name__)

_CHUNK = 64 * 1024


class DownloadCancelled(Exception):
    """Raised to unwind a download when the user cancels."""


class DownloadError(Exception):
    """Raised for network/IO failures during download."""


def pending_dir() -> Path:
    directory = paths.data_dir() / "updates" / "pending"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def archive_dir() -> Path:
    directory = paths.data_dir() / "updates" / "archive"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _open(request: urllib.request.Request):
    """Open an HTTP request over a certifi-verified TLS context. Injected in tests.

    Shares the update-check module's certifi-backed SSL context so the frozen
    app can verify GitHub's certificate when downloading the DMG / installer and
    the SHA256SUMS manifest — without it, downloads would fail cert verification
    exactly like the check did (see update_service._build_ssl_context).
    """
    from app.services.update_service import _SSL_CONTEXT

    return urllib.request.urlopen(request, timeout=30, context=_SSL_CONTEXT)  # noqa: S310


def _content_length(resp) -> int | None:
    try:
        raw = resp.headers.get("Content-Length")
        return int(raw) if raw is not None else None
    except (ValueError, AttributeError):
        return None


def download_update(url, dest_path, on_progress=None, should_cancel=None) -> Path:
    """Stream ``url`` to ``dest_path``, resuming a prior ``.part`` if present.

    ``on_progress(done_bytes, total_bytes_or_None)`` is called as data arrives.
    ``should_cancel()`` is polled between chunks; returning True raises
    :class:`DownloadCancelled` (the partial file is kept for a later resume).
    Returns ``dest_path`` on success.
    """
    dest_path = Path(dest_path)
    part = dest_path.with_name(dest_path.name + ".part")
    existing = part.stat().st_size if part.exists() else 0

    headers = {"User-Agent": "FolioOrb-Updater"}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        resp = _open(request)
    except Exception as exc:  # pylint: disable=broad-except
        raise DownloadError(str(exc)) from exc

    status = getattr(resp, "status", 200)
    resumed = existing > 0 and status == 206
    if not resumed:
        existing = 0  # server ignored Range (200) → restart cleanly
    remaining = _content_length(resp)
    total = (existing + remaining) if remaining is not None else None

    mode = "ab" if resumed else "wb"
    done = existing
    try:
        with open(part, mode) as handle:
            while True:
                if should_cancel and should_cancel():
                    raise DownloadCancelled()
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    except DownloadCancelled:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise DownloadError(str(exc)) from exc
    finally:
        if hasattr(resp, "close"):
            resp.close()

    part.replace(dest_path)
    logger.info("Downloaded update package %s (%d bytes)", dest_path.name, done)
    return dest_path


def compute_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_sha256sums(text: str, filename: str) -> str | None:
    """Return the lowercase hash for ``filename`` from ``shasum``-format text."""
    target = Path(filename).name
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and Path(parts[-1]).name == target:
            return parts[0].strip().lower()
    return None


def verify_download(path, sha256sums_text: str, filename: str) -> bool:
    """True only if ``path``'s SHA-256 matches its entry in the checksum manifest."""
    expected = parse_sha256sums(sha256sums_text, filename)
    if not expected:
        logger.error("No checksum entry for %s", filename)
        return False
    actual = compute_sha256(path)
    if actual != expected:
        logger.error("Checksum mismatch for %s", filename)
        return False
    return True


def fetch_text(url: str) -> str:
    """Fetch a small text asset (e.g. SHA256SUMS.txt) via the same HTTP seam."""
    request = urllib.request.Request(url, headers={"User-Agent": "FolioOrb-Updater"})
    try:
        resp = _open(request)
        try:
            return resp.read().decode("utf-8")
        finally:
            if hasattr(resp, "close"):
                resp.close()
    except Exception as exc:  # pylint: disable=broad-except
        raise DownloadError(str(exc)) from exc
