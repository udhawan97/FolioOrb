#!/usr/bin/env bash
# Regenerate the landing-page product-demo video loops from the real app.
#
# Reproducible pipeline: seed a throwaway demo database → boot the app on it →
# drive Playwright to record .webm → trim/encode to MP4/WebM + poster in
# docs-site/public/assets/demos/. Dev-only; only the optimized outputs ship.
#
# Playwright is intentionally NOT a committed dependency (its postinstall pulls
# a ~150 MB browser, which would bloat every Pages deploy). ffmpeg must be
# installed (brew install ffmpeg). Install the tooling once before running:
#     cd docs-site && npm i -D playwright && npx playwright install chromium
#
# Usage:  ./docs-site/scripts/record_demos.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PORT="${SHOT_PORT:-8177}"
TMP_PARENT="${TMPDIR:-/tmp}"
TMP_PARENT="${TMP_PARENT%/}"
TMP_DIR="$(mktemp -d "$TMP_PARENT/folioorb-demos.XXXXXX")"
RAW_DIR="$REPO_ROOT/docs-site/_demos/raw"
APP_PID=""
# Install cleanup before seeding: set -e may exit on any later command.
cleanup() {
  if [[ -n "$APP_PID" ]]; then
    kill "$APP_PID" 2>/dev/null || true
  fi
  case "$TMP_DIR" in
    "$TMP_PARENT"/folioorb-demos.*) rm -rf -- "$TMP_DIR" ;;
    *) echo "Refusing to remove unexpected demo path: $TMP_DIR" >&2 ;;
  esac
  case "$RAW_DIR" in
    "$REPO_ROOT"/docs-site/_demos/raw) rm -rf -- "$RAW_DIR" ;;
    *) echo "Refusing to remove unexpected raw-demo path: $RAW_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

export FOLIOORB_DATA_DIR="$TMP_DIR/data"
mkdir -p "$FOLIOORB_DATA_DIR"
chmod 700 "$FOLIOORB_DATA_DIR"
DB_PATH="$FOLIOORB_DATA_DIR/demo.db"
export DATABASE_URL="sqlite:///$DB_PATH"
export ANTHROPIC_API_KEY=""
export DEFAULT_HOLDINGS=""
export DEBUG="False"

PY="python"
[[ -x "$REPO_ROOT/venv/bin/python" ]] && PY="$REPO_ROOT/venv/bin/python"

echo "→ Seeding demo portfolio…"
"$PY" docs-site/scripts/seed_demo.py

echo "→ Booting app on port $PORT…"
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning &
APP_PID=$!

echo "→ Waiting for health…"
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
# Warm the caches so recorded panels aren't mid-fetch.
curl -sf "http://127.0.0.1:$PORT/api/portfolio/value?portfolio_id=1" >/dev/null 2>&1 || true
sleep 2

echo "→ Recording demos…"
( cd docs-site && SHOT_BASE_URL="http://127.0.0.1:$PORT" node scripts/record_demos.mjs )

echo "→ Encoding demos…"
docs-site/scripts/encode_demos.sh

echo "✓ Done. Demo loops in docs-site/public/assets/demos/"
