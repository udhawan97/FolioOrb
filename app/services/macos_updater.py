"""macOS in-app update: swap the running ``.app`` bundle from a verified DMG.

A running ``.app`` can't replace itself in place — its executable is locked while
it runs — so the install hands off to a small **detached** shell script that:

1. waits for this process to exit,
2. mounts the already-downloaded, SHA-256/minisign-verified DMG,
3. copies the new ``.app`` bundle next to the installed one and atomically
   swaps it in (restoring the old bundle if anything fails),
4. detaches the DMG, clears quarantine, and relaunches the app.

Data safety: the portfolio database and ``.env`` live in the per-user data
directory (``~/Library/Application Support/FolioOrb``), never inside the
bundle, so swapping the bundle cannot touch user data. The swap script only ever
writes to the target bundle, the DMG, a temp mountpoint, and the update log /
status markers.

On any failure the script relaunches the still-intact old bundle and drops a
``last-update-failed`` marker, which the app surfaces on next start.
"""
from __future__ import annotations

import logging
import os
import subprocess  # noqa: S404 (launches only the fixed swap script)
import sys
from pathlib import Path

from app import paths

logger = logging.getLogger(__name__)

FAILED_MARKER = "last-update-failed"
OK_MARKER = "last-update-ok"

# Static, argument-driven so no untrusted value is ever interpolated into shell.
# Args: $1 DMG  $2 BUNDLE  $3 PID  $4 LOGDIR  $5 MARKERDIR
_SWAP_SCRIPT = r"""#!/bin/bash
set -u
DMG="$1"; BUNDLE="$2"; PID="$3"; LOGDIR="$4"; MARKERDIR="$5"
mkdir -p "$LOGDIR" "$MARKERDIR"
exec >>"$LOGDIR/macos-update.log" 2>&1
echo "$(date -u) swap start dmg=$DMG bundle=$BUNDLE pid=$PID"
fail() {
  echo "$(date -u) FAILED: $1"
  : > "$MARKERDIR/last-update-failed"
  /usr/bin/open "$BUNDLE" 2>/dev/null || true
  exit 1
}
# Wait for the running app to exit (up to ~30s), then swap.
for _ in $(seq 1 60); do /bin/kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
MNT="$(/usr/bin/mktemp -d /tmp/folio-update.XXXXXX)"
trap '/bin/rm -rf "$MNT"' EXIT
/usr/bin/hdiutil attach "$DMG" -nobrowse -noverify -mountpoint "$MNT" -quiet || fail "mount"
# Locate the .app inside the DMG by extension rather than a hardcoded name, so a
# rebrand (FolioSenseAI.app -> FolioOrb.app) or any future rename can't break the
# swap. Every FolioOrb DMG ships exactly one bundle, so take the first match.
NEWAPP="$(ls -d "$MNT"/*.app 2>/dev/null | head -1)"
if [ -z "$NEWAPP" ] || [ ! -d "$NEWAPP" ]; then /usr/bin/hdiutil detach "$MNT" -quiet 2>/dev/null; fail "no-app-in-dmg"; fi
NEW="${BUNDLE}.new-$$"; OLD="${BUNDLE}.old-$$"
if ! /usr/bin/ditto "$NEWAPP" "$NEW"; then
  /bin/rm -rf "$NEW"; /usr/bin/hdiutil detach "$MNT" -quiet 2>/dev/null; fail "copy"
fi
/usr/bin/hdiutil detach "$MNT" -quiet 2>/dev/null || true
if ! /bin/mv "$BUNDLE" "$OLD"; then /bin/rm -rf "$NEW"; fail "move-aside"; fi
if ! /bin/mv "$NEW" "$BUNDLE"; then /bin/mv "$OLD" "$BUNDLE" 2>/dev/null; fail "move-in"; fi
/bin/rm -rf "$OLD"
/usr/bin/xattr -dr com.apple.quarantine "$BUNDLE" 2>/dev/null || true
/bin/rm -f "$DMG" 2>/dev/null || true
: > "$MARKERDIR/last-update-ok"
echo "$(date -u) swap ok; relaunching"
/usr/bin/open "$BUNDLE"
"""


def bundle_path() -> Path | None:
    """The running ``.app`` bundle path, or None if not launched from one."""
    try:
        exe = Path(sys.executable).resolve()
    except OSError:
        return None
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def can_swap_install() -> bool:
    """True only when running from a real ``.app`` bundle we can replace."""
    bundle = bundle_path()
    return bundle is not None and bundle.is_dir()


def _markers_dir() -> Path:
    directory = paths.data_dir() / "updates"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def launch_swap(dmg: Path) -> bool:
    """Write and launch the detached swap script for ``dmg``.

    Returns True if the swap was handed off, False if this isn't a bundle we can
    swap (dev/source run) — the caller then falls back to opening the DMG.
    """
    bundle = bundle_path()
    if bundle is None or not bundle.is_dir():
        return False

    markers = _markers_dir()
    log_dir = paths.data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    # Clear any stale result markers before starting a fresh attempt.
    for marker in (FAILED_MARKER, OK_MARKER):
        try:
            (markers / marker).unlink()
        except OSError:
            pass

    script = markers / "macos-swap.sh"
    script.write_text(_SWAP_SCRIPT, encoding="utf-8")
    script.chmod(0o755)

    subprocess.Popen(  # noqa: S603  pylint: disable=consider-using-with
        ["/bin/bash", str(script), str(dmg), str(bundle), str(os.getpid()),
         str(log_dir), str(markers)],
        start_new_session=True,  # survive this app quitting
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("Launched macOS bundle-swap helper for %s", bundle.name)
    return True


def consume_failed_marker() -> bool:
    """Return True (and clear it) if the last swap attempt left a failed marker.

    Only reports failure when there's a failed marker and no *newer* ok marker,
    so a successful reinstall is never mistaken for a failure.
    """
    markers = _markers_dir()
    failed = markers / FAILED_MARKER
    ok = markers / OK_MARKER
    if not failed.exists():
        return False
    is_failure = True
    try:
        if ok.exists() and ok.stat().st_mtime >= failed.stat().st_mtime:
            is_failure = False
    except OSError:
        pass
    for marker in (failed, ok):
        try:
            marker.unlink()
        except OSError:
            pass
    return is_failure
