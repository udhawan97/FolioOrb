"""Stage and verify the exact installer bytes presented for release acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


REQUIRED_CHECKS = {
    "Tests / Python 3.11", "Tests / Python 3.12", "Dependency Audit",
    "build (3.11)", "build (3.12)", "Analyze Python", "repository-hygiene",
}


def sha256(path: Path) -> str:
    """Hash large installers without loading them into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity() -> dict:
    """Bind a candidate to the live workflow identity, not inherited outputs."""
    source = os.environ["GITHUB_SHA"]
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    token = os.environ["ASSET_TOKEN"]
    version = os.environ["APP_VERSION"]
    channel = os.environ["CHANNEL"]
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("Invalid source SHA")
    if not run_id.isdigit() or attempt != "1":
        raise ValueError("Use a fresh workflow run; rerun attempts cannot publish")
    if channel not in {"stable", "dev"} or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid channel or version")
    if channel == "stable":
        valid_token = token == f"v{version}"
    else:
        short = token.removeprefix("main-")
        valid_token = token.startswith("main-") and 7 <= len(short) <= 40
        valid_token = valid_token and source.startswith(short)
    if not valid_token:
        raise ValueError("Asset token does not match source/version")
    return {
        "schema_version": 1, "source_sha": source, "run_id": run_id,
        "run_attempt": attempt, "channel": channel, "app_version": version,
        "asset_token": token,
    }


def installer_names(meta: dict) -> tuple[str, str]:
    token = meta["asset_token"]
    return (f"FolioOrb-macOS-arm64-{token}.dmg",
            f"FolioOrb-Windows-x64-{token}-Setup.exe")


def exact_files(directory: Path, names: set[str]) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Candidate directory is missing or a symlink")
    if {path.name for path in directory.iterdir()} != names:
        raise ValueError("Unexpected or missing candidate files")
    if any(path.is_symlink() or not path.is_file() for path in directory.iterdir()):
        raise ValueError("Candidate files must be regular files")


def bounded_text(path: Path) -> str:
    if path.stat().st_size > 65536:
        raise ValueError("Oversized candidate metadata")
    return path.read_text(encoding="utf-8")


def file_records(directory: Path, meta: dict) -> list[dict]:
    records = []
    for name in installer_names(meta):
        path = directory / name
        size = path.stat().st_size
        if not 0 < size <= 2 * 1024**3:
            raise ValueError("Invalid installer size")
        records.append({"name": name, "size": size, "sha256": sha256(path)})
    return records


def checksums(records: list[dict]) -> str:
    return "".join(f"{row['sha256']}  {row['name']}\n" for row in records)


def prepare(inputs: Path, output: Path) -> str:
    meta = identity()
    for platform, name in zip(("macos", "windows"), installer_names(meta)):
        directory = inputs / platform
        checksum_name = f"{platform}-SHA256SUMS.txt"
        source_name = f"{platform}-SOURCE-SHA.txt"
        exact_files(directory, {name, checksum_name, source_name})
        if bounded_text(directory / source_name).strip() != meta["source_sha"]:
            raise ValueError("Producer source SHA mismatch")
        expected = f"{sha256(directory / name)}  {name}"
        if bounded_text(directory / checksum_name).strip() != expected:
            raise ValueError("Producer checksum mismatch")
    output.mkdir(parents=True, exist_ok=False)
    for platform, name in zip(("macos", "windows"), installer_names(meta)):
        shutil.copyfile(inputs / platform / name, output / name)
    records = file_records(output, meta)
    (output / "SHA256SUMS.txt").write_text(checksums(records), encoding="utf-8")
    manifest = output / "candidate.json"
    manifest.write_text(json.dumps({**meta, "files": records}, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    return sha256(manifest)


def verify(directory: Path, expected_digest: str, *, signed: bool = False) -> dict:
    meta = identity()
    names = {*installer_names(meta), "candidate.json", "SHA256SUMS.txt"}
    if signed and (directory / "SHA256SUMS.txt.minisig").exists():
        names.add("SHA256SUMS.txt.minisig")
    exact_files(directory, names)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ValueError("Invalid expected manifest digest")
    manifest = directory / "candidate.json"
    text = bounded_text(manifest)
    if sha256(manifest) != expected_digest:
        raise ValueError("Accepted manifest digest mismatch")
    records = file_records(directory, meta)
    if json.loads(text) != {**meta, "files": records}:
        raise ValueError("Candidate identity, installer size or checksum mismatch")
    if bounded_text(directory / "SHA256SUMS.txt") != checksums(records):
        raise ValueError("Candidate checksum list mismatch")
    if "SHA256SUMS.txt.minisig" in names:
        bounded_text(directory / "SHA256SUMS.txt.minisig")
    return meta


def verify_checks(path: Path) -> None:
    """Require the latest GitHub Actions result for each main-branch source gate."""
    source = identity()["source_sha"]
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        check = json.loads(line)
        if check.get("head_sha") != source or check.get("app", {}).get("slug") != "github-actions":
            continue
        name = check.get("name")
        if name not in latest or check["id"] > latest[name]["id"]:
            latest[name] = check
    failed = [name for name in sorted(REQUIRED_CHECKS)
              if name not in latest or latest[name].get("status") != "completed"
              or latest[name].get("conclusion") != "success"]
    if failed:
        raise ValueError(f"Missing or unsuccessful exact-source checks: {', '.join(failed)}")


def verify_tag(path: Path, releases: Path) -> None:
    """Resolve lightweight/annotated tag evidence fetched after acceptance."""
    meta = identity()
    tag = f"v{meta['app_version']}"
    if meta["channel"] != "stable":
        raise ValueError("Tag verification requires a stable candidate")
    refs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        commit, ref = line.split()
        refs[ref] = commit
    ref = f"refs/tags/{tag}"
    resolved = refs.get(f"{ref}^{{}}", refs.get(ref))
    if resolved != meta["source_sha"]:
        raise ValueError("Stable tag is missing or moved from the accepted source")
    if tag in releases.read_text(encoding="utf-8").splitlines():
        raise ValueError("Stable release already exists; immutable assets cannot be replaced")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "checks", "tag"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--digest")
    parser.add_argument("--signed", action="store_true")
    parser.add_argument("--releases", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.output is None:
            parser.error("prepare requires --output")
        print(prepare(args.path, args.output))
    elif args.command == "verify":
        verify(args.path, args.digest or "", signed=args.signed)
    elif args.command == "checks":
        verify_checks(args.path)
    else:
        if args.releases is None:
            parser.error("tag requires --releases")
        verify_tag(args.path, args.releases)


if __name__ == "__main__":
    main()
