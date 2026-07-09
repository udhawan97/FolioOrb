"""System / update endpoints.

Exposes the current version, the update-check and status of the update state
machine, and read/write access to the update preferences. Download, install, and
rollback endpoints are added in later phases; the routes here are the read-mostly
surface the UI needs to show version info, run a manual check, and toggle the
Software Updates settings.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import app_settings, paths
from app.services import launch_health, rollback_service, update_installer, update_service
from app.version import __version__

router = APIRouter(prefix="/api/system", tags=["system"])


class UpdateSettingsIn(BaseModel):
    """Only the user-toggleable update preferences may be written here."""

    auto_check_updates: bool | None = None
    notify_updates: bool | None = None
    include_early_builds: bool | None = None


class SkipVersionIn(BaseModel):
    version: str


class RollbackIn(BaseModel):
    # Default False = keep current data (compatible with the older binary via the
    # additive-only migration rule). True = also restore the pre-update snapshot.
    restore_data: bool = False


@router.get("/version")
def get_version() -> dict:
    """Installed version, packaged flag, and whether this is a post-update run."""
    launch = update_service.launch_info()
    return {
        "version": __version__,
        "is_frozen": paths.is_frozen(),
        "platform": update_service.current_platform_key(),
        "just_updated": launch.get("just_updated", False),
        "previous_version": launch.get("previous_version"),
        "update_failed": launch.get("update_failed", False),
    }


@router.get("/update/check")
def check_for_updates(force: bool = False) -> dict:
    """Run an update check (network) and return the resulting state snapshot."""
    return update_service.check_for_updates(force=force)


@router.get("/update/status")
def update_status() -> dict:
    """Return the current update state without triggering a network check."""
    return update_service.get_state()


@router.get("/update/settings")
def get_update_settings() -> dict:
    """Return update preferences plus the last-checked timestamp."""
    return app_settings.load_settings()


@router.put("/update/settings")
def put_update_settings(payload: UpdateSettingsIn) -> dict:
    """Persist only the provided preference fields and echo the merged settings."""
    changes = payload.model_dump(exclude_none=True)
    return app_settings.save_settings(changes)


@router.post("/update/skip")
def skip_version(payload: SkipVersionIn) -> dict:
    """Record a version the user chose to skip so the pill stays hidden for it."""
    return app_settings.save_settings({"skipped_version": payload.version})


@router.post("/update/download")
def start_download() -> dict:
    """Begin downloading the available update (background) and return the state."""
    return update_installer.start_download()


@router.post("/update/cancel")
def cancel_download() -> dict:
    """Cancel an in-progress download; the partial file is kept for resume."""
    return update_installer.cancel_download()


@router.post("/update/install")
def install_update() -> dict:
    """Hand the verified installer to the OS and quit the app (when ready)."""
    return update_installer.install()


@router.get("/rollback/status")
def rollback_status() -> dict:
    """Whether a rollback is available and whether it should be offered proactively."""
    settings = app_settings.load_settings()
    rollback = settings.get("rollback_point") or {}
    return {
        "can_rollback": rollback_service.can_rollback(),
        "previous_version": rollback.get("version"),
        "offer_rollback": launch_health.should_offer_rollback(),
    }


@router.post("/rollback")
def do_rollback(payload: RollbackIn) -> dict:
    """Restore the previous version; optionally also restore the pre-update data."""
    return rollback_service.rollback(restore_data=payload.restore_data)
