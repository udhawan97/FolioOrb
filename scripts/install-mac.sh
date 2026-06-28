#!/usr/bin/env bash
# One-command Mac installer.
# Usage: curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.1/scripts/install-mac.sh | bash
set -euo pipefail

INSTALL_DIR="$HOME/Applications/FolioSenseAI"
SHORTCUT="$HOME/Desktop/FolioSenseAI.command"
RELEASE_URL="https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v4.1.zip"
EXTRACT_NAME="FolioSenseAI-release-v4.1"

echo ""
echo "  FolioSenseAI Installer"
echo "  ─────────────────────"
echo ""

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

echo "  Downloading FolioSenseAI v4.1..."
curl -fsSL --progress-bar "$RELEASE_URL" -o "$TMP/folio.zip"

echo "  Extracting..."
unzip -q "$TMP/folio.zip" -d "$TMP/"

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
mv "$TMP/$EXTRACT_NAME" "$INSTALL_DIR"

[[ -d "$TMP/db_backup" ]] && cp -r "$TMP/db_backup" "$INSTALL_DIR/database" && echo "  ✓ Portfolio data restored"
[[ -f "$TMP/env_backup" ]] && cp "$TMP/env_backup" "$INSTALL_DIR/.env" && echo "  ✓ Settings restored"

# ── Dependencies ──────────────────────────────────────────────────────────────
echo "  Installing dependencies (one-time, ~60 s)..."
cd "$INSTALL_DIR"
"$PYTHON_BIN" -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
mkdir -p database

if [[ ! -f .env ]]; then
  SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
  printf 'ANTHROPIC_API_KEY=\nSECRET_KEY=%s\nDEBUG=True\nDATABASE_URL=sqlite:///./database/portfolio.db\nCORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000\nDEFAULT_HOLDINGS=\n' "$SECRET" > .env
fi

# ── Desktop shortcut ─────────────────────────────────────────────────────────
cp "$INSTALL_DIR/FolioSenseAI.command" "$SHORTCUT"
chmod +x "$SHORTCUT"
# Files installed via curl (not browser) are not quarantined, but remove just in case.
xattr -d com.apple.quarantine "$SHORTCUT" 2>/dev/null || true

echo ""
echo "  ✓ Installed to ~/Applications/FolioSenseAI"
echo "  ✓ Desktop shortcut created — double-click it anytime to open the app"
echo ""
echo "  Starting FolioSenseAI — your browser will open in a moment..."
echo "  (Press Ctrl+C to stop)"
echo ""
python run.py
