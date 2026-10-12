"""Contracts for reproducible macOS and Windows packaging environments."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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
        blocks = re.split(r"(?=^[a-z0-9])", lock, flags=re.MULTILINE)[1:]
        assert all(re.search(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)", block)
                   for block in blocks)
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
    assert "UPGRADE_ARGS=(--upgrade)" in script
    assert script.count('${UPGRADE_ARGS[@]+"${UPGRADE_ARGS[@]}"}') == 3
    assert script.count("--generate-hashes") == 3
    assert "--python-platform x86_64-manylinux_2_17" in script
    assert 'UV_CUSTOM_COMPILE_COMMAND="scripts/lock_desktop_dependencies.sh"' in script


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None,
                    reason="Lock generator runs on Unix CI with Bash")
@pytest.mark.parametrize("mode", ["check", "version-drift", "hash-drift", "refresh"])
def test_lock_check_preserves_resolutions_and_detects_drift(tmp_path, mode):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "lock_desktop_dependencies.sh"
    script.write_text(_text("scripts/lock_desktop_dependencies.sh"), encoding="utf-8")
    locks = (
        "requirements-desktop-macos.lock",
        "requirements-release-test-linux.lock",
        "requirements-desktop-windows.lock",
    )
    committed = "urllib3==2.8.0 \\\n    --hash=sha256:expected\n"
    for lock in locks:
        (repo / lock).write_text(committed, encoding="utf-8")
    log = tmp_path / "calls.jsonl"
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "output = pathlib.Path(args[args.index('--output-file') + 1])\n"
        "seed = output.read_text() if output.exists() else None\n"
        "with open(os.environ['UV_CALL_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(json.dumps({'args': args, 'seed': seed, 'output': str(output)}) + '\\n')\n"
        "content = os.environ['EXPECTED_LOCK']\n"
        "if os.environ['LOCK_MODE'] == 'version-drift':\n"
        "    content = content.replace('2.8.0', '2.9.0')\n"
        "if os.environ['LOCK_MODE'] == 'hash-drift':\n"
        "    content = content.replace('sha256:expected', 'sha256:different')\n"
        "output.write_text(content)\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    args = ["--check"] if mode != "refresh" else [str(tmp_path / "output")]
    result = subprocess.run(
        ["bash", str(script), *args],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
             "UV_CALL_LOG": str(log), "LOCK_MODE": mode, "EXPECTED_LOCK": committed},
        capture_output=True, text=True, check=False,
    )
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 3
    assert result.returncode == (1 if mode.endswith("drift") else 0)
    for call in calls:
        assert ("--upgrade" in call["args"]) == (mode == "refresh")
        assert call["seed"] == (None if mode == "refresh" else "urllib3==2.8.0\n")
        if mode != "refresh":
            assert not Path(call["output"]).exists()
    assert all((repo / lock).read_text(encoding="utf-8") == committed
               for lock in locks)


def test_ci_checks_committed_locks_and_audits_all_dependencies():
    workflow = _text(".github/workflows/ci.yml")
    assert "scripts/lock_desktop_dependencies.sh --check" in workflow
    assert "pip-audit -r requirements.txt" in workflow
    for lock in ("requirements-desktop-macos.lock", "requirements-release-test-linux.lock",
                 "requirements-desktop-windows.lock"):
        assert f"pip-audit --no-deps --disable-pip -r {lock}" in workflow


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
