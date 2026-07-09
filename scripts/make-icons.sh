#!/usr/bin/env bash
# Regenerate the platform icon files from the 1024×1024 brand PNG.
#
#   packaging/icons/FolioOrb.icns   (macOS app bundle)
#   packaging/icons/FolioOrb.ico    (Windows installer + exe)
#
# The generated files are committed so CI never needs cross-platform icon
# tooling. Run this only when the brand mark changes. Requires macOS (sips,
# iconutil) and Python with Pillow for the .ico.
set -euo pipefail

cd "$(dirname "$0")/.."

SRC="static/img/brand/folio-orbit-icon-1024.png"
OUT_DIR="packaging/icons"
ICNS="$OUT_DIR/FolioOrb.icns"
ICO="$OUT_DIR/FolioOrb.ico"

[[ -f "$SRC" ]] || { echo "Source icon not found: $SRC" >&2; exit 1; }
mkdir -p "$OUT_DIR"

# ── macOS .icns via an iconset ────────────────────────────────────────────────
ICONSET="$(mktemp -d)/FolioOrb.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size"       "$SRC" --out "$ICONSET/icon_${size}x${size}.png"   >/dev/null
  sips -z $((size*2)) $((size*2)) "$SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ICNS"
echo "Wrote $ICNS"

# ── Windows .ico via Pillow (multi-resolution) ────────────────────────────────
python3 - "$SRC" "$ICO" <<'PY'
import sys
from PIL import Image

src, out = sys.argv[1], sys.argv[2]
img = Image.open(src).convert("RGBA")
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(out, format="ICO", sizes=sizes)
print(f"Wrote {out}")
PY
