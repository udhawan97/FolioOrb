#!/usr/bin/env bash
set -euo pipefail

DESTINATION_DIR="${1:?destination directory is required}"
VERSION="1.3.0"
EXPECTED_SHA256="c50d2bc97c3d6292642bac55f530d247eaf4bf65ee605f26b4caf339383e381c"
DESTINATION="$DESTINATION_DIR/create-dmg"
ARCHIVE="$DESTINATION_DIR/create-dmg-v${VERSION}.tar.gz"

mkdir -p "$DESTINATION_DIR"
curl --fail --silent --show-error --location \
  "https://github.com/create-dmg/create-dmg/archive/refs/tags/v${VERSION}.tar.gz" \
  --output "$ARCHIVE"
printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | shasum -a 256 --check
tar -xzf "$ARCHIVE" --strip-components=1 -C "$DESTINATION_DIR"
chmod 0755 "$DESTINATION"
