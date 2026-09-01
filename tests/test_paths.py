# pylint: disable=protected-access,unused-argument,wrong-import-position,wrong-import-order
"""Source-mode behavior of app.paths.

In a normal checkout the app is not frozen, so resources and writable data both
resolve to the repo root and the app keeps reading ./static, ./templates and
writing ./database and ./.env exactly as before packaging was added.
"""

from pathlib import Path

import platformdirs
import pytest

from app import paths


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_not_frozen_in_source_checkout():
    assert paths.is_frozen() is False


def test_resource_dir_is_repo_root():
    assert paths.resource_dir() == REPO_ROOT


def test_data_dir_is_repo_root(monkeypatch):
    monkeypatch.delenv("FOLIOORB_DATA_DIR", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert paths.data_dir() == REPO_ROOT


def test_data_dir_override_bypasses_frozen_legacy_migration(tmp_path, monkeypatch):
    isolated = tmp_path / "isolated-smoke"
    monkeypatch.setenv("FOLIOORB_DATA_DIR", str(isolated))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)

    def forbidden_migration(_directory):
        raise AssertionError("legacy migration must not run for an isolated data root")

    monkeypatch.setattr(paths, "_migrate_legacy_data", forbidden_migration)

    assert paths.data_dir() == isolated.resolve()
    assert isolated.is_dir()


def test_bundled_resources_resolve_from_resource_dir():
    assert (paths.resource_dir() / "static").is_dir()
    assert (paths.resource_dir() / "templates" / "index.html").is_file()


# --------------------------------------------------------------------------- #
# FolioSenseAI -> FolioOrb data migration (frozen-only path)
# --------------------------------------------------------------------------- #
# These tests exercise app.paths' private migration helpers directly.
# pylint: disable=protected-access


def _seed_legacy_dir(legacy: Path) -> None:
    """Create a realistic pre-rename FolioSenseAI data tree."""
    (legacy / "database").mkdir(parents=True)
    (legacy / "database" / "portfolio.db").write_bytes(b"SQLite format 3\x00legacy")
    (legacy / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-legacy\n", encoding="utf-8")
    (legacy / "updates").mkdir()
    (legacy / "updates" / "last-update-ok").write_text("", encoding="utf-8")


def _point_legacy_at(monkeypatch, legacy: Path, new: Path) -> None:
    """Make platformdirs.user_data_dir resolve the legacy app name to ``legacy``.

    ``_migrate_legacy_data`` does ``from platformdirs import user_data_dir`` at
    call time, so patching the attribute on the module is what it picks up.
    """
    def fake_user_data_dir(appname, _appauthor):
        return str(legacy) if appname == paths.LEGACY_APP_NAME else str(new)

    monkeypatch.setattr(platformdirs, "user_data_dir", fake_user_data_dir)


def test_migrates_legacy_data_when_new_dir_is_empty(tmp_path, monkeypatch):
    """A fresh FolioOrb dir adopts the old FolioSenseAI database, .env, and markers."""
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)

    paths._migrate_legacy_data(new)

    assert (new / "database" / "portfolio.db").read_bytes().endswith(b"legacy")
    assert (new / ".env").read_text(encoding="utf-8").strip().endswith("sk-ant-legacy")
    assert (new / "updates" / "last-update-ok").exists()
    # Marker written so it never runs twice, and the legacy dir is left intact.
    assert (new / paths._MIGRATION_MARKER).exists()
    assert (legacy / "database" / "portfolio.db").exists()


def test_ambiguous_existing_folioorb_data_stops_without_writing(tmp_path, monkeypatch):
    """Independent FolioOrb state is never silently classified as migrated."""
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    (new / "database").mkdir(parents=True)
    (new / "database" / "portfolio.db").write_bytes(b"SQLite format 3\x00current")
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)

    before = (new / "database" / "portfolio.db").read_bytes()

    with pytest.raises(paths.ProfileMigrationAmbiguityError, match="ambiguous ownership"):
        paths._migrate_legacy_data(new)

    # The current data is untouched, and the legacy .env is NOT copied over.
    assert (new / "database" / "portfolio.db").read_bytes() == before
    assert not (new / ".env").exists()
    assert not (new / paths._MIGRATION_MARKER).exists()


def test_migration_is_idempotent_once_marker_present(tmp_path, monkeypatch):
    """A second run is a no-op even if the legacy dir still has files."""
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    (new / paths._MIGRATION_MARKER).write_text("done\n", encoding="utf-8")
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)

    paths._migrate_legacy_data(new)

    # Marker was already there → nothing copied.
    assert not (new / ".env").exists()
    assert not (new / "database").exists()


def test_partial_staging_copy_retries_and_completes(tmp_path, monkeypatch):
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)
    real_copy = paths.shutil.copy2
    failed_once = False

    def fail_once(source, destination):
        nonlocal failed_once
        if Path(source).name == "last-update-ok" and not failed_once:
            failed_once = True
            raise OSError("simulated copy interruption")
        return real_copy(source, destination)

    monkeypatch.setattr(paths.shutil, "copy2", fail_once)
    with pytest.raises(OSError, match="copy interruption"):
        paths._migrate_legacy_data(new)

    staging = tmp_path / ".FolioOrb.migrating-from-foliosenseai"
    assert staging.is_dir()
    assert legacy.is_dir()
    assert not (new / paths._MIGRATION_MARKER).exists()

    monkeypatch.setattr(paths.shutil, "copy2", real_copy)
    paths._migrate_legacy_data(new)

    assert (new / paths._MIGRATION_MARKER).is_file()
    assert (new / "updates" / "last-update-ok").is_file()
    assert legacy.is_dir()


def test_marker_write_failure_retries_without_publishing_partial_state(
    tmp_path, monkeypatch
):
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)
    real_write_text = Path.write_text
    failed_once = False

    def fail_marker(path, *args, **kwargs):
        nonlocal failed_once
        if path.name == paths._MIGRATION_MARKER and not failed_once:
            failed_once = True
            raise OSError("simulated marker failure")
        return real_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_marker)
    with pytest.raises(OSError, match="marker failure"):
        paths._migrate_legacy_data(new)

    assert not (new / paths._MIGRATION_MARKER).exists()
    assert legacy.is_dir()
    monkeypatch.setattr(Path, "write_text", real_write_text)
    paths._migrate_legacy_data(new)
    assert (new / paths._MIGRATION_MARKER).is_file()


def test_old_partial_destination_is_recognized_by_bytes_and_resumed(tmp_path, monkeypatch):
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    _seed_legacy_dir(legacy)
    (new / ".env").write_bytes((legacy / ".env").read_bytes())
    _point_legacy_at(monkeypatch, legacy, new)

    paths._migrate_legacy_data(new)

    assert (new / "database" / "portfolio.db").read_bytes() == (
        legacy / "database" / "portfolio.db"
    ).read_bytes()
    assert (new / paths._MIGRATION_MARKER).is_file()


@pytest.mark.parametrize("fault_boundary", ("previous", "publish"))
def test_publication_rename_failures_leave_retryable_canonical_root(
    tmp_path, monkeypatch, fault_boundary
):
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)
    real_replace = Path.replace

    def faulted_replace(source, destination):
        destination = Path(destination)
        is_previous = source == new and destination.name.startswith(
            ".FolioOrb.migration-previous-"
        )
        is_publish = source.name == ".FolioOrb.migrating-from-foliosenseai"
        if (fault_boundary == "previous" and is_previous) or (
            fault_boundary == "publish" and is_publish
        ):
            raise OSError("simulated publication rename failure")
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", faulted_replace)
    with pytest.raises(OSError, match="publication rename failure"):
        paths._migrate_legacy_data(new)

    assert new.is_dir()
    assert legacy.is_dir()
    staging = tmp_path / ".FolioOrb.migrating-from-foliosenseai"
    assert (staging / paths._MIGRATION_MARKER).is_file()

    monkeypatch.setattr(Path, "replace", real_replace)
    paths._migrate_legacy_data(new)
    assert (new / paths._MIGRATION_MARKER).is_file()


def test_rollback_rename_failure_preserves_previous_copy_and_retry(tmp_path, monkeypatch):
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)
    real_replace = Path.replace

    def faulted_replace(source, destination):
        destination = Path(destination)
        if source.name == ".FolioOrb.migrating-from-foliosenseai":
            raise OSError("simulated publish failure")
        if source.name.startswith(".FolioOrb.migration-previous-") and destination == new:
            raise OSError("simulated rollback failure")
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", faulted_replace)
    with pytest.raises(OSError, match="publish failure"):
        paths._migrate_legacy_data(new)

    assert new.is_dir()
    assert legacy.is_dir()
    assert list(tmp_path.glob(".FolioOrb.migration-previous-*"))

    monkeypatch.setattr(Path, "replace", real_replace)
    paths._migrate_legacy_data(new)
    assert (new / paths._MIGRATION_MARKER).is_file()


def test_cleanup_failure_keeps_completed_profile_and_legacy_source(tmp_path, monkeypatch):
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)

    def fail_cleanup(_path):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(paths.shutil, "rmtree", fail_cleanup)
    paths._migrate_legacy_data(new)

    assert (new / paths._MIGRATION_MARKER).is_file()
    assert legacy.is_dir()
    assert list(tmp_path.glob(".FolioOrb.migration-previous-*"))


def test_legacy_symlink_stops_before_staging(tmp_path, monkeypatch):
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    new.mkdir()
    legacy.mkdir()
    referent = tmp_path / "outside"
    referent.write_text("outside", encoding="utf-8")
    (legacy / "linked").symlink_to(referent)
    _point_legacy_at(monkeypatch, legacy, new)

    with pytest.raises(paths.ProfileMigrationAmbiguityError, match="symlink"):
        paths._migrate_legacy_data(new)

    assert not (tmp_path / ".FolioOrb.migrating-from-foliosenseai").exists()
