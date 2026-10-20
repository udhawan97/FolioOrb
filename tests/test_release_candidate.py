"""Behavioral contracts for acceptance-bound publication."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_candidate", ROOT / "packaging/release_candidate.py"
)
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


@pytest.fixture(name="release_env")
def _release_env(monkeypatch):
    values = {
        "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
        "ASSET_TOKEN": "main-aaaaaaa", "APP_VERSION": "5.16.1", "CHANNEL": "dev",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


@pytest.fixture(name="staged")
def _staged(tmp_path, release_env):  # pylint: disable=unused-argument
    inputs = tmp_path / "inputs"
    names = candidate.installer_names(candidate.identity())
    for platform, name in zip(("macos", "windows"), names):
        folder = inputs / platform
        folder.mkdir(parents=True)
        (folder / name).write_bytes(f"fictional {platform} installer".encode())
        (folder / f"{platform}-SOURCE-SHA.txt").write_text("a" * 40 + "\n")
        (folder / f"{platform}-SHA256SUMS.txt").write_text(
            f"{candidate.sha256(folder / name)}  {name}\n"
        )
    output = tmp_path / "candidate"
    digest = candidate.prepare(inputs, output)
    return inputs, output, digest


def test_candidate_roundtrip_preserves_installer_bytes_and_checksums(staged):
    inputs, output, digest = staged
    meta = candidate.verify(output, digest)
    for platform, name in zip(("macos", "windows"), candidate.installer_names(meta)):
        assert (inputs / platform / name).read_bytes() == (output / name).read_bytes()
    assert len(list(output.iterdir())) == 4


@pytest.mark.parametrize("fault", [
    "bytes", "missing", "extra", "symlink", "checksum", "manifest", "digest", "empty",
])
def test_changed_candidate_fails_closed(staged, fault):
    _, output, digest = staged
    installer = output / candidate.installer_names(candidate.identity())[0]
    if fault == "bytes":
        installer.write_bytes(b"changed")
    elif fault == "missing":
        installer.unlink()
    elif fault == "extra":
        (output / "unexpected.exe").write_bytes(b"extra")
    elif fault == "symlink":
        installer.unlink()
        installer.symlink_to(output / "SHA256SUMS.txt")
    elif fault == "checksum":
        (output / "SHA256SUMS.txt").write_text("invented")
    elif fault == "manifest":
        (output / "candidate.json").write_text("{}")
    elif fault == "digest":
        digest = "b" * 64
    else:
        installer.write_bytes(b"")
    with pytest.raises(ValueError):
        candidate.verify(output, digest)


@pytest.mark.parametrize("field,value", [
    ("GITHUB_SHA", "b" * 40), ("GITHUB_RUN_ID", "456"),
    ("GITHUB_RUN_ATTEMPT", "2"), ("APP_VERSION", "5.16.2"),
])
def test_inherited_stage_outputs_cannot_authorize_changed_runtime(
    staged, monkeypatch, field, value
):
    _, output, digest = staged
    monkeypatch.setenv(field, value)
    with pytest.raises(ValueError):
        candidate.verify(output, digest)


@pytest.mark.parametrize("platform", ["macos", "windows"])
@pytest.mark.parametrize("sidecar", ["SOURCE-SHA", "SHA256SUMS"])
def test_producer_identity_is_checked_before_staging(staged, tmp_path, platform, sidecar):
    inputs, _, _ = staged
    (inputs / platform / f"{platform}-{sidecar}.txt").write_text("wrong")
    with pytest.raises(ValueError):
        candidate.prepare(inputs, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_detached_signature_does_not_allow_other_postacceptance_changes(staged):
    _, output, digest = staged
    (output / "SHA256SUMS.txt.minisig").write_text("fictional detached signature")
    with pytest.raises(ValueError):
        candidate.verify(output, digest)
    candidate.verify(output, digest, signed=True)
    (output / "candidate.json").write_text("{}")
    with pytest.raises(ValueError):
        candidate.verify(output, digest, signed=True)


@pytest.mark.parametrize("kind", ["lightweight", "annotated", "missing", "moved", "existing"])
def test_stable_tag_is_rechecked_against_accepted_commit(tmp_path, release_env, monkeypatch, kind):
    monkeypatch.setenv("CHANNEL", "stable")
    monkeypatch.setenv("ASSET_TOKEN", "v5.16.1")
    tag = "refs/tags/v5.16.1"
    sha = release_env["GITHUB_SHA"]
    text = f"{sha}\t{tag}\n"
    if kind == "annotated":
        text = f"{'b' * 40}\t{tag}\n{sha}\t{tag}^{{}}\n"
    elif kind == "missing":
        text = ""
    elif kind == "moved":
        text = f"{'b' * 40}\t{tag}\n"
    refs = tmp_path / "refs"
    refs.write_text(text)
    releases = tmp_path / "releases"
    releases.write_text("v5.16.1\n" if kind == "existing" else "v5.16.0\n")
    if kind in {"missing", "moved", "existing"}:
        with pytest.raises(ValueError):
            candidate.verify_tag(refs, releases)
    else:
        candidate.verify_tag(refs, releases)


@pytest.mark.parametrize("fault", ["none", "missing", "failed", "source", "app", "later_failure"])
def test_exact_source_checks_fail_closed(tmp_path, release_env, fault):
    rows = [{"id": index, "name": name, "head_sha": release_env["GITHUB_SHA"],
             "app": {"slug": "github-actions"}, "status": "completed", "conclusion": "success"}
            for index, name in enumerate(sorted(candidate.REQUIRED_CHECKS), 1)]
    if fault == "missing":
        rows.pop()
    elif fault == "failed":
        rows[0]["conclusion"] = "failure"
    elif fault == "source":
        rows[0]["head_sha"] = "b" * 40
    elif fault == "app":
        rows[0]["app"]["slug"] = "other"
    elif fault == "later_failure":
        rows.append({**rows[0], "id": 99, "conclusion": "failure"})
    checks = tmp_path / "checks"
    checks.write_text("\n".join(json.dumps(row) for row in rows))
    if fault == "none":
        candidate.verify_checks(checks)
    else:
        with pytest.raises(ValueError):
            candidate.verify_checks(checks)


@pytest.mark.skipif(os.name == "nt", reason="Preparation runs in Bash on Ubuntu")
@pytest.mark.parametrize("event,ref,publish_request,attempt,allowed,publish", [
    ("push", "refs/heads/main", "false", "1", True, False),
    ("push", "refs/tags/v5.16.1", "false", "1", True, False),
    ("workflow_dispatch", "refs/heads/main", "false", "1", True, False),
    ("workflow_dispatch", "refs/heads/main", "true", "1", True, True),
    ("workflow_dispatch", "refs/tags/v5.16.1", "true", "1", True, True),
    ("workflow_dispatch", "refs/heads/other", "true", "1", False, False),
    ("workflow_dispatch", "refs/heads/main", "true", "2", False, False),
])
def test_actual_prepare_policy(
    tmp_path, *, event, ref, publish_request, attempt, allowed, publish
):
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    block = workflow.split("      - name: Resolve build variables", 1)[1]
    block = block.split("        run: |\n", 1)[1].split("\n  test:", 1)[0]
    script = "\n".join(line[10:] for line in block.splitlines())
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app/version.py").write_text('__version__ = "5.16.1"\n')
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
    git("init", "-b", "main")
    git("add", "app/version.py")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-m", "Synthetic source")
    sha = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", sha)
    output = tmp_path / "output"
    # No inherited signing variables or credentials enter this subprocess.
    result = subprocess.run(["bash", "-c", script], cwd=repo, check=False, capture_output=True,
                            text=True, env={
                                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                                "MANUAL_SIGN_MACOS": "false", "MANUAL_NOTARIZE_MACOS": "false",
                                "MANUAL_SIGN_WINDOWS": "false", "EVENT_NAME": event,
                                "MANUAL_PUBLISH": publish_request,
                                "GITHUB_REF": ref, "GITHUB_REF_NAME": ref.rsplit("/", 1)[-1],
                                "GITHUB_SHA": sha, "GITHUB_RUN_ATTEMPT": attempt,
                                "GITHUB_OUTPUT": str(output),
                            })
    assert (result.returncode == 0) == allowed, result.stderr
    assert ('publish=true' in output.read_text()) == publish


def test_publication_is_protected_and_uses_immutable_candidate_without_building():
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    stage, publish = workflow.split("\n  stage-candidate:\n", 1)[1].split("\n  publish:\n", 1)
    assert "contents: write" not in stage
    assert "secrets." not in stage
    assert "environment: release-publication" in publish
    assert "github.run_attempt == 1" in publish
    assert "artifact-ids: ${{ needs.stage-candidate.outputs.artifact_id }}" in publish
    assert "packaging/release_candidate.py verify" in publish
    assert "packaging/release_candidate.py checks" in publish
    assert "packaging/release_candidate.py tag" in publish
    assert "PyInstaller" not in publish
    assert "build_and_verify_dmg" not in publish
    stable = publish.split("      - name: Publish stable release", 1)[1].split(
        "      - name: Refresh latest-main", 1)[0]
    assert "--clobber" not in stable
    assert workflow.count("dist/installer/windows-SOURCE-SHA.txt") == 2
