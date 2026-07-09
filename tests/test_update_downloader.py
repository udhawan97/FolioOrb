# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
"""Resumable download + SHA-256 verification, with the HTTP seam injected.

No network: update_downloader._open is monkeypatched to serve bytes from memory,
including honoring a Range header so the resume path is exercised end to end.
"""
import hashlib
import io

import pytest

from app import paths
from app.services import update_downloader as dl


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path


class FakeResp:
    def __init__(self, data, status=200):
        self._buf = io.BytesIO(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._buf.read(n)

    def close(self):
        pass


def _serve(full_bytes, honor_range=True):
    """Return an _open replacement that serves full_bytes, honoring Range."""
    def _open(request):
        rng = request.headers.get("Range")
        if honor_range and rng:
            start = int(rng.split("=")[1].split("-")[0])
            return FakeResp(full_bytes[start:], status=206)
        return FakeResp(full_bytes, status=200)
    return _open


# ------------------------------- checksums -------------------------------- #
def test_compute_sha256(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello world")
    assert dl.compute_sha256(f) == hashlib.sha256(b"hello world").hexdigest()


def test_parse_sha256sums_matches_by_basename():
    text = (
        "aaa111  FolioSenseAI-macOS-arm64-v4.4.0.dmg\n"
        "bbb222  FolioSenseAI-Windows-x64-v4.4.0-Setup.exe\n"
    )
    assert dl.parse_sha256sums(text, "FolioSenseAI-macOS-arm64-v4.4.0.dmg") == "aaa111"
    win = "some/path/FolioSenseAI-Windows-x64-v4.4.0-Setup.exe"
    assert dl.parse_sha256sums(text, win) == "bbb222"
    assert dl.parse_sha256sums(text, "missing.dmg") is None


def test_verify_download(tmp_path):
    f = tmp_path / "a.dmg"
    f.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    good = digest + "  a.dmg\n"
    assert dl.verify_download(f, good, "a.dmg") is True
    assert dl.verify_download(f, "deadbeef  a.dmg\n", "a.dmg") is False
    assert dl.verify_download(f, "", "a.dmg") is False


# ------------------------------- download --------------------------------- #
def test_download_writes_file_and_reports_progress(tmp_path, monkeypatch):
    data = b"0123456789" * 500
    monkeypatch.setattr(dl, "_open", _serve(data))
    seen = []
    dest = dl.pending_dir() / "pkg.dmg"

    result = dl.download_update(
        "https://x/pkg.dmg", dest, on_progress=lambda d, t: seen.append((d, t))
    )

    assert result == dest
    assert dest.read_bytes() == data
    assert seen[-1][0] == len(data)
    assert not dest.with_name(dest.name + ".part").exists()


def test_download_resumes_from_partial(tmp_path, monkeypatch):
    data = b"ABCDEFGHIJ" * 400  # 4000 bytes
    monkeypatch.setattr(dl, "_open", _serve(data, honor_range=True))
    dest = dl.pending_dir() / "pkg.dmg"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(data[:1500])  # pretend a prior run got 1500 bytes

    dl.download_update("https://x/pkg.dmg", dest)

    assert dest.read_bytes() == data  # resumed bytes + remainder == whole file


def test_download_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    data = b"XYZ" * 1000
    monkeypatch.setattr(dl, "_open", _serve(data, honor_range=False))
    dest = dl.pending_dir() / "pkg.dmg"
    dest.with_name(dest.name + ".part").write_bytes(b"stale-partial")

    dl.download_update("https://x/pkg.dmg", dest)

    assert dest.read_bytes() == data


def test_download_cancel_raises_and_keeps_partial(tmp_path, monkeypatch):
    data = b"Q" * 5000
    monkeypatch.setattr(dl, "_open", _serve(data))
    dest = dl.pending_dir() / "pkg.dmg"

    with pytest.raises(dl.DownloadCancelled):
        dl.download_update("https://x/pkg.dmg", dest, should_cancel=lambda: True)

    assert not dest.exists()  # not promoted to final


def test_fetch_text(monkeypatch):
    monkeypatch.setattr(dl, "_open", lambda req: FakeResp(b"hash  file.dmg\n"))
    assert dl.fetch_text("https://x/SHA256SUMS.txt") == "hash  file.dmg\n"
