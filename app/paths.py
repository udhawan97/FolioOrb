"""Filesystem locations that differ between a source checkout and a frozen app.

When FolioOrb runs from source, resources (``static/``, ``templates/``) and
writable data (``database/``, ``.env``) all live at the repo root, exactly as
before. When it runs as a PyInstaller-frozen desktop app, read-only resources
are unpacked into a temporary bundle directory while writable data must live in
the per-user application-data directory — an installed app must never write
inside its own install location (``/Applications/...`` or ``Program Files``).

This module depends only on the standard library plus ``platformdirs`` (already
a project dependency), so it is safe to import from ``config`` and ``database``
without creating an import cycle.
"""

import hashlib
import os
import secrets
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path

APP_NAME = "FolioOrb"

# The app shipped as "FolioSenseAI" before the FolioOrb rebrand. Existing frozen
# installs keep their database and ``.env`` under the old per-user data directory,
# so on first launch of a frozen FolioOrb we migrate that data forward (see
# ``_migrate_legacy_data``). Kept as a migration alias only — nothing new is ever
# written under this name.
LEGACY_APP_NAME = "FolioSenseAI"
_MIGRATION_MARKER = ".migrated-from-foliosenseai"
_MIGRATION_STAGING_SUFFIX = ".migrating-from-foliosenseai"
_CANONICAL_RELATIVE_DATABASE = Path("database/portfolio.db")


class ProfileConfigurationError(RuntimeError):
    """The configured database and writable data root do not form one profile."""


class ProfileMigrationAmbiguityError(ProfileConfigurationError):
    """Legacy and current profiles cannot be assigned ownership without user input."""


@dataclass(frozen=True)
class RuntimeProfile:
    """Validated ownership of every writable FolioOrb runtime artifact."""

    data_root: Path
    database_url: str
    database_path: Path | None
    env_source: Path
    frozen: bool
    explicit_data_root: bool


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def _source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _source_profile_override() -> Path | None:
    """Read the source installer's durable-profile pointer without writing."""
    pointer = _source_root() / ".source-profile-path"
    if not pointer.exists():
        return None
    if not pointer.is_file() or pointer.is_symlink():
        raise ProfileConfigurationError(".source-profile-path must be a regular file.")
    try:
        value = pointer.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProfileConfigurationError(".source-profile-path could not be read.") from exc
    configured = Path(value).expanduser() if value else Path()
    if not value or not configured.is_absolute():
        raise ProfileConfigurationError(
            ".source-profile-path must contain one absolute writable profile path."
        )
    return configured.resolve()


def _frozen_data_root() -> Path:
    from platformdirs import user_data_dir

    return Path(user_data_dir(APP_NAME, APP_NAME)).expanduser().resolve()


def _legacy_data_root() -> Path:
    from platformdirs import user_data_dir

    return Path(user_data_dir(LEGACY_APP_NAME, LEGACY_APP_NAME)).expanduser().resolve()


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (``static/``, ``templates/``).

    Frozen: PyInstaller unpacks ``datas`` under ``sys._MEIPASS``.
    Source: the repo root, one level above this ``app/`` package.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return _source_root()


def _migrate_legacy_data(new_dir: Path) -> None:
    """One-time copy of pre-rename FolioSenseAI data into the FolioOrb data dir.

    Frozen installs that predate the rebrand hold the user's portfolio database,
    ``.env``, update markers, and logs under the old ``FolioSenseAI`` per-user
    directory. The first time a frozen FolioOrb starts and finds no data of its
    own, copy the legacy tree across so nothing is lost — leaving the old
    directory untouched as a fallback. A marker file makes this idempotent and
    cheap (a single ``stat``) on every subsequent launch.
    """
    new_dir = Path(new_dir)
    marker = new_dir / _MIGRATION_MARKER
    if marker.is_file() and not marker.is_symlink():
        return
    if marker.exists() or marker.is_symlink():
        raise ProfileMigrationAmbiguityError(
            "The FolioOrb migration marker is not a regular file."
        )
    try:
        legacy_dir = _legacy_data_root()
    except Exception:  # pylint: disable=broad-except
        return
    if not legacy_dir.is_dir() or legacy_dir.resolve() == new_dir.resolve():
        return
    if not _migration_subset_matches(legacy_dir, legacy_dir):
        raise ProfileMigrationAmbiguityError(
            "The legacy profile contains a symlink or non-regular entry."
        )

    if not _migration_subset_matches(new_dir, legacy_dir):
        raise ProfileMigrationAmbiguityError(
            "FolioOrb and FolioSenseAI both contain data with ambiguous ownership; "
            "choose which profile to keep before relaunching."
        )

    staging = new_dir.parent / f".{new_dir.name}{_MIGRATION_STAGING_SUFFIX}"
    if staging.exists() and (staging.is_symlink() or not staging.is_dir()):
        raise ProfileMigrationAmbiguityError(
            "The legacy migration staging path is not an owned directory."
        )
    staging.mkdir(mode=0o700, parents=False, exist_ok=True)
    if os.name == "posix":
        staging.chmod(0o700)

    _copy_migration_tree(legacy_dir, staging)
    if not _migration_trees_match(legacy_dir, staging):
        raise OSError("Legacy profile staging verification failed")
    (staging / _MIGRATION_MARKER).write_text(
        f"migrated from {legacy_dir}\n", encoding="utf-8"
    )

    previous = new_dir.parent / (
        f".{new_dir.name}.migration-previous-{secrets.token_hex(6)}"
    )
    moved_previous = False
    try:
        new_dir.replace(previous)
        moved_previous = True
        staging.replace(new_dir)
    except OSError as forward_error:
        if moved_previous:
            _rollback_profile_publication(previous, new_dir, forward_error)
        raise

    try:
        shutil.rmtree(previous)
    except OSError:
        # The completed profile and legacy source remain canonical. A private
        # previous-directory copy is harmless and may aid manual recovery.
        pass
    _fsync_profile_parent(new_dir.parent)


def _migration_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _migration_subset_matches(candidate: Path, source: Path) -> bool:
    """Return whether every candidate entry is byte-identical legacy state."""
    for item in candidate.rglob("*"):
        if item.name == _MIGRATION_MARKER and item.parent == candidate:
            continue
        if item.is_symlink():
            return False
        relative = item.relative_to(candidate)
        original = source / relative
        if not original.exists() or original.is_symlink():
            return False
        if item.is_dir() != original.is_dir():
            return False
        if item.is_file():
            if not original.is_file() or _migration_digest(item) != _migration_digest(original):
                return False
        elif not item.is_dir():
            return False
    return True


def _migration_trees_match(source: Path, candidate: Path) -> bool:
    if not _migration_subset_matches(candidate, source):
        return False
    source_entries = {
        item.relative_to(source) for item in source.rglob("*")
    }
    candidate_entries = {
        item.relative_to(candidate)
        for item in candidate.rglob("*")
        if not (item.name == _MIGRATION_MARKER and item.parent == candidate)
    }
    return source_entries == candidate_entries


def _copy_migration_tree(source: Path, destination: Path) -> None:
    """Resume a private staging copy, overwriting only regular partial files."""
    for item in source.iterdir():
        if item.is_symlink():
            raise ProfileMigrationAmbiguityError(
                f"Legacy profile contains a symlink: {item.name}"
            )
        target = destination / item.name
        if item.is_dir():
            if target.exists() and (target.is_symlink() or not target.is_dir()):
                raise ProfileMigrationAmbiguityError(
                    f"Migration staging entry has ambiguous type: {item.name}"
                )
            target.mkdir(exist_ok=True)
            _copy_migration_tree(item, target)
        elif item.is_file():
            if target.exists() and (target.is_symlink() or not target.is_file()):
                raise ProfileMigrationAmbiguityError(
                    f"Migration staging entry has ambiguous type: {item.name}"
                )
            shutil.copy2(item, target)
        else:
            raise ProfileMigrationAmbiguityError(
                f"Legacy profile entry is not a regular file or directory: {item.name}"
            )


def _rollback_profile_publication(
    previous: Path, new_dir: Path, forward_error: OSError
) -> None:
    """Republish the previous canonical root after a staging rename failure."""
    try:
        previous.replace(new_dir)
    except OSError:
        try:
            shutil.copytree(previous, new_dir)
        except OSError as copy_error:
            raise ProfileConfigurationError(
                "Legacy migration failed and the previous FolioOrb root could not "
                "be republished automatically."
            ) from copy_error
    _fsync_profile_parent(new_dir.parent)
    if not new_dir.is_dir():
        raise ProfileConfigurationError(
            "Legacy migration failed without a readable FolioOrb profile root."
        ) from forward_error


def _fsync_profile_parent(parent: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    except OSError:
        # No power-loss safety claim is made for this best-effort migration.
        pass
    finally:
        os.close(descriptor)


def _prospective_env_source(data_root: Path, frozen: bool, explicit: bool) -> Path:
    """Choose the dotenv file that phase two would make active, without writing."""
    current = data_root / ".env"
    if current.exists() or not frozen or explicit:
        return current

    # A default frozen launch migrates the legacy tree only when FolioOrb has no
    # database or .env of its own. Inspect that source now so its DATABASE_URL is
    # validated before the first migration marker, directory, or copied byte.
    if (data_root / "database" / "portfolio.db").exists():
        return current
    legacy = _legacy_data_root() / ".env"
    return legacy if legacy.exists() else current


def _dotenv_database_url(env_path: Path) -> str | None:
    if not env_path.is_file():
        return None
    from dotenv import dotenv_values

    value = dotenv_values(env_path).get("DATABASE_URL")
    return str(value).strip() if value else None


def _sqlite_profile_database(
    raw_url: str,
    data_root: Path,
    *,
    explicit_data_root: bool,
) -> tuple[str, Path | None]:
    """Normalize one supported SQLite URL and enforce profile containment."""
    prefix = "sqlite:///"
    if not raw_url.startswith(prefix):
        raise ProfileConfigurationError(
            "FolioOrb supports a local SQLite DATABASE_URL; configure a sqlite:/// URL."
        )

    database_value = raw_url[len(prefix) :]
    if database_value == ":memory:":
        return raw_url, None
    if not database_value or "?" in database_value or "#" in database_value:
        raise ProfileConfigurationError("DATABASE_URL must identify one local SQLite file.")

    configured = Path(database_value).expanduser()
    if configured.is_absolute():
        database_path = configured.resolve()
    else:
        relative = Path(os.path.normpath(database_value))
        if not explicit_data_root and relative != _CANONICAL_RELATIVE_DATABASE:
            raise ProfileConfigurationError(
                "A non-default database needs an explicit FOLIOORB_DATA_DIR so "
                "backups, settings, updates, and the database share the same profile."
            )
        database_path = (data_root / relative).resolve()

    if (
        not explicit_data_root
        and database_path != (data_root / _CANONICAL_RELATIVE_DATABASE).resolve()
    ):
        raise ProfileConfigurationError(
            "A non-default database needs an explicit FOLIOORB_DATA_DIR so "
            "backups, settings, updates, and the database share the same profile."
        )

    if database_path == data_root or database_path.is_dir():
        raise ProfileConfigurationError(
            "DATABASE_URL must identify a SQLite file inside FOLIOORB_DATA_DIR, "
            "not the profile directory itself."
        )

    try:
        database_path.relative_to(data_root)
    except ValueError as exc:
        raise ProfileConfigurationError(
            "DATABASE_URL must stay inside FOLIOORB_DATA_DIR so every writable "
            "artifact belongs to the same profile."
        ) from exc

    return f"sqlite:///{database_path.as_posix()}", database_path


def resolve_runtime_profile() -> RuntimeProfile:
    """Resolve and validate the effective writable profile without side effects.

    Process environment values retain dotenv precedence. A data-root override by
    itself derives the canonical database inside that root. The historical source
    ``sqlite:///./database/portfolio.db`` remains valid and is normalized against
    the source root rather than the caller's working directory.
    """
    environment_override = os.getenv("FOLIOORB_DATA_DIR", "").strip()
    frozen = is_frozen()
    pointer_override = None if frozen or environment_override else _source_profile_override()
    explicit = bool(environment_override or pointer_override)
    if environment_override:
        root = Path(environment_override).expanduser().resolve()
    elif pointer_override:
        root = pointer_override
    else:
        root = _frozen_data_root() if frozen else _source_root().resolve()

    env_source = _prospective_env_source(root, frozen, explicit)
    if "DATABASE_URL" in os.environ:
        configured_url = os.environ.get("DATABASE_URL", "").strip() or None
    else:
        configured_url = _dotenv_database_url(env_source)

    if configured_url is None:
        database_path = root / _CANONICAL_RELATIVE_DATABASE
        database_url = f"sqlite:///{database_path.as_posix()}"
    else:
        database_url, database_path = _sqlite_profile_database(
            configured_url,
            root,
            explicit_data_root=explicit,
        )

    return RuntimeProfile(
        data_root=root,
        database_url=database_url,
        database_path=database_path,
        env_source=env_source,
        frozen=frozen,
        explicit_data_root=explicit,
    )


def prepare_runtime_profile() -> RuntimeProfile:
    """Validate first, then create/migrate the one owned writable profile."""
    profile = resolve_runtime_profile()
    existed = profile.data_root.exists()
    profile.data_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not existed:
        try:
            profile.data_root.chmod(0o700)
        except OSError:
            pass

    if profile.frozen and not profile.explicit_data_root:
        _migrate_legacy_data(profile.data_root)

    active_env = profile.data_root / ".env"
    if profile.env_source != active_env and not active_env.is_file():
        raise ProfileConfigurationError(
            "The legacy FolioOrb profile was valid but its .env could not be copied."
        )
    return replace(profile, env_source=active_env)


def data_dir() -> Path:
    """Writable root after the database and data ownership contract is validated."""
    return prepare_runtime_profile().data_root
