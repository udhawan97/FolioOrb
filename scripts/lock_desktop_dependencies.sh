#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to refresh the desktop dependency locks." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
cd "$REPO_ROOT"
export UV_CUSTOM_COMPILE_COMMAND="scripts/lock_desktop_dependencies.sh"

uv pip compile requirements.txt requirements-desktop.txt \
  --python-version 3.12 \
  --python-platform aarch64-apple-darwin \
  --generate-hashes \
  --output-file "$OUTPUT_DIR/requirements-desktop-macos.lock"

uv pip compile requirements.txt requirements-release-test.txt \
  --python-version 3.12 \
  --python-platform x86_64-manylinux_2_17 \
  --generate-hashes \
  --output-file "$OUTPUT_DIR/requirements-release-test-linux.lock"

uv pip compile requirements.txt requirements-desktop.txt requirements-release-test.txt \
  --python-version 3.12 \
  --python-platform x86_64-pc-windows-msvc \
  --generate-hashes \
  --output-file "$OUTPUT_DIR/requirements-desktop-windows.lock"
