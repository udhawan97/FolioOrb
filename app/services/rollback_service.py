"""Restore the previous version safely, without ever losing current data.

A rollback point is recorded before each in-app update (see
:mod:`app.services.update_installer`): the outgoing version plus a verified
snapshot of the database and ``.env`` at that moment. Rolling back:

1. Takes a *fresh* verified backup of the CURRENT data first, so whichever data
   the user ends up with, the other copy is always recoverable — a rollback can
   never corrupt or silently discard newer data.
2. Optionally restores the pre-update snapshot (the user's explicit choice); the
   default keeps current data, which an older binary can still read because
   migrations are additive-only.
3. Reinstalls the previous version's binary — from the archived installer if
   present, otherwise re-downloaded from that version's release — then quits so
   the installer can run.

The data steps are fully offline (backups are local). Only reinstalling the
binary may need the network; if it's unavailable, the data is already safe and
the user is pointed at the releases page.
"""
from __future__ import annotations

import logging

from app.services import (
    backup_service,
    update_downloader,
    update_installer,
    update_log,
    update_service,
)
from app.services.update_service import UpdateStatus

logger = logging.getLogger(__name__)

# Statuses that mean an update download/verify/backup/install is actively in
# flight. Rollback refuses to start while one of these is active — running
# both at once would interleave writes to update_service's shared state and
# could overlap two OS-level install handoffs.
_BUSY_STATUSES = {
    UpdateStatus.DOWNLOADING.value,
    UpdateStatus.VERIFYING.value,
    UpdateStatus.BACKING_UP.value,
    UpdateStatus.INSTALLING.value,
}


def _rollback_point() -> dict | None:
    from app import app_settings

    return app_settings.load_settings().get("rollback_point")


def can_rollback() -> bool:
    """True when a rollback point with an existing, verified DB backup is present."""
    from pathlib import Path

    point = _rollback_point()
    if not point or not point.get("db_backup"):
        return False
    return Path(point["db_backup"]).exists()


def rollback(restore_data: bool = False) -> dict:  # pylint: disable=too-many-return-statements
    """Roll back to the previous version. See module docstring for the contract."""
    current = update_service.get_state()
    if current.get("status") in _BUSY_STATUSES:
        return update_service.mark(
            UpdateStatus.ERROR,
            error="An update is already in progress. Wait for it to finish before restoring "
            "a previous version.",
        )

    rollback_point = _rollback_point()
    if not rollback_point or not rollback_point.get("db_backup"):
        return update_service.mark(
            UpdateStatus.ERROR, error="There's no previous version to restore."
        )

    update_service.mark(UpdateStatus.BACKING_UP)

    # 1. Always snapshot current data first — nothing newer is ever lost.
    try:
        source_db = backup_service.live_db_path()
        pre_count = backup_service.count_holdings(source_db)
        safety = backup_service.create_backup(source_db, label="pre-rollback")
        if not backup_service.verify_backup(safety, expected_min_holdings=pre_count):
            raise ValueError("safety backup failed verification")
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Pre-rollback safety backup failed: %s", type(exc).__name__)
        return update_service.mark(
            UpdateStatus.ERROR,
            error="Couldn't safeguard your current data, so the rollback was paused.",
        )

    # 2. Optionally restore the pre-update snapshot (explicit user choice).
    if restore_data:
        try:
            backup_service.restore_backup(
                rollback_point["db_backup"], backup_service.live_db_path()
            )
            if rollback_point.get("env_backup"):
                backup_service.restore_env(rollback_point["env_backup"])
            update_log.event("rollback restored pre-update data snapshot")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to restore pre-update snapshot")
            return update_service.mark(
                UpdateStatus.ERROR, error="Couldn't restore the earlier data snapshot."
            )

    # 3. Reinstall the previous binary.
    installer = _resolve_previous_installer(rollback_point)
    if installer is None:
        update_log.event("rollback: previous installer unavailable")
        return update_service.mark(
            UpdateStatus.ERROR,
            error="Your data is safe. Reinstall the previous version from the "
            "releases page to finish rolling back.",
        )

    try:
        update_installer.launch_installer(installer)
    except Exception:  # pylint: disable=broad-except
        logger.exception("Failed to launch rollback installer")
        return update_service.mark(
            UpdateStatus.ERROR, error="Couldn't start the previous version's installer."
        )

    update_log.event(f"rollback handoff to version={rollback_point.get('version')}")
    state = update_service.mark(UpdateStatus.INSTALLING)
    update_installer.schedule_exit()
    return state


def _resolve_previous_installer(rollback_point: dict):
    """Return a path to the previous version's installer, archived or downloaded."""
    from pathlib import Path

    archived = rollback_point.get("installer")
    if archived and Path(archived).exists():
        return Path(archived)

    version = rollback_point.get("version")
    if not version:
        return None

    info = update_service.fetch_release_info(version)
    if not info or not info.download_url or not info.asset_name:
        return None

    dest = update_downloader.archive_dir() / info.asset_name
    try:
        update_downloader.download_update(info.download_url, dest)
        if info.sha256_url:
            sums = update_downloader.fetch_text(info.sha256_url)
            if not update_downloader.verify_download(dest, sums, info.asset_name):
                logger.error("Rollback installer failed verification")
                return None
        return dest
    except Exception:  # pylint: disable=broad-except
        logger.exception("Failed to fetch previous installer")
        return None
