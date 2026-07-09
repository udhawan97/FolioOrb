"""User-facing application settings persisted outside the database.

Update preferences, the skipped-update version, the last-check timestamp and the
rollback-point metadata live in ``settings.json`` in the per-user data dir — not
in ``portfolio.db``. Keeping them out of the database means they survive a
database restore independently, and a corrupt settings file can never take
holdings data down with it.

Writes are atomic (temp file + ``os.replace``) and a corrupt or unreadable file
degrades to defaults rather than raising, so the app always starts.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from app import paths

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"

# Serializes save_settings()'s read-modify-write within this process — without
# it, the background update-check scheduler and a concurrent user-triggered
# write (e.g. skip-version, a settings toggle) can race and silently drop
# whichever wrote first.
_write_lock = threading.Lock()

# Every persisted key and its default. Only keys listed here are stored or
# returned — unknown keys in an on-disk file are ignored, which keeps the file
# forward/backward compatible across versions.
DEFAULTS: dict[str, Any] = {
    "auto_check_updates": True,
    "notify_updates": True,
    "include_early_builds": False,
    # Version string the user chose to skip (e.g. "4.4.0"); None means none.
    "skipped_version": None,
    # ISO-8601 timestamp of the last successful update check, or None.
    "last_checked_at": None,
    # Rollback point metadata (see update_installer) or None.
    "rollback_point": None,
    # The version the user last actually ran, used to detect a fresh update.
    "last_seen_version": None,
}


def settings_path() -> Path:
    """Absolute path to the settings file in the per-user data directory."""
    return paths.data_dir() / SETTINGS_FILENAME


def load_settings() -> dict[str, Any]:
    """Return the merged settings, falling back to defaults for anything absent.

    A missing, unreadable, or malformed file yields a fresh copy of ``DEFAULTS``
    rather than raising — settings are never allowed to block startup.
    """
    path = settings_path()
    if not path.exists():
        return dict(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("settings.json is not a JSON object")
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning("Ignoring unreadable settings file (%s); using defaults", type(exc).__name__)
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({key: value for key, value in raw.items() if key in DEFAULTS})
    return merged


def save_settings(values: dict[str, Any]) -> dict[str, Any]:
    """Merge ``values`` into the stored settings and write them back atomically.

    Only known keys (present in ``DEFAULTS``) are persisted. Returns the full
    merged settings so callers can echo the resulting state to the UI.
    """
    with _write_lock:
        merged = load_settings()
        merged.update({key: value for key, value in values.items() if key in DEFAULTS})
        _atomic_write(settings_path(), merged)
        return merged


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` as JSON to ``path`` via a temp file + atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
