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

import shutil
import sys
from pathlib import Path

APP_NAME = "FolioOrb"

# The app shipped as "FolioSenseAI" before the FolioOrb rebrand. Existing frozen
# installs keep their database and ``.env`` under the old per-user data directory,
# so on first launch of a frozen FolioOrb we migrate that data forward (see
# ``_migrate_legacy_data``). Kept as a migration alias only — nothing new is ever
# written under this name.
LEGACY_APP_NAME = "FolioSenseAI"
_MIGRATION_MARKER = ".migrated-from-foliosenseai"


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (``static/``, ``templates/``).

    Frozen: PyInstaller unpacks ``datas`` under ``sys._MEIPASS``.
    Source: the repo root, one level above this ``app/`` package.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


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
        from platformdirs import user_data_dir

        legacy_dir = Path(user_data_dir(LEGACY_APP_NAME, LEGACY_APP_NAME))
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


def data_dir() -> Path:
    """Writable directory for the database and ``.env``.

    Frozen: the OS per-user data directory (created on first run), with any
    pre-rename FolioSenseAI data migrated in once.
    Source: the repo root, so source runs keep writing ``./database`` and
    ``./.env`` exactly as they always have.
    """
    if is_frozen():
        from platformdirs import user_data_dir

        directory = Path(user_data_dir(APP_NAME, APP_NAME))
        directory.mkdir(parents=True, exist_ok=True)
        _migrate_legacy_data(directory)
    else:
        directory = Path(__file__).resolve().parent.parent
        directory.mkdir(parents=True, exist_ok=True)
    return directory
