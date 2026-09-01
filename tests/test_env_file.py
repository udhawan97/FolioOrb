# pylint: disable=protected-access
"""Security and fault contracts for the one POSIX environment-file writer."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.services import env_file


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_initialize_publishes_complete_owner_only_profile(tmp_path):
    target = tmp_path / ".env"

    env_file.initialize_profile_env(target, "sk-ant-fictional", "secret")

    assert _mode(target) == 0o600
    assert target.read_text(encoding="utf-8").startswith(
        "ANTHROPIC_API_KEY=sk-ant-fictional\nSECRET_KEY=secret\n"
    )


def test_temporary_file_is_0600_before_content_write(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    real_fdopen = env_file.os.fdopen
    observed = []

    def checked_fdopen(descriptor, *args, **kwargs):
        observed.append(stat.S_IMODE(os.fstat(descriptor).st_mode))
        return real_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(env_file.os, "fdopen", checked_fdopen)

    env_file.initialize_profile_env(target, "", "secret")

    assert observed == [0o600]


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_source_setup_existing_file_is_retightened_without_content_change(
    tmp_path, monkeypatch
):
    target = tmp_path / ".env"
    original = b"ANTHROPIC_API_KEY=fictional\nSECRET_KEY=keep-this-byte-for-byte\n"
    target.write_bytes(original)
    target.chmod(0o644)
    identity = (target.stat().st_dev, target.stat().st_ino)

    def reject_content_read(*_args, **_kwargs):
        raise AssertionError("existing environment content must not be read")

    monkeypatch.setattr(env_file.os, "fdopen", reject_content_read)

    env_file.secure_existing_env(target)

    assert target.read_bytes() == original
    assert (target.stat().st_dev, target.stat().st_ino) == identity
    assert _mode(target) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner contract")
def test_source_setup_existing_wrong_owner_is_refused_without_change(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    target.write_text("ANTHROPIC_API_KEY=original\n", encoding="utf-8")
    target.chmod(0o644)
    before = target.read_bytes()
    before_mode = _mode(target)
    monkeypatch.setattr(env_file.os, "geteuid", lambda: target.stat().st_uid + 1)

    with pytest.raises(env_file.EnvFileSecurityError, match="not owned"):
        env_file.secure_existing_env(target)

    assert target.read_bytes() == before
    assert _mode(target) == before_mode


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink contract")
def test_source_setup_existing_symlink_is_refused_without_touching_referent(tmp_path):
    referent = tmp_path / "real.env"
    referent.write_text("ANTHROPIC_API_KEY=original\n", encoding="utf-8")
    referent.chmod(0o644)
    before = referent.read_bytes()
    before_mode = _mode(referent)
    target = tmp_path / ".env"
    target.symlink_to(referent)

    with pytest.raises(env_file.EnvFileSecurityError, match="regular file"):
        env_file.secure_existing_env(target)

    assert referent.read_bytes() == before
    assert _mode(referent) == before_mode
    assert target.is_symlink()


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner contract")
def test_wrong_owner_target_is_refused_without_change(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    target.write_text("ANTHROPIC_API_KEY=original\n", encoding="utf-8")
    before = target.read_bytes()
    monkeypatch.setattr(env_file.os, "geteuid", lambda: target.stat().st_uid + 1)

    with pytest.raises(env_file.EnvFileSecurityError, match="not owned"):
        env_file.update_env_key(target, "ANTHROPIC_API_KEY", "replacement")

    assert target.read_bytes() == before


def test_symlink_target_is_refused_without_touching_referent(tmp_path):
    referent = tmp_path / "real.env"
    referent.write_text("ANTHROPIC_API_KEY=original\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.symlink_to(referent)

    with pytest.raises(env_file.EnvFileSecurityError, match="regular file"):
        env_file.update_env_key(target, "ANTHROPIC_API_KEY", "replacement")

    assert referent.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=original\n"
    assert target.is_symlink()


def test_nonregular_target_is_refused(tmp_path):
    target = tmp_path / ".env"
    target.mkdir()

    with pytest.raises(env_file.EnvFileSecurityError, match="regular file"):
        env_file.update_env_key(target, "ANTHROPIC_API_KEY", "replacement")


def test_replace_failure_keeps_original_and_removes_secret_staging(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    target.write_text("ANTHROPIC_API_KEY=original\n", encoding="utf-8")
    target.chmod(0o600)
    before = target.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(env_file.os, "replace", fail_replace)

    with pytest.raises(OSError, match="publication failure"):
        env_file.update_env_key(target, "ANTHROPIC_API_KEY", "replacement")

    assert target.read_bytes() == before
    assert not list(tmp_path.glob("..env-*.tmp"))


def test_setup_script_delegates_secret_publication_to_shared_writer():
    script = (Path(__file__).resolve().parents[1] / "scripts/setup.sh").read_text(
        encoding="utf-8"
    )

    assert 'python -m app.services.env_file "$PROFILE_DIR/.env"' in script
    assert (
        'python -m app.services.env_file --secure-existing "$PROFILE_DIR/.env"'
        in script
    )
    assert 'cat > "$PROFILE_DIR/.env"' not in script


def test_macos_source_installer_delegates_secret_writes_to_shared_writer():
    script = (Path(__file__).resolve().parents[1] / "scripts/install-mac.sh").read_text(
        encoding="utf-8"
    )

    assert 'python -m app.services.env_file "$DATA_DIR/.env"' in script
    assert 'python -m app.services.env_file --set-secret "$DATA_DIR/.env"' in script
    assert (
        'python -m app.services.env_file --secure-existing "$DATA_DIR/.env"'
        in script
    )
    assert "printf 'SECRET_KEY=%s" not in script
