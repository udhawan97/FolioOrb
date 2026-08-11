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

PORT="${SHOT_PORT:-8177}"
TMP_DIR="$REPO_ROOT/docs-site/_shots"
DB_PATH="$TMP_DIR/demo.db"
export DATABASE_URL="sqlite:///$DB_PATH"
export ANTHROPIC_API_KEY=""
export DEFAULT_HOLDINGS=""
export DEBUG="False"
export FOLIO_DISABLE_UPDATE_SCHEDULER="1"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

# Prefer the project venv if present.
PY="python"
[[ -x "$REPO_ROOT/venv/bin/python" ]] && PY="$REPO_ROOT/venv/bin/python"

echo "→ Seeding demo portfolio…"
"$PY" docs-site/scripts/seed_demo.py

echo "→ Booting app on port $PORT…"
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning &
APP_PID=$!
trap 'kill "$APP_PID" 2>/dev/null || true; rm -rf "$TMP_DIR"' EXIT

echo "→ Waiting for health…"
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "→ Capturing screenshots…"
( cd docs-site && SHOT_BASE_URL="http://127.0.0.1:$PORT" node scripts/capture_shots.mjs )

echo "✓ Done. Assets in docs-site/public/assets/shots/ and docs/plan-protect.webp"
