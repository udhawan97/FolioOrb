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

import os
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
_CANONICAL_RELATIVE_DATABASE = Path("database/portfolio.db")


class ProfileConfigurationError(RuntimeError):
    """The configured database and writable data root do not form one profile."""


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
    marker = new_dir / _MIGRATION_MARKER
    if marker.exists():
        return
    # If FolioOrb already has its own data, never overwrite it — just record that
    # the legacy scan is done so we don't repeat it on later launches.
    if (new_dir / ".env").exists() or (new_dir / "database" / "portfolio.db").exists():
        try:
            marker.write_text("skipped: folioorb data already present\n", encoding="utf-8")
        except OSError:
            pass
        return
    try:
        legacy_dir = _legacy_data_root()
    except Exception:  # pylint: disable=broad-except
        return
    if not legacy_dir.is_dir() or legacy_dir.resolve() == new_dir.resolve():
        return
    try:
        for item in legacy_dir.iterdir():
            dest = new_dir / item.name
            if dest.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        marker.write_text(f"migrated from {legacy_dir}\n", encoding="utf-8")
    except OSError:
        # A partial copy still beats losing the data; never crash startup on it.
        pass


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
