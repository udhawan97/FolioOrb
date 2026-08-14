#!/usr/bin/env bash
# Regenerate the landing-page product screenshots from the real app.
#
# Reproducible pipeline: seed a throwaway demo database → boot the app on it →
# drive Playwright at 2x → optimize to WebP in docs-site/public/assets/shots/.
# Dev-only; nothing here ships to the deployed site.
#
# Playwright is intentionally NOT a committed dependency (its postinstall pulls
# a ~150 MB browser, which would bloat the docs deploy). The generated .webp
# files are committed, so this script is only needed to regenerate them. Install
# the tooling once before running:
#     cd docs-site && npm i -D playwright && npx playwright install chromium
#
# Usage:  ./docs-site/scripts/capture.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Prefer the project venv if present.
PY="python"
[[ -x "$REPO_ROOT/venv/bin/python" ]] && PY="$REPO_ROOT/venv/bin/python"

TMP_PARENT="${TMPDIR:-/tmp}"
TMP_PARENT="${TMP_PARENT%/}"
TMP_DIR="$(mktemp -d "$TMP_PARENT/folioorb-shots.XXXXXX")"
APP_PID=""
cleanup() {
  if [[ -n "$APP_PID" ]]; then
    kill "$APP_PID" 2>/dev/null || true
  fi
  case "$TMP_DIR" in
    "$TMP_PARENT"/folioorb-shots.*) rm -rf -- "$TMP_DIR" ;;
    *) echo "Refusing to remove unexpected capture path: $TMP_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

export FOLIOORB_DATA_DIR="$TMP_DIR/data"
mkdir -p "$FOLIOORB_DATA_DIR"
DB_PATH="$FOLIOORB_DATA_DIR/demo.db"
export DATABASE_URL="sqlite:///$DB_PATH"
export ANTHROPIC_API_KEY=""
export DEFAULT_HOLDINGS=""
export DEBUG="False"
export FOLIO_DISABLE_UPDATE_SCHEDULER="1"
FOLIOORB_CAPTURE_TOKEN="$("$PY" -c 'import secrets; print(secrets.token_hex(16))')"
export FOLIOORB_CAPTURE_TOKEN

# A caller can pin a port, but the default asks the OS for a disposable one.
# The per-run health token below prevents us from ever accepting an unrelated
# FolioOrb process if another service wins the small bind race.
PORT="${SHOT_PORT:-}"
if [[ -z "$PORT" ]]; then
  PORT="$("$PY" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "Invalid SHOT_PORT: $PORT" >&2
  exit 1
fi

echo "→ Seeding demo portfolio…"
"$PY" docs-site/scripts/seed_demo.py

echo "→ Booting app on port ${PORT}…"
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning &
APP_PID=$!

echo "→ Waiting for health…"
READY=0
for _ in $(seq 1 30); do
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "Capture app exited before becoming ready; refusing to use another process." >&2
    wait "$APP_PID" || true
    exit 1
  fi
  if RESPONSE="$(curl -sf "http://127.0.0.1:$PORT/health" 2>/dev/null)"; then
    OBSERVED_TOKEN="$(
      printf '%s' "$RESPONSE" |
        "$PY" -c 'import json, sys; print(json.load(sys.stdin).get("capture_token", ""))' \
        2>/dev/null || true
    )"
    if [[ "$OBSERVED_TOKEN" == "$FOLIOORB_CAPTURE_TOKEN" ]]; then
      READY=1
      break
    fi
  fi
  sleep 1
done
if (( READY != 1 )); then
  echo "Capture app did not return this run's health token; refusing to capture." >&2
  exit 1
fi

echo "→ Capturing screenshots…"
( cd docs-site && SHOT_BASE_URL="http://127.0.0.1:$PORT" node scripts/capture_shots.mjs )
( cd docs-site && SHOT_BASE_URL="http://127.0.0.1:$PORT" node scripts/capture_v3.mjs )

echo "✓ Done. Assets in docs-site/public/assets/shots/ and docs/*.webp"
