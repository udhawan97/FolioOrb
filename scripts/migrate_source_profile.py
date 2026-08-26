#!/usr/bin/env python3
"""Safely migrate a legacy source install's writable FolioOrb profile.

The one-line installers replace their source tree during an update. Older
versions also used that tree as the writable profile, so replacement must first
move every owned runtime artifact to a durable directory outside the code tree.
The original install is retained separately by the calling installer as a
recovery copy.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path


PROFILE_ENTRIES = (
    ".env",
    ".folioorb-backup-operation.lock",
    "backup-policy.json",
    "backups",
    "database",
    "launch-health.txt",
    "logs",
    "settings.json",
    "updates",
)
PROFILE_MARKER = ".source-profile-v1"
DATABASE_NAME = "portfolio.db"
DATABASE_URL_PREFIX = "sqlite:///"


def _dotenv_database_url(env_path: Path) -> str | None:
    """Read DATABASE_URL without importing FolioOrb's not-yet-installed deps."""
    if not env_path.is_file():
        return None
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "DATABASE_URL":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _legacy_database(source: Path) -> tuple[Path, str, bool]:
    process_url = os.getenv("DATABASE_URL", "").strip()
    raw_url = process_url
    if not process_url:
        raw_url = _dotenv_database_url(source / ".env") or (
            f"{DATABASE_URL_PREFIX}./database/{DATABASE_NAME}"
        )
    if not raw_url.startswith(DATABASE_URL_PREFIX):
        raise RuntimeError("legacy DATABASE_URL must use local SQLite")
    value = raw_url[len(DATABASE_URL_PREFIX) :]
    if not value or value == ":memory:" or "?" in value or "#" in value:
        raise RuntimeError("legacy DATABASE_URL must identify one SQLite file")
    configured = Path(value).expanduser()
    if configured.is_absolute():
        raise RuntimeError(
            "absolute legacy DATABASE_URL cannot be migrated automatically; "
            "move it inside the source profile or migrate it manually"
        )
    relative = Path(os.path.normpath(value))
    database = (source / relative).resolve()
    try:
        database.relative_to(source)
    except ValueError as exc:
        raise RuntimeError("legacy DATABASE_URL escapes the source profile") from exc
    normalized_url = f"{DATABASE_URL_PREFIX}./{relative.as_posix()}"
    return database, normalized_url, bool(process_url)


def _contains_legacy_profile(source: Path, database: Path) -> bool:
    if database.is_file():
        return True
    for name in PROFILE_ENTRIES:
        entry = source / name
        if name == "database" and entry.is_dir():
            if any(child.name != ".gitkeep" for child in entry.iterdir()):
                return True
            continue
        if entry.exists():
            return True
    return False


def _reject_symlinks(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"profile entry is a symlink: {path}")
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_symlink():
                raise RuntimeError(f"profile entry contains a symlink: {child}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_regular_entry(source: Path, destination: Path) -> None:
    _reject_symlinks(source)
    if source.is_dir():
        shutil.copytree(source, destination)
        for copied in destination.rglob("*"):
            if copied.is_file():
                original = source / copied.relative_to(destination)
                if _sha256(original) != _sha256(copied):
                    raise RuntimeError(f"profile copy verification failed: {original}")
        return
    shutil.copy2(source, destination)
    if _sha256(source) != _sha256(destination):
        raise RuntimeError(f"profile copy verification failed: {source}")


def _copy_tree_excluding(source: Path, destination: Path, excluded: set[Path]) -> None:
    """Copy a profile tree while omitting an active SQLite database and sidecars."""
    _reject_symlinks(source)
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        resolved = child.resolve()
        if resolved in excluded:
            continue
        target = destination / child.name
        if child.is_dir():
            _copy_tree_excluding(child, target, excluded)
        else:
            _copy_regular_entry(child, target)


def _backup_database(live_database: Path, migrated_database: Path) -> None:
    """Create a transactionally consistent copy, including committed WAL data."""
    migrated_database.parent.mkdir(parents=True, exist_ok=True)
    uri = f"{live_database.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as source_connection:
        with sqlite3.connect(migrated_database) as destination_connection:
            source_connection.backup(destination_connection)
            result = destination_connection.execute("PRAGMA quick_check").fetchone()
    if result != ("ok",):
        raise RuntimeError("migrated portfolio database failed SQLite quick_check")


def _persist_database_url(env_path: Path, database_url: str) -> None:
    """Make a process-selected database durable for the next source launch."""
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    rewritten: list[str] = []
    found = False
    for line in lines:
        candidate = line.strip()
        if candidate.startswith("export "):
            candidate = candidate.removeprefix("export ").lstrip()
        if candidate.split("=", 1)[0].strip() == "DATABASE_URL" and "=" in candidate:
            rewritten.append(f"DATABASE_URL={database_url}")
            found = True
        else:
            rewritten.append(line)
    if not found:
        rewritten.append(f"DATABASE_URL={database_url}")
    env_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def _existing_destination_status(
    destination: Path, *, has_legacy_profile: bool
) -> str | None:
    """Adopt an existing durable profile or reject an ambiguous split profile."""
    marker = destination / PROFILE_MARKER
    if marker.is_file():
        if has_legacy_profile:
            raise RuntimeError(
                "both the legacy install and durable profile contain data; "
                "refusing to choose or overwrite either"
            )
        return "READY"
    if destination.exists() and any(destination.iterdir()):
        if has_legacy_profile:
            raise RuntimeError(
                "both the legacy install and durable profile contain data; "
                "refusing to choose or overwrite either"
            )
        marker.write_text("adopted existing external profile\n", encoding="utf-8")
        return "READY"
    return None


def migrate(source: Path, destination: Path) -> str:
    """Migrate a legacy profile and return ``MIGRATED`` or ``READY``."""
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if destination == source or source in destination.parents:
        raise RuntimeError("durable profile directory must be outside the source install")

    database, effective_database_url, persist_process_url = _legacy_database(source)
    has_legacy_profile = source.is_dir() and _contains_legacy_profile(source, database)
    destination_status = _existing_destination_status(
        destination, has_legacy_profile=has_legacy_profile
    )
    if destination_status:
        return destination_status

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.migration-", dir=destination.parent)
    )
    try:
        if has_legacy_profile:
            if not database.is_file():
                raise RuntimeError(
                    f"configured legacy database is missing: {database}; "
                    "refusing to replace the source install"
                )
            excluded = {
                database,
                Path(f"{database}-wal"),
                Path(f"{database}-shm"),
            }
            for name in PROFILE_ENTRIES:
                entry = source / name
                if not entry.exists():
                    continue
                target = staging / name
                if entry.is_dir():
                    _copy_tree_excluding(entry, target, excluded)
                else:
                    _copy_regular_entry(entry, target)
            database_relative = database.relative_to(source)
            _backup_database(database, staging / database_relative)
            if persist_process_url:
                _persist_database_url(staging / ".env", effective_database_url)
        marker_text = (
            "migrated legacy source profile\n" if has_legacy_profile else "fresh profile\n"
        )
        (staging / PROFILE_MARKER).write_text(marker_text, encoding="utf-8")
        try:
            staging.chmod(0o700)
        except OSError:
            pass

        if destination.exists():
            destination.rmdir()
        # The paths share one parent, so rename is atomic. Unlike os.replace,
        # it also supports directory moves on Windows (MoveFileEx with
        # REPLACE_EXISTING returns WinError 5 even when the target is absent).
        os.rename(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return "MIGRATED" if has_legacy_profile else "READY"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(migrate(args.source, args.destination))
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"Profile migration failed safely: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
