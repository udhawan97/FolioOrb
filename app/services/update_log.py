"""Dedicated, rotating log for update lifecycle events.

Writes to ``data_dir()/logs/updates.log`` (3 × 512 KB rotation) so update
problems can be diagnosed after the fact, separate from the app's general log.

Only non-sensitive update metadata is recorded — versions, sizes, hashes,
durations, state transitions. Holdings, tickers, portfolio values, and ``.env``
contents are never logged. Every message is passed through
:func:`sanitize_for_log` to prevent log forging.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app import paths
from app.services.log_safety import sanitize_for_log

_LOGGER_NAME = "foliosense.update"
_configured = {"done": False}


def get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured["done"]:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        log_dir = paths.data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "updates.log", maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except Exception:  # pylint: disable=broad-except
        # A logging problem must never block an update; fall back to no file sink.
        pass
    _configured["done"] = True
    return logger


def event(message: str) -> None:
    """Record a single non-sensitive update lifecycle event."""
    try:
        get_logger().info(sanitize_for_log(message))
    except Exception:  # pylint: disable=broad-except
        pass


def _reset_for_tests() -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    _configured["done"] = False
