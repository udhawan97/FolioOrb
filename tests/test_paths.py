# pylint: disable=protected-access,unused-argument,wrong-import-position,wrong-import-order
"""Source-mode behavior of app.paths.

In a normal checkout the app is not frozen, so resources and writable data both
resolve to the repo root and the app keeps reading ./static, ./templates and
writing ./database and ./.env exactly as before packaging was added.
"""

from pathlib import Path

import platformdirs

from app import paths


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_not_frozen_in_source_checkout():
    assert paths.is_frozen() is False


def test_resource_dir_is_repo_root():
    assert paths.resource_dir() == REPO_ROOT


def test_data_dir_is_repo_root():
    assert paths.data_dir() == REPO_ROOT


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


def test_does_not_overwrite_existing_folioorb_data(tmp_path, monkeypatch):
    """If FolioOrb already has its own database, the legacy copy is skipped."""
    legacy = tmp_path / "FolioSenseAI"
    new = tmp_path / "FolioOrb"
    (new / "database").mkdir(parents=True)
    (new / "database" / "portfolio.db").write_bytes(b"SQLite format 3\x00current")
    _seed_legacy_dir(legacy)
    _point_legacy_at(monkeypatch, legacy, new)

    paths._migrate_legacy_data(new)

    # The current data is untouched, and the legacy .env is NOT copied over.
    assert (new / "database" / "portfolio.db").read_bytes().endswith(b"current")
    assert not (new / ".env").exists()
    assert (new / paths._MIGRATION_MARKER).exists()  # marker still recorded


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
