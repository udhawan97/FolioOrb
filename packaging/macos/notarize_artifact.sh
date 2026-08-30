#!/bin/bash

# Submit one signed macOS artifact, require Apple's Accepted result, staple its
# ticket, and prove Gatekeeper recognizes the stapled artifact. The workflow
# calls this once for the app (before the DMG is assembled) and once for the
# signed DMG, so the copied app remains independently verifiable offline.

set -euo pipefail

KIND="${1:-}"
ARTIFACT="${2:-}"

if [[ "$KIND" != "app" && "$KIND" != "dmg" ]]; then
  echo "Usage: $0 <app|dmg> <artifact>" >&2
  exit 2
fi
if [[ -z "$ARTIFACT" || ! -e "$ARTIFACT" ]]; then
  echo "Notarization artifact does not exist: ${ARTIFACT:-missing}" >&2
  exit 2
fi

: "${FOLIOORB_NOTARY_KEY_PATH:?FOLIOORB_NOTARY_KEY_PATH is required}"
: "${FOLIOORB_NOTARY_KEY_ID:?FOLIOORB_NOTARY_KEY_ID is required}"
: "${FOLIOORB_NOTARY_ISSUER_ID:?FOLIOORB_NOTARY_ISSUER_ID is required}"

if [[ ! -r "$FOLIOORB_NOTARY_KEY_PATH" ]]; then
  echo "The App Store Connect API key is not readable." >&2
  exit 2
fi

WORK_ROOT="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/folioorb-notary.XXXXXX")"
RESULT_PATH="${WORK_ROOT}/submit-result.json"
LOG_PATH="${WORK_ROOT}/submission-log.json"
SUBMISSION_PATH="$ARTIFACT"

cleanup() {
  rm -rf "$WORK_ROOT"
}
trap cleanup EXIT

if [[ "$KIND" == "app" ]]; then
  SUBMISSION_PATH="${WORK_ROOT}/FolioOrb.zip"
  ditto -c -k --sequesterRsrc --keepParent "$ARTIFACT" "$SUBMISSION_PATH"
fi

set +e
xcrun notarytool submit "$SUBMISSION_PATH" \
  --key "$FOLIOORB_NOTARY_KEY_PATH" \
  --key-id "$FOLIOORB_NOTARY_KEY_ID" \
  --issuer "$FOLIOORB_NOTARY_ISSUER_ID" \
  --wait \
  --timeout 45m \
  --output-format json > "$RESULT_PATH"
SUBMIT_STATUS=$?
set -e

read -r SUBMISSION_ID NOTARY_STATUS < <(
  RESULT_PATH="$RESULT_PATH" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["RESULT_PATH"])
try:
    result = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("notarytool did not return a readable JSON result") from exc
print(result.get("id", ""), result.get("status", ""))
PY
)

printf 'Notarization submission %s finished with status %s.\n' \
  "${SUBMISSION_ID:-missing}" "${NOTARY_STATUS:-missing}"

LOG_STATUS=1
if [[ -n "$SUBMISSION_ID" ]]; then
  set +e
  xcrun notarytool log "$SUBMISSION_ID" \
    --key "$FOLIOORB_NOTARY_KEY_PATH" \
    --key-id "$FOLIOORB_NOTARY_KEY_ID" \
    --issuer "$FOLIOORB_NOTARY_ISSUER_ID" \
    "$LOG_PATH"
  LOG_STATUS=$?
  set -e
fi

if [[ "$SUBMIT_STATUS" -ne 0 || "$NOTARY_STATUS" != "Accepted" || -z "$SUBMISSION_ID" ]]; then
  if [[ -s "$LOG_PATH" ]]; then
    python -m json.tool "$LOG_PATH" || cat "$LOG_PATH"
  fi
  echo "Apple did not accept the $KIND artifact; refusing to staple or publish it." >&2
  exit 1
fi
if [[ "$LOG_STATUS" -ne 0 || ! -s "$LOG_PATH" ]]; then
  echo "The accepted submission log could not be downloaded; refusing to publish without its audit record." >&2
  exit 1
fi

LOG_PATH="$LOG_PATH" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["LOG_PATH"])
try:
    log = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("notarytool returned an unreadable submission log") from exc

issues = log.get("issues") or []
if log.get("status") != "Accepted" or issues:
    print(json.dumps(log, indent=2, sort_keys=True))
    raise SystemExit("notarization log was not clean and Accepted")
print("Notarization log is Accepted with no reported issues.")
PY

xcrun stapler staple -v "$ARTIFACT"
xcrun stapler validate "$ARTIFACT"

if [[ "$KIND" == "app" ]]; then
  ASSESS_ARGS=(--assess --type execute --verbose=4 "$ARTIFACT")
else
  ASSESS_ARGS=(--assess --type open --context context:primary-signature --verbose=4 "$ARTIFACT")
fi

set +e
ASSESSMENT="$(spctl "${ASSESS_ARGS[@]}" 2>&1)"
ASSESS_STATUS=$?
set -e
printf '%s\n' "$ASSESSMENT"
if [[ "$ASSESS_STATUS" -ne 0 ]] || ! grep -Fq "source=Notarized Developer ID" <<< "$ASSESSMENT"; then
  echo "Gatekeeper did not recognize the stapled $KIND as Notarized Developer ID." >&2
  exit 1
fi
