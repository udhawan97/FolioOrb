#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK=false
UPGRADE_ARGS=(--upgrade)
LOCK_FILES=(
  requirements-desktop-macos.lock
  requirements-release-test-linux.lock
  requirements-desktop-windows.lock
)

if [[ "${1:-}" == "--check" ]]; then
  # Validate committed resolutions against current inputs, not today's latest
  # transitive releases. Normal invocation remains an explicit upgrade refresh.
  CHECK=true
  UPGRADE_ARGS=()
  OUTPUT_DIR="$(mktemp -d)"
  trap 'rm -rf "$OUTPUT_DIR"' EXIT
  for lock in "${LOCK_FILES[@]}"; do
    # Reuse version preferences only: uv otherwise reuses committed hashes too,
    # which would let a bad hash validate itself instead of checking the index.
    sed -n '/^[[:alnum:]][[:alnum:]_.-]*==/ { s/ \\$//; p; }' \
      "$REPO_ROOT/$lock" > "$OUTPUT_DIR/$lock"
  done
else
  OUTPUT_DIR="${1:-$REPO_ROOT}"
fi

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
  ${UPGRADE_ARGS[@]+"${UPGRADE_ARGS[@]}"} \
  --generate-hashes \
  --output-file "$OUTPUT_DIR/requirements-desktop-macos.lock"

uv pip compile requirements.txt requirements-release-test.txt \
  --python-version 3.12 \
  --python-platform x86_64-manylinux_2_17 \
  ${UPGRADE_ARGS[@]+"${UPGRADE_ARGS[@]}"} \
  --generate-hashes \
  --output-file "$OUTPUT_DIR/requirements-release-test-linux.lock"

uv pip compile requirements.txt requirements-desktop.txt requirements-release-test.txt \
  --python-version 3.12 \
  --python-platform x86_64-pc-windows-msvc \
  ${UPGRADE_ARGS[@]+"${UPGRADE_ARGS[@]}"} \
  --generate-hashes \
  --output-file "$OUTPUT_DIR/requirements-desktop-windows.lock"

if [[ "$CHECK" == true ]]; then
  for lock in "${LOCK_FILES[@]}"; do
    diff -u "$REPO_ROOT/$lock" "$OUTPUT_DIR/$lock"
  done
fi
