"""Contracts for reproducible macOS and Windows packaging environments."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_platform_locks_are_fully_pinned_and_hash_checked():
    for relative in (
        "requirements-desktop-macos.lock",
        "requirements-release-test-linux.lock",
        "requirements-desktop-windows.lock",
    ):
        lock = _text(relative)
        requirements = [line for line in lock.splitlines() if re.match(r"^[a-z0-9]", line)]
        assert requirements
        assert all("==" in line for line in requirements)
        assert lock.count("--hash=sha256:") >= len(requirements)
        if relative != "requirements-release-test-linux.lock":
            assert "pyinstaller==" in lock
            assert "pywebview==" in lock
        else:
            assert "pytest==" in lock


def test_lock_generator_targets_the_release_platforms():
    script = _text("scripts/lock_desktop_dependencies.sh")

    assert "requirements.txt requirements-desktop.txt" in script
    assert "requirements-desktop.txt requirements-release-test.txt" in script
    assert "--python-platform aarch64-apple-darwin" in script
    assert "--python-platform x86_64-pc-windows-msvc" in script
    assert script.count("--generate-hashes") == 3
    assert "--python-platform x86_64-manylinux_2_17" in script
    assert 'UV_CUSTOM_COMPILE_COMMAND="scripts/lock_desktop_dependencies.sh"' in script


def test_release_installs_only_the_matching_hash_checked_lock():
    workflow = _text(".github/workflows/release.yml")

    assert "pip install --require-hashes -r requirements-desktop-macos.lock" in workflow
    assert "pip install --require-hashes -r requirements-release-test-linux.lock" in workflow
    assert "pip install --require-hashes -r requirements-desktop-windows.lock" in workflow
    assert "python -m pip install pytest" not in workflow
    assert "pip install --upgrade pip" not in workflow
    assert "pip install -r requirements.txt -r requirements-desktop.txt" not in workflow
    assert "pip-audit --no-deps --disable-pip -r requirements-desktop-macos.lock" in _text(
        ".github/workflows/ci.yml"
    )
