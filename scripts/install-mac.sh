#!/usr/bin/env bash
# One-command Mac installer (runs FolioOrb from source).
# Usage: curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioOrb/main/scripts/install-mac.sh | bash
#
# By default this installs the latest stable release. Override the ref to pin a
# supported tag (v5.16.0+) or track the dev channel:
#   curl ... | FOLIO_REF=v5.16.1 bash
#   curl ... | FOLIO_REF=latest-main bash
#   curl ... | FOLIO_REF=main bash
#
# Prefer the .dmg for a no-Python install: https://github.com/udhawan97/FolioOrb/releases/latest
set -euo pipefail

REPO="udhawan97/FolioOrb"
INSTALL_DIR="${FOLIOORB_INSTALL_DIR:-$HOME/Applications/FolioOrb}"
SHORTCUT="${FOLIOORB_SHORTCUT:-$HOME/Desktop/FolioOrb.command}"
if [[ "$(uname -s)" == "Darwin" ]]; then
  DEFAULT_DATA_DIR="$HOME/Library/Application Support/FolioOrb-source"
else
  DEFAULT_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/FolioOrb-source"
fi
DATA_DIR="${FOLIOORB_DATA_DIR:-$DEFAULT_DATA_DIR}"
NO_START="${FOLIOORB_INSTALL_NO_START:-0}"
TMP=""
ROLLBACK_DIR=""
INSTALL_READY=0

cleanup() {
  local status=$?
  trap - EXIT
  if (( status != 0 && INSTALL_READY == 0 )) && [[ -n "$ROLLBACK_DIR" && -e "$ROLLBACK_DIR" ]]; then
    if [[ -e "$INSTALL_DIR" && -n "$TMP" ]]; then
      mv "$INSTALL_DIR" "$TMP/failed-install-$$" 2>/dev/null || true
    fi
    if [[ ! -e "$INSTALL_DIR" ]]; then
      mv "$ROLLBACK_DIR" "$INSTALL_DIR" 2>/dev/null || true
    fi
    echo "  Installation failed; the prior source install was restored." >&2
  fi
  if [[ -n "$TMP" && -d "$TMP" ]]; then
    rm -rf "$TMP"
  fi
  exit "$status"
}
trap cleanup EXIT

echo ""
echo "  FolioOrb Installer"
echo "  ─────────────────────"
echo ""

# ── Resolve which ref to download ─────────────────────────────────────────────
REF="${FOLIO_REF:-}"
if [[ -z "$REF" ]]; then
  REF="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
        | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1 || true)"
fi
if [[ -z "$REF" ]]; then
  echo "  Could not resolve the latest release — falling back to 'main'."
  REF="main"
fi
echo "  Installing ref: $REF"

RELEASE_URL="https://github.com/$REPO/archive/refs/tags/$REF.zip"
if [[ "$REF" == "main" ]]; then
  RELEASE_URL="https://github.com/$REPO/archive/refs/heads/main.zip"
fi

# ── Python ────────────────────────────────────────────────────────────────────
find_python() {
  for candidate in python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
        echo "$candidate"; return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "  Python 3.11+ is required."
  echo "  Opening the download page — install it, then run this command again."
  open "https://www.python.org/downloads/" 2>/dev/null || true
  exit 1
fi
echo "  ✓ $("$PYTHON_BIN" --version)"

if [[ "$REF" != "main" && "$REF" != "latest-main" ]]; then
  if ! "$PYTHON_BIN" - "$REF" <<'PY'
import re
import sys

match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", sys.argv[1])
raise SystemExit(0 if match and tuple(map(int, match.groups())) >= (5, 16, 0) else 1)
PY
  then
    echo "  Source installs support stable tags v5.16.0 or newer." >&2
    echo "  Choose a supported tag, 'latest-main', or 'main'." >&2
    exit 1
  fi
fi

# Normalize every persisted profile reference once, independent of caller CWD.
DATA_DIR="$("$PYTHON_BIN" -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$DATA_DIR")"
INSTALL_DIR="$("$PYTHON_BIN" -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$INSTALL_DIR")"
SHORTCUT="$("$PYTHON_BIN" -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$SHORTCUT")"
MIGRATION_COMPLETE="$DATA_DIR/.source-install-migration-complete"

# ── Download ──────────────────────────────────────────────────────────────────
TMP="$(mktemp -d)"
echo "  Downloading FolioOrb ($REF)..."
curl -fsSL --progress-bar "$RELEASE_URL" -o "$TMP/folio.zip"

echo "  Extracting..."
unzip -q "$TMP/folio.zip" -d "$TMP/"
EXTRACTED="$(find "$TMP" -maxdepth 1 -type d -name 'FolioOrb-*' | head -n1)"
if [[ -z "$EXTRACTED" ]]; then
  echo "  Download did not contain the expected FolioOrb folder." >&2
  exit 1
fi

# v5.16.0 understands the external-profile environment variable but predates
# the migration helper. Use the selected archive's helper when present and the
# current compatibility helper otherwise.
MIGRATION_TOOL="$EXTRACTED/scripts/migrate_source_profile.py"
if [[ ! -f "$MIGRATION_TOOL" ]]; then
  MIGRATION_TOOL="$TMP/migrate_source_profile.py"
  curl -fsSL "https://raw.githubusercontent.com/$REPO/main/scripts/migrate_source_profile.py" \
    -o "$MIGRATION_TOOL"
fi

# ── Preserve the complete writable profile ───────────────────────────────────
MIGRATION_STATUS="$(
  "$PYTHON_BIN" "$MIGRATION_TOOL" --source "$INSTALL_DIR" --destination "$DATA_DIR"
)"
KEEP_RECOVERY=0
if [[ "$MIGRATION_STATUS" == "MIGRATED" ]]; then
  KEEP_RECOVERY=1
  echo "  ✓ Portfolio, backups, settings, and update state migrated"
fi

# ── Install transaction ───────────────────────────────────────────────────────
mkdir -p "$(dirname "$INSTALL_DIR")"
if [[ -e "$INSTALL_DIR" ]]; then
  STAMP="$(date -u '+%Y%m%dT%H%M%SZ')-$$"
  if (( KEEP_RECOVERY == 1 )); then
    ROLLBACK_DIR="${INSTALL_DIR}-profile-recovery-$STAMP"
  else
    ROLLBACK_DIR="${INSTALL_DIR}-update-rollback-$STAMP"
  fi
  mv "$INSTALL_DIR" "$ROLLBACK_DIR"
fi
mv "$EXTRACTED" "$INSTALL_DIR"
printf '%s\n' "$DATA_DIR" > "$INSTALL_DIR/.source-profile-path"
export FOLIOORB_DATA_DIR="$DATA_DIR"

echo "  Installing dependencies (one-time, ~60 s)..."
cd "$INSTALL_DIR"
"$PYTHON_BIN" -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q

if [[ ! -f "$DATA_DIR/.env" ]]; then
  SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
  printf 'ANTHROPIC_API_KEY=\nSECRET_KEY=%s\nDEBUG=True\nDATABASE_URL=sqlite:///./database/portfolio.db\nCORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000\nDEFAULT_HOLDINGS=\n' "$SECRET" > "$DATA_DIR/.env"
elif ! grep -Eq '^[[:space:]]*(export[[:space:]]+)?SECRET_KEY[[:space:]]*=' "$DATA_DIR/.env"; then
  SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
  printf 'SECRET_KEY=%s\n' "$SECRET" >> "$DATA_DIR/.env"
fi
printf 'source installer profile ready\n' > "$MIGRATION_COMPLETE"

# ── Desktop shortcut ─────────────────────────────────────────────────────────
mkdir -p "$(dirname "$SHORTCUT")"
cat > "$SHORTCUT" <<LAUNCHER
#!/usr/bin/env bash
cd "$INSTALL_DIR"
export FOLIOORB_DATA_DIR="$DATA_DIR"
exec bash FolioOrb.command
LAUNCHER
chmod +x "$SHORTCUT"
xattr -d com.apple.quarantine "$SHORTCUT" 2>/dev/null || true

if [[ -n "$ROLLBACK_DIR" && "$KEEP_RECOVERY" -eq 0 ]]; then
  rm -rf "$ROLLBACK_DIR"
  ROLLBACK_DIR=""
fi
INSTALL_READY=1

echo ""
echo "  ✓ Installed to $INSTALL_DIR"
echo "  ✓ Writable profile: $DATA_DIR"
if [[ -n "$ROLLBACK_DIR" ]]; then
  echo "  ✓ Prior source install retained at $ROLLBACK_DIR"
fi
echo "  ✓ Desktop shortcut created at $SHORTCUT"
echo ""
if [[ "$NO_START" == "1" ]]; then
  echo "  Start skipped for installer verification."
  exit 0
fi
echo "  Starting FolioOrb — your browser will open in a moment..."
echo "  (Press Ctrl+C to stop)"
echo ""
python run.py
