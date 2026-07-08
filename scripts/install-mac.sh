#!/usr/bin/env bash
# One-command Mac installer (runs FolioSenseAI from source).
# Usage: curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioSenseAI/main/scripts/install-mac.sh | bash
#
# By default this installs the latest stable release. Override the ref to pin a
# tag or track the dev channel:
#   FOLIO_REF=v4.3.2      curl ... | bash     # a specific release
#   FOLIO_REF=latest-main curl ... | bash     # newest main build
#   FOLIO_REF=main        curl ... | bash     # current main branch
#
# Prefer the .dmg for a no-Python install: https://github.com/udhawan97/FolioSenseAI/releases/latest
set -euo pipefail

REPO="udhawan97/FolioSenseAI"
INSTALL_DIR="$HOME/Applications/FolioSenseAI"
SHORTCUT="$HOME/Desktop/FolioSenseAI.command"

echo ""
echo "  FolioSenseAI Installer"
echo "  ─────────────────────"
echo ""

# ── Resolve which ref to download ─────────────────────────────────────────────
# Default to the latest published release tag; fall back to main if the API is
# unreachable or no release exists yet.
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
# Branch refs (e.g. main) live under a different archive path than tags.
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

# ── Download ──────────────────────────────────────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "  Downloading FolioSenseAI ($REF)..."
curl -fsSL --progress-bar "$RELEASE_URL" -o "$TMP/folio.zip"

echo "  Extracting..."
unzip -q "$TMP/folio.zip" -d "$TMP/"

# GitHub names the extracted folder after the ref (and strips a leading "v" on
# version tags), so locate it instead of guessing the name.
EXTRACTED="$(find "$TMP" -maxdepth 1 -type d -name 'FolioSenseAI-*' | head -n1)"
if [[ -z "$EXTRACTED" ]]; then
  echo "  Download did not contain the expected FolioSenseAI folder." >&2
  exit 1
fi

# ── Preserve existing data ────────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/database" ]]; then
  echo "  Existing portfolio found — preserving your data..."
  cp -r "$INSTALL_DIR/database" "$TMP/db_backup"
fi
if [[ -f "$INSTALL_DIR/.env" ]]; then
  cp "$INSTALL_DIR/.env" "$TMP/env_backup"
fi

# ── Install ───────────────────────────────────────────────────────────────────
mkdir -p "$HOME/Applications"
rm -rf "$INSTALL_DIR"
mv "$EXTRACTED" "$INSTALL_DIR"

[[ -f "$TMP/env_backup" ]] && cp "$TMP/env_backup" "$INSTALL_DIR/.env" && echo "  ✓ Settings restored"

# Restore database before pip so data is safe even if dependency install fails.
if [[ -d "$TMP/db_backup" ]]; then
  rm -rf "$INSTALL_DIR/database"
  cp -r "$TMP/db_backup" "$INSTALL_DIR/database"
  echo "  ✓ Portfolio data restored"
else
  mkdir -p "$INSTALL_DIR/database"
fi

# ── Dependencies ──────────────────────────────────────────────────────────────
echo "  Installing dependencies (one-time, ~60 s)..."
cd "$INSTALL_DIR"
"$PYTHON_BIN" -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q

if [[ ! -f .env ]]; then
  SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
  printf 'ANTHROPIC_API_KEY=\nSECRET_KEY=%s\nDEBUG=True\nDATABASE_URL=sqlite:///./database/portfolio.db\nCORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000\nDEFAULT_HOLDINGS=\n' "$SECRET" > .env
fi

# ── Desktop shortcut ─────────────────────────────────────────────────────────
# Write a launcher that knows the absolute install path, so double-clicking
# from the Desktop doesn't cd to ~/Desktop and lose the scripts/ directory.
cat > "$SHORTCUT" <<LAUNCHER
#!/usr/bin/env bash
cd "$INSTALL_DIR"
exec bash FolioSenseAI.command
LAUNCHER
chmod +x "$SHORTCUT"
xattr -d com.apple.quarantine "$SHORTCUT" 2>/dev/null || true

echo ""
echo "  ✓ Installed to ~/Applications/FolioSenseAI"
echo "  ✓ Desktop shortcut created — double-click it anytime to open the app"
echo ""
echo "  Starting FolioSenseAI — your browser will open in a moment..."
echo "  (Press Ctrl+C to stop)"
echo ""
python run.py
