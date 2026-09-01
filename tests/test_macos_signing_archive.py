"""Executable hostile-archive contracts for the protected macOS signer."""

import io
import importlib.util
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_signing_archive",
    ROOT / "packaging/macos/verify_signing_archive.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
validate_and_extract = MODULE.validate_and_extract


def _archive(path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> Path:
    with tarfile.open(path, "w:gz") as bundle:
        for info, payload in members:
            bundle.addfile(info, io.BytesIO(payload) if info.isreg() else None)
    return path


def _dir(name: str) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    return info, b""


def _file(name: str, payload: bytes = b"safe") -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    return info, payload


def _symlink(name: str, target: str) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    info.mode = 0o777
    return info, b""


def test_validator_extracts_contained_app_and_relative_link(tmp_path):
    archive = _archive(
        tmp_path / "safe.tar.gz",
        [
            _dir("FolioOrb.app"),
            _dir("FolioOrb.app/Contents"),
            _dir("FolioOrb.app/Contents/Resources"),
            _file("FolioOrb.app/Contents/Resources/value.txt"),
            _symlink("FolioOrb.app/Contents/value.txt", "Resources/value.txt"),
        ],
    )

    app = validate_and_extract(archive, tmp_path / "out")

    assert (app / "Contents/value.txt").read_bytes() == b"safe"


@pytest.mark.parametrize(
    "member",
    [
        _file("FolioOrb.app/../../outside"),
        _file("/FolioOrb.app/Contents/outside"),
        _file("Other.app/Contents/file"),
        _symlink("FolioOrb.app/Contents/escape", "../../outside"),
        _symlink("FolioOrb.app/Contents/absolute", "/tmp/outside"),
    ],
)
def test_validator_rejects_escape_paths_and_links(tmp_path, member):
    archive = _archive(tmp_path / "hostile.tar.gz", [_dir("FolioOrb.app"), member])

    with pytest.raises(ValueError):
        validate_and_extract(archive, tmp_path / "out")


def test_validator_rejects_special_files(tmp_path):
    fifo = tarfile.TarInfo("FolioOrb.app/Contents/fifo")
    fifo.type = tarfile.FIFOTYPE
    archive = _archive(tmp_path / "fifo.tar.gz", [_dir("FolioOrb.app"), (fifo, b"")])

    with pytest.raises(ValueError, match="unsupported archive member type"):
        validate_and_extract(archive, tmp_path / "out")
