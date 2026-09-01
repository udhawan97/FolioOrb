#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" != "2" ]]; then
  echo "usage: $0 APP_BUNDLE OUTPUT_DMG" >&2
  exit 2
fi

APP_BUNDLE="$1"
OUTPUT_DMG="$2"
if [[ ! -d "$APP_BUNDLE" || "$(basename "$APP_BUNDLE")" != "FolioOrb.app" ]]; then
  echo "Expected the exact FolioOrb.app bundle." >&2
  exit 1
fi
if ! command -v create-dmg >/dev/null 2>&1; then
  echo "create-dmg is required." >&2
  exit 1
fi
if ! command -v hdiutil >/dev/null 2>&1; then
  echo "hdiutil is required." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_DMG")"
rm -f -- "$OUTPUT_DMG"
STAGE_ROOT="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/folioorb-dmg-stage.XXXXXX")"
MOUNT_ROOT="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/folioorb-dmg-check.XXXXXX")"
MOUNT_POINT="$MOUNT_ROOT/mounted"
mkdir "$MOUNT_POINT"
DMG_MOUNTED=false
cleanup() {
  if [[ "$DMG_MOUNTED" == "true" ]]; then
    hdiutil detach "$MOUNT_POINT" -quiet || true
  fi
  rm -rf -- "$STAGE_ROOT"
  rmdir "$MOUNT_POINT" "$MOUNT_ROOT" 2>/dev/null || true
}
trap cleanup EXIT

cp -R "$APP_BUNDLE" "$STAGE_ROOT/FolioOrb.app"
# Compatibility for pre-rename (<= v4.x) auto-updaters. Keep the alias outside
# the visible window while preserving the exact relative target.
ln -s FolioOrb.app "$STAGE_ROOT/FolioSenseAI.app"

set +e
create-dmg \
  --volname "FolioOrb" \
  --volicon packaging/icons/FolioOrb.icns \
  --window-size 540 380 \
  --icon-size 110 \
  --icon "FolioOrb.app" 150 190 \
  --app-drop-link 390 190 \
  --hide-extension "FolioOrb.app" \
  --icon "FolioSenseAI.app" 620 999 \
  "$OUTPUT_DMG" "$STAGE_ROOT/"
CREATE_DMG_STATUS=$?
set -e

DMGS=("$(dirname "$OUTPUT_DMG")"/*.dmg)
if [[ "${#DMGS[@]}" != "1" || ! -f "${DMGS[0]}" || "${DMGS[0]}" != "$OUTPUT_DMG" ]]; then
  echo "Expected exactly the named macOS DMG." >&2
  exit 1
fi

hdiutil verify "$OUTPUT_DMG"
hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT_POINT" "$OUTPUT_DMG" >/dev/null
DMG_MOUNTED=true
test -d "$MOUNT_POINT/FolioOrb.app"
test -L "$MOUNT_POINT/Applications"
test "$(readlink "$MOUNT_POINT/Applications")" = "/Applications"
test -L "$MOUNT_POINT/FolioSenseAI.app"
test "$(readlink "$MOUNT_POINT/FolioSenseAI.app")" = "FolioOrb.app"
hdiutil detach "$MOUNT_POINT" -quiet
DMG_MOUNTED=false
rmdir "$MOUNT_POINT" "$MOUNT_ROOT"
trap - EXIT
rm -rf -- "$STAGE_ROOT"

if [[ "$CREATE_DMG_STATUS" != "0" ]]; then
  echo "create-dmg exited ${CREATE_DMG_STATUS}, but the exact image passed structural verification." >&2
fi
echo "Built and verified $OUTPUT_DMG"
