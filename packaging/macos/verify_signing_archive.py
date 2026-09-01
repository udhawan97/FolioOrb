#!/usr/bin/env python3
"""Validate and extract the exact app archive accepted by the signing job."""

from __future__ import annotations

import argparse
import posixpath
import tarfile
from pathlib import Path, PurePosixPath


APP_ROOT = "FolioOrb.app"
MAX_MEMBERS = 10_000
MAX_TOTAL_FILE_BYTES = 2 * 1024 * 1024 * 1024


def _normalized_target(member_name: str, link_name: str) -> PurePosixPath:
    if PurePosixPath(link_name).is_absolute():
        raise ValueError(f"absolute link target: {member_name} -> {link_name}")
    target = posixpath.normpath(
        posixpath.join(posixpath.dirname(member_name), link_name)
    )
    return PurePosixPath(target)


def _validated_path(member: tarfile.TarInfo, names: set[str]) -> PurePosixPath:
    path = PurePosixPath(member.name)
    unsafe_part = any(part in ("", ".", "..") for part in path.parts)
    if path.is_absolute() or not path.parts or unsafe_part:
        raise ValueError(f"unsafe archive path: {member.name}")
    if path.parts[0] != APP_ROOT:
        raise ValueError(f"path outside {APP_ROOT}: {member.name}")
    if member.name in names:
        raise ValueError(f"duplicate archive path: {member.name}")
    names.add(member.name)
    return path


def _validated_file_size(member: tarfile.TarInfo) -> int:
    if member.isreg():
        if member.mode & 0o6000:
            raise ValueError(f"privileged file mode in archive: {member.name}")
        return member.size
    if member.isdir():
        return 0
    if member.issym():
        target = _normalized_target(member.name, member.linkname)
        if not target.parts or target.parts[0] != APP_ROOT:
            raise ValueError(
                f"link escapes {APP_ROOT}: {member.name} -> {member.linkname}"
            )
        return 0
    raise ValueError(f"unsupported archive member type: {member.name}")


def validate_members(members: list[tarfile.TarInfo]) -> None:
    """Reject paths or archive types that could escape the app bundle."""
    if not members or len(members) > MAX_MEMBERS:
        raise ValueError("signing archive has an invalid member count")

    names: set[str] = set()
    total_size = 0
    root_seen = False
    for member in members:
        path = _validated_path(member, names)
        root_seen = root_seen or (path == PurePosixPath(APP_ROOT) and member.isdir())
        total_size += _validated_file_size(member)

    if not root_seen:
        raise ValueError(f"archive does not contain the {APP_ROOT} directory")
    if total_size > MAX_TOTAL_FILE_BYTES:
        raise ValueError("signing archive expands beyond the size limit")


def validate_and_extract(archive: Path, destination: Path) -> Path:
    """Validate all metadata before using Python's hardened tar extraction."""
    destination.mkdir(parents=True, exist_ok=True)
    app_destination = destination / APP_ROOT
    if app_destination.exists() or app_destination.is_symlink():
        raise ValueError(f"refusing to replace existing {app_destination}")

    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        validate_members(members)
        bundle.extractall(destination, members=members, filter="data")
    if not app_destination.is_dir() or app_destination.is_symlink():
        raise ValueError("extracted signing input is not the exact app directory")
    return app_destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        validate_and_extract(args.archive, args.destination)
    except (OSError, tarfile.TarError, ValueError) as exc:
        parser.exit(1, f"Signing archive rejected: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
