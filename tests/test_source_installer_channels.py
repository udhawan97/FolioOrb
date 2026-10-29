"""Source installer channel resolution fails before touching an existing install."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("metadata", [
    "failure", "empty", "malformed", "main", "latest-main", "unsupported", "badref", "stable",
])
@pytest.mark.parametrize("explicit", [None, "main", "latest-main", "v5.16.1"])
@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="Requires Bash source installer")
def test_mac_installer_channel_resolution(tmp_path, metadata, explicit):
    """Only the metadata curl stub runs; archive curl deliberately refuses."""
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python3.12").symlink_to(sys.executable)
    log = tmp_path / "requests.log"
    curl = binaries / "curl"
    curl.write_text("""#!/bin/bash
printf '%s\\n' "$*" >> "$REQUEST_LOG"
case "$*" in
  *api.github.com*)
    case "$METADATA" in
      failure) exit 22 ;;
      empty) printf '{}\\n' ;;
      malformed) printf '{broken\\n' ;;
      main) printf '{"tag_name":"main"}\\n' ;;
      latest-main) printf '{"tag_name":"latest-main"}\\n' ;;
      unsupported) printf '{"tag_name":"v5.15.0"}\\n' ;;
      badref) printf '{"tag_name":"not-a-tag"}\\n' ;;
      stable) printf '{"tag_name":"v5.16.1"}\\n' ;;
    esac ;;
  *) exit 22 ;;
esac
""", encoding="utf-8")
    curl.chmod(0o755)
    install = tmp_path / "install"
    profile = tmp_path / "profile"
    install.mkdir()
    profile.mkdir()
    (install / "keep.txt").write_bytes(b"existing code")
    (profile / "keep.txt").write_bytes(b"existing profile")
    shortcut = tmp_path / "shortcut.command"
    env = dict(os.environ)
    # Cleared test runners may omit HOME; retain the account home, never relocate it.
    env.setdefault("HOME", str(Path.home()))
    env.pop("FOLIO_REF", None)
    env.update(
        PATH=f"{binaries}:{env['PATH']}", REQUEST_LOG=str(log), METADATA=metadata,
        FOLIOORB_INSTALL_DIR=str(install), FOLIOORB_DATA_DIR=str(profile),
        FOLIOORB_SHORTCUT=str(shortcut), FOLIOORB_INSTALL_NO_START="1",
    )
    if explicit:
        env["FOLIO_REF"] = explicit
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts" / "install-mac.sh")],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0  # The archive stub never downloads anything.
    requests = log.read_text().splitlines()
    if explicit is None and metadata != "stable":
        assert len(requests) == 1
        assert ("latest stable release" in result.stderr or
                "Source installs support stable tags" in result.stderr)
    else:
        selected = explicit or "v5.16.1"
        archive = "heads/main" if selected == "main" else f"tags/{selected}"
        assert f"archive/refs/{archive}.zip" in requests[-1]
        assert len(requests) == (1 if explicit else 2)
    assert sorted(path.name for path in install.iterdir()) == ["keep.txt"]
    assert sorted(path.name for path in profile.iterdir()) == ["keep.txt"]
    assert (install / "keep.txt").read_bytes() == b"existing code"
    assert (profile / "keep.txt").read_bytes() == b"existing profile"
    assert not shortcut.exists()


def test_windows_stable_resolution_has_no_implicit_main_fallback():
    """Static guard only; actual PowerShell acceptance needs Windows/PowerShell."""
    source = (ROOT / "scripts" / "install-win.ps1").read_text()
    resolution = source[source.index("$ref = $env:FOLIO_REF"):source.index("# -- Python")]
    assert 'throw "Could not resolve the latest stable release.' in resolution
    assert '$ref = "main"' not in resolution


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="Requires Bash source installer")
@pytest.mark.parametrize("explicit", [None, "main"])
def test_mac_extraction_is_install_sibling_only_after_metadata_acceptance(tmp_path, explicit):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python3.12").symlink_to(sys.executable)
    log = tmp_path / "archive-path.txt"
    curl = binaries / "curl"
    curl.write_text("""#!/bin/bash
case "$*" in *api.github.com*) exit 22 ;; esac
while (( $# )); do
  if [[ "$1" == "-o" ]]; then printf '%s\\n' "$2" > "$REQUEST_LOG"; break; fi
  shift
done
exit 22
""", encoding="utf-8")
    curl.chmod(0o755)
    install = tmp_path / "new install parent" / "install"
    other_temp = tmp_path / "unrelated system temp"
    other_temp.mkdir()
    profile = tmp_path / "other profile"
    env = dict(os.environ)
    env.setdefault("HOME", str(Path.home()))
    env.pop("FOLIO_REF", None)
    env.update(
        PATH=f"{binaries}:{env['PATH']}", REQUEST_LOG=str(log), TMPDIR=str(other_temp),
        FOLIOORB_INSTALL_DIR=str(install), FOLIOORB_DATA_DIR=str(profile),
        FOLIOORB_SHORTCUT=str(tmp_path / "shortcut"), FOLIOORB_INSTALL_NO_START="1",
    )
    if explicit:
        env["FOLIO_REF"] = explicit
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts" / "install-mac.sh")],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0  # Archive I/O is deliberately stopped before cutover.
    if explicit:
        archive = Path(log.read_text().strip())
        assert archive.parent.parent == install.parent
        assert archive.parent.name.startswith(".folioorb-install.")
        assert not archive.parent.exists()  # Failure cleanup owns the temporary sibling.
    else:
        assert not install.parent.exists()  # Metadata refusal precedes parent creation.
        assert not log.exists()
    assert not install.exists() and not profile.exists()
    assert not list(other_temp.iterdir())
