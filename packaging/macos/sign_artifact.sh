#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" != "3" ]]; then
  echo "usage: $0 app|dmg ARTIFACT EXPECTED_TEAM_ID" >&2
  exit 2
fi

ARTIFACT_KIND="$1"
ARTIFACT="$2"
EXPECTED_TEAM_ID="$3"
if [[ "$ARTIFACT_KIND" != "app" && "$ARTIFACT_KIND" != "dmg" ]]; then
  echo "Artifact kind must be app or dmg." >&2
  exit 2
fi
if [[ "$ARTIFACT_KIND" == "app" && ! -d "$ARTIFACT" ]]; then
  echo "The exact app bundle is missing." >&2
  exit 1
fi
if [[ "$ARTIFACT_KIND" == "dmg" && ! -f "$ARTIFACT" ]]; then
  echo "The exact DMG is missing." >&2
  exit 1
fi
if [[ -z "${MACOS_DEVELOPER_ID_CERTIFICATE:-}" || -z "${MACOS_DEVELOPER_ID_PASSWORD:-}" ]]; then
  echo "MACOS_SIGNING_ENABLED=true requires both Developer ID secrets." >&2
  exit 1
fi
if [[ ! "$EXPECTED_TEAM_ID" =~ ^[A-Z0-9]{10}$ ]]; then
  echo "MACOS_DEVELOPER_TEAM_ID must be the expected 10-character Apple Team ID." >&2
  exit 1
fi

umask 077
SIGNING_ROOT="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/folioorb-signing.XXXXXX")"
KEYCHAIN_PATH="$SIGNING_ROOT/developer-id.keychain-db"
CERTIFICATE_PATH="$SIGNING_ROOT/developer-id.p12"
export CERTIFICATE_PATH
cleanup() {
  rm -f -- "$CERTIFICATE_PATH"
  if [[ -f "$KEYCHAIN_PATH" ]]; then
    security delete-keychain "$KEYCHAIN_PATH" || true
    rm -f -- "$KEYCHAIN_PATH"
  fi
  rmdir "$SIGNING_ROOT" 2>/dev/null || true
}
trap cleanup EXIT

python - <<'PY'
import base64
import binascii
import os
from pathlib import Path

try:
    certificate = base64.b64decode(
        os.environ["MACOS_DEVELOPER_ID_CERTIFICATE"], validate=True
    )
except (KeyError, ValueError, binascii.Error) as exc:
    raise SystemExit("MACOS_DEVELOPER_ID_CERTIFICATE is not valid base64") from exc
if not certificate:
    raise SystemExit("MACOS_DEVELOPER_ID_CERTIFICATE decoded to an empty file")
Path(os.environ["CERTIFICATE_PATH"]).write_bytes(certificate)
PY

KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"
echo "::add-mask::${KEYCHAIN_PASSWORD}"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 300 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security import "$CERTIFICATE_PATH" -k "$KEYCHAIN_PATH" \
  -P "$MACOS_DEVELOPER_ID_PASSWORD" -T /usr/bin/codesign
rm -f -- "$CERTIFICATE_PATH"
security set-key-partition-list -S apple-tool:,apple: -s \
  -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

IDENTITIES="$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" \
  | awk -F'"' -v suffix="(${EXPECTED_TEAM_ID})" \
    '/Developer ID Application:/ && index($2, suffix) == length($2) - length(suffix) + 1 {print $2}')"
IDENTITY_COUNT="$(printf '%s\n' "$IDENTITIES" | sed '/^$/d' | wc -l | tr -d ' ')"
if [[ "$IDENTITY_COUNT" != "1" ]]; then
  echo "Expected exactly one valid Developer ID Application identity for team ${EXPECTED_TEAM_ID}; found ${IDENTITY_COUNT}." >&2
  exit 1
fi
IDENTITY="$(printf '%s\n' "$IDENTITIES" | sed -n '1p')"
unset MACOS_DEVELOPER_ID_CERTIFICATE MACOS_DEVELOPER_ID_PASSWORD

if [[ "$ARTIFACT_KIND" == "app" ]]; then
  codesign --force --deep --all-architectures --timestamp --options runtime \
    --entitlements packaging/macos/FolioOrb.entitlements \
    --keychain "$KEYCHAIN_PATH" --sign "$IDENTITY" "$ARTIFACT"
  codesign --verify --deep --strict --verbose=2 "$ARTIFACT"
else
  codesign --force --timestamp --keychain "$KEYCHAIN_PATH" \
    --sign "$IDENTITY" "$ARTIFACT"
  codesign --verify --strict --verbose=2 "$ARTIFACT"
fi

DISPLAY="$(codesign --display --verbose=4 "$ARTIFACT" 2>&1)"
printf '%s\n' "$DISPLAY" | grep -F "Authority=Developer ID Application:"
ACTUAL_TEAM_ID="$(printf '%s\n' "$DISPLAY" | sed -n 's/^TeamIdentifier=//p')"
if [[ "$ACTUAL_TEAM_ID" != "$EXPECTED_TEAM_ID" ]]; then
  echo "Signed artifact team ${ACTUAL_TEAM_ID:-missing} does not match the expected Team ID." >&2
  exit 1
fi
