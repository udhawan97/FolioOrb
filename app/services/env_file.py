"""Owner-only, atomic writes for FolioOrb's local plaintext environment file."""

from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
from pathlib import Path


class EnvFileSecurityError(OSError):
    """The environment target does not belong to the current local profile owner."""


_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_OWNER_ONLY_MODE = stat.S_IRUSR | stat.S_IWUSR


def _assert_owner(path: Path, metadata: os.stat_result) -> None:
    if os.name == "posix" and metadata.st_uid != os.geteuid():
        raise EnvFileSecurityError(f"Refusing environment file not owned by this user: {path}")


def _open_target(path: Path) -> tuple[int | None, tuple[int, int] | None]:
    """Open one regular, owned target without following a final-component symlink."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None, None
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise EnvFileSecurityError(f"Environment target must be a regular file: {path}")
    _assert_owner(path, metadata)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise EnvFileSecurityError(f"Environment target must be a regular file: {path}")
        _assert_owner(path, opened)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise EnvFileSecurityError("Environment target changed while it was being opened")
    except OSError:
        os.close(descriptor)
        raise
    return descriptor, (metadata.st_dev, metadata.st_ino)


def _read_target(path: Path) -> tuple[str, tuple[int, int] | None]:
    """Read one regular, owned target without following a final-component symlink."""
    descriptor, identity = _open_target(path)
    if descriptor is None:
        return "", None
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            content = handle.read()
    finally:
        os.close(descriptor)
    return content, identity


def _assert_unchanged(path: Path, identity: tuple[int, int] | None) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if identity is None:
            return
        raise EnvFileSecurityError("Environment target disappeared during update") from None
    if identity is None:
        raise EnvFileSecurityError("Environment target appeared during update")
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise EnvFileSecurityError(f"Environment target must be a regular file: {path}")
    _assert_owner(path, metadata)
    if (metadata.st_dev, metadata.st_ino) != identity:
        raise EnvFileSecurityError("Environment target changed during update")


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _restrict_owner_only(descriptor: int, path: Path) -> None:
    """Apply the strongest portable owner-only mode to an opened file."""
    if os.name == "posix":
        os.fchmod(descriptor, _OWNER_ONLY_MODE)
        return
    # chmod is not a Windows ACL guarantee; it only preserves functional parity
    # while Windows ACL enforcement remains an explicit research item.
    os.chmod(path, _OWNER_ONLY_MODE)


def secure_existing_env(path: Path) -> None:
    """Validate and retighten an existing environment file without reading its content."""
    path = Path(path)
    descriptor, identity = _open_target(path)
    if descriptor is None:
        raise FileNotFoundError(path)
    try:
        _restrict_owner_only(descriptor, path)
        secured = os.fstat(descriptor)
        if os.name == "posix" and stat.S_IMODE(secured.st_mode) != _OWNER_ONLY_MODE:
            raise EnvFileSecurityError(f"Environment target is not owner-only: {path}")
        _assert_unchanged(path, identity)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: str, identity: tuple[int, int] | None) -> None:
    """Publish complete UTF-8 content from a 0600 sibling or leave target unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        _restrict_owner_only(descriptor, temporary)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _assert_unchanged(path, identity)
        os.replace(temporary, path)
        try:
            _fsync_directory(path.parent)
        except OSError:
            # The complete, file-fsynced replacement is already visible. Do not
            # report a failed save and leave the live client disagreeing with it.
            pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def update_env_key(path: Path, key: str, value: str) -> None:
    """Replace all occurrences of ``key`` with one canonical owner-only line."""
    if not _KEY_PATTERN.fullmatch(key):
        raise ValueError("Environment key name is invalid")
    if any(character in value for character in "\r\n\0"):
        raise ValueError("Environment value must fit on one line")

    path = Path(path)
    existing, identity = _read_target(path)
    lines = existing.splitlines(keepends=True)
    owned_line = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
    canonical = f"{key}={value}\n"
    rewritten: list[str] = []
    inserted = False
    for line in lines:
        if owned_line.match(line):
            if not inserted:
                rewritten.append(canonical)
                inserted = True
            continue
        rewritten.append(line)
    if not inserted:
        if rewritten and not rewritten[-1].endswith(("\n", "\r")):
            rewritten[-1] += "\n"
        rewritten.append(canonical)
    _atomic_write(path, "".join(rewritten), identity)


def initialize_profile_env(path: Path, api_key: str, secret_key: str) -> None:
    """Create source-setup defaults without ever publishing broadly readable secrets."""
    for value in (api_key, secret_key):
        if any(character in value for character in "\r\n\0"):
            raise ValueError("Environment value must fit on one line")
    path = Path(path)
    _existing, identity = _read_target(path)
    if identity is not None:
        raise FileExistsError(path)
    content = (
        f"ANTHROPIC_API_KEY={api_key}\n"
        f"SECRET_KEY={secret_key}\n"
        "DEBUG=True\n"
        "DATABASE_URL=sqlite:///./database/portfolio.db\n"
        "CORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000\n"
        "DEFAULT_HOLDINGS=\n"
    )
    _atomic_write(path, content, None)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Create a private FolioOrb source profile")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--set-secret", action="store_true")
    operation.add_argument("--secure-existing", action="store_true")
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args()
    if arguments.secure_existing:
        secure_existing_env(arguments.path)
        return 0
    if arguments.set_secret:
        update_env_key(
            arguments.path,
            "SECRET_KEY",
            os.environ["FOLIOORB_SETUP_SECRET_KEY"],
        )
        return 0
    initialize_profile_env(
        arguments.path,
        os.environ.get("FOLIOORB_SETUP_API_KEY", ""),
        os.environ["FOLIOORB_SETUP_SECRET_KEY"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
