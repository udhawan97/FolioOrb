# pylint: disable=protected-access
"""Runtime profile ownership is resolved before FolioOrb creates local state."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import paths


CANONICAL_DATABASE_URL = "sqlite:///./database/portfolio.db"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _source_profile(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    source_root = tmp_path / "source"
    outside = tmp_path / "outside"
    source_root.mkdir()
    monkeypatch.setattr(paths, "_source_root", lambda: source_root)
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    monkeypatch.delenv("FOLIOORB_DATA_DIR", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return source_root, outside


def _tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def test_canonical_source_profile_normalizes_inside_source_root(tmp_path, monkeypatch):
    source_root, _outside = _source_profile(tmp_path, monkeypatch)
    (source_root / ".env").write_text(
        f"DATABASE_URL={CANONICAL_DATABASE_URL}\n", encoding="utf-8"
    )

    profile = paths.resolve_runtime_profile()

    assert profile.data_root == source_root
    assert profile.database_path == source_root / "database" / "portfolio.db"
    assert profile.database_url == f"sqlite:///{profile.database_path.as_posix()}"


def test_data_root_alone_derives_database_without_writing(tmp_path, monkeypatch):
    source_root, _outside = _source_profile(tmp_path, monkeypatch)
    isolated = tmp_path / "isolated-profile"
    monkeypatch.setenv("FOLIOORB_DATA_DIR", str(isolated))
    baseline = _tree(tmp_path)

    profile = paths.resolve_runtime_profile()

    assert profile.data_root == isolated
    assert profile.database_path == isolated / "database" / "portfolio.db"
    assert _tree(tmp_path) == baseline
    assert not isolated.exists()
    assert source_root.exists()


def test_database_only_outside_default_root_fails_without_writing(tmp_path, monkeypatch):
    _source_root, outside = _source_profile(tmp_path, monkeypatch)
    database = outside / "portfolio.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    baseline = _tree(tmp_path)

    with pytest.raises(paths.ProfileConfigurationError, match="FOLIOORB_DATA_DIR"):
        paths.resolve_runtime_profile()

    assert _tree(tmp_path) == baseline
    assert not outside.exists()


def test_dotenv_database_outside_default_root_fails_without_writing(tmp_path, monkeypatch):
    source_root, outside = _source_profile(tmp_path, monkeypatch)
    database = outside / "portfolio.db"
    (source_root / ".env").write_text(
        f"DATABASE_URL=sqlite:///{database.as_posix()}\n", encoding="utf-8"
    )
    baseline = _tree(tmp_path)

    with pytest.raises(paths.ProfileConfigurationError, match="same profile"):
        paths.resolve_runtime_profile()

    assert _tree(tmp_path) == baseline
    assert not outside.exists()


def test_process_database_precedes_dotenv_value(tmp_path, monkeypatch):
    source_root, outside = _source_profile(tmp_path, monkeypatch)
    (source_root / ".env").write_text(
        f"DATABASE_URL=sqlite:///{(outside / 'wrong.db').as_posix()}\n",
        encoding="utf-8",
    )
    intended = source_root / "database" / "portfolio.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{intended.as_posix()}")

    profile = paths.resolve_runtime_profile()

    assert profile.database_path == intended


def test_dotenv_cannot_redirect_data_root_after_profile_is_frozen(tmp_path):
    source_root = tmp_path / "source"
    redirected = tmp_path / "redirected"
    source_root.mkdir()
    (source_root / ".env").write_text(
        f"FOLIOORB_DATA_DIR={redirected}\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment.pop("FOLIOORB_DATA_DIR", None)
    environment.pop("DATABASE_URL", None)
    script = (
        "import sys; from pathlib import Path; from app import paths; "
        "paths._source_root = lambda: Path(sys.argv[1]); "
        "from app.config import settings; "
        "print(settings.DATABASE_URL); print(paths.data_dir())"
    )

    result = subprocess.run(
        (sys.executable, "-c", script, str(source_root)),
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )

    assert result.stdout.splitlines() == [
        f"sqlite:///{(source_root / 'database' / 'portfolio.db').as_posix()}",
        str(source_root),
    ]
    assert not redirected.exists()


def test_both_overrides_require_database_inside_data_root(tmp_path, monkeypatch):
    _source_root, _outside = _source_profile(tmp_path, monkeypatch)
    isolated = tmp_path / "isolated"
    inside = isolated / "database" / "custom.db"
    monkeypatch.setenv("FOLIOORB_DATA_DIR", str(isolated))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{inside.as_posix()}")

    assert paths.resolve_runtime_profile().database_path == inside

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    with pytest.raises(paths.ProfileConfigurationError, match="inside"):
        paths.resolve_runtime_profile()


def test_database_cannot_equal_profile_root_and_creates_nothing(tmp_path, monkeypatch):
    _source_root, _outside = _source_profile(tmp_path, monkeypatch)
    profile_root = tmp_path / "profile"
    monkeypatch.setenv("FOLIOORB_DATA_DIR", str(profile_root))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{profile_root.as_posix()}")
    baseline = _tree(tmp_path)

    with pytest.raises(paths.ProfileConfigurationError, match="profile directory"):
        paths.prepare_runtime_profile()

    assert _tree(tmp_path) == baseline
    assert not profile_root.exists()


def test_existing_directory_cannot_be_used_as_database(tmp_path, monkeypatch):
    _source_root, _outside = _source_profile(tmp_path, monkeypatch)
    profile_root = tmp_path / "profile"
    database_directory = profile_root / "database-target"
    database_directory.mkdir(parents=True)
    monkeypatch.setenv("FOLIOORB_DATA_DIR", str(profile_root))
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite:///{database_directory.as_posix()}"
    )
    baseline = _tree(tmp_path)

    with pytest.raises(paths.ProfileConfigurationError, match="SQLite file"):
        paths.resolve_runtime_profile()

    assert _tree(tmp_path) == baseline


def test_equal_root_profile_is_zero_write_at_config_boundary(tmp_path):
    profile_root = tmp_path / "profile"
    environment = os.environ.copy()
    environment.update(
        {
            "FOLIOORB_DATA_DIR": str(profile_root),
            "DATABASE_URL": f"sqlite:///{profile_root.as_posix()}",
            "ANTHROPIC_API_KEY": "",
        }
    )
    baseline = _tree(tmp_path)

    result = subprocess.run(
        (sys.executable, "-c", "from app.config import settings"),
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "profile directory" in result.stderr
    assert _tree(tmp_path) == baseline
    assert not profile_root.exists()


def test_noncanonical_relative_database_requires_explicit_profile(tmp_path, monkeypatch):
    _source_root, _outside = _source_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./database/ci-portfolio.db")

    with pytest.raises(paths.ProfileConfigurationError, match="non-default database"):
        paths.resolve_runtime_profile()


def test_noncanonical_absolute_database_requires_explicit_profile(tmp_path, monkeypatch):
    source_root, _outside = _source_profile(tmp_path, monkeypatch)
    database = source_root / "database" / "ci-portfolio.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")

    with pytest.raises(paths.ProfileConfigurationError, match="non-default database"):
        paths.resolve_runtime_profile()


def test_rejected_profile_does_not_run_legacy_migration(tmp_path, monkeypatch):
    new_root = tmp_path / "FolioOrb"
    legacy_root = tmp_path / "FolioSenseAI"
    legacy_root.mkdir()
    legacy_db = legacy_root / "database" / "portfolio.db"
    (legacy_root / ".env").write_text(
        f"DATABASE_URL=sqlite:///{legacy_db.as_posix()}\n", encoding="utf-8"
    )
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "_frozen_data_root", lambda: new_root)
    monkeypatch.setattr(paths, "_legacy_data_root", lambda: legacy_root)
    monkeypatch.delenv("FOLIOORB_DATA_DIR", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    baseline = _tree(tmp_path)

    with pytest.raises(paths.ProfileConfigurationError, match="same profile"):
        paths.prepare_runtime_profile()

    assert _tree(tmp_path) == baseline
    assert not new_root.exists()


def test_legacy_canonical_profile_is_validated_then_copied(tmp_path, monkeypatch):
    new_root = tmp_path / "FolioOrb"
    legacy_root = tmp_path / "FolioSenseAI"
    legacy_db = legacy_root / "database" / "portfolio.db"
    legacy_db.parent.mkdir(parents=True)
    legacy_db.write_bytes(b"SQLite format 3\x00legacy")
    (legacy_root / ".env").write_text(
        f"DATABASE_URL={CANONICAL_DATABASE_URL}\n", encoding="utf-8"
    )
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "_frozen_data_root", lambda: new_root)
    monkeypatch.setattr(paths, "_legacy_data_root", lambda: legacy_root)
    monkeypatch.delenv("FOLIOORB_DATA_DIR", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    resolved = paths.resolve_runtime_profile()
    assert resolved.env_source == legacy_root / ".env"
    assert not new_root.exists()

    prepared = paths.prepare_runtime_profile()
    assert prepared.data_root == new_root
    assert prepared.database_path == new_root / "database" / "portfolio.db"
    assert prepared.env_source == new_root / ".env"
    assert prepared.database_path.read_bytes().endswith(b"legacy")
    assert legacy_db.exists()


def test_prepare_profile_creates_owner_only_explicit_root(tmp_path, monkeypatch):
    _source_root, _outside = _source_profile(tmp_path, monkeypatch)
    isolated = tmp_path / "isolated"
    monkeypatch.setenv("FOLIOORB_DATA_DIR", str(isolated))

    profile = paths.prepare_runtime_profile()

    assert profile.data_root == isolated
    if os.name == "posix":
        assert isolated.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    "command",
    (
        ("-c", "from app.config import settings"),
        ("-c", "from app.services import backup_service; backup_service.apply_pending_restore()"),
        ("-c", "from app.services import backup_service; backup_service.list_backups()"),
        ("-c", "from app import app_settings; app_settings.save_settings({'x': 1})"),
        ("-c", "from app.services import launch_health; launch_health.record_launch_attempt()"),
        ("-c", "from app.services import update_downloader; update_downloader.pending_dir()"),
        ("-c", "from app.services import update_service; update_service.note_launch()"),
        ("-c", "from app.services import rollback_service; rollback_service.can_rollback()"),
        ("-c", "from app.services import update_log; update_log.event('profile probe')"),
        ("-c", "from app.services import macos_updater; macos_updater.consume_failed_marker()"),
        (
            "-c",
            "from app.services import api_key_store; api_key_store.save('sk-ant-' + 'x' * 20)",
        ),
        ("run.py",),
        ("desktop/main.py",),
    ),
)
def test_rejected_profile_is_zero_write_across_launch_boundaries(
    tmp_path, command
):
    profile_root = tmp_path / "profile"
    outside_db = tmp_path / "outside" / "portfolio.db"
    environment = os.environ.copy()
    environment.update(
        {
            "FOLIOORB_DATA_DIR": str(profile_root),
            "DATABASE_URL": f"sqlite:///{outside_db.as_posix()}",
            "ANTHROPIC_API_KEY": "",
        }
    )
    baseline = _tree(tmp_path)

    result = subprocess.run(
        (sys.executable, *command),
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    # update_service.note_launch deliberately swallows settings failures so an
    # update marker can never block startup; its required behavior here is still
    # zero writes. Every direct launcher/path boundary must surface the error.
    joined = " ".join(command)
    swallowed_marker_error = (
        "update_service.note_launch" in joined or "update_log.event" in joined
    )
    if not swallowed_marker_error:
        assert result.returncode != 0
        assert "same profile" in result.stderr or "stay inside" in result.stderr
    assert _tree(tmp_path) == baseline
    assert not profile_root.exists()
    assert not outside_db.parent.exists()
