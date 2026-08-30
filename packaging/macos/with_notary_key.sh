#!/bin/bash

# Materialize the App Store Connect private key only for one notary submission.
# Each workflow invocation decodes, parses, uses, and removes its own temporary
# copy, so unrelated build, smoke, Homebrew, and packaging steps cannot read it.

set -euo pipefail

KIND="${1:-}"
ARTIFACT="${2:-}"

: "${MACOS_NOTARY_PRIVATE_KEY:?MACOS_NOTARY_PRIVATE_KEY is required}"
: "${FOLIOORB_NOTARY_KEY_ID:?FOLIOORB_NOTARY_KEY_ID is required}"
: "${FOLIOORB_NOTARY_ISSUER_ID:?FOLIOORB_NOTARY_ISSUER_ID is required}"

if [[ ! "$FOLIOORB_NOTARY_KEY_ID" =~ ^[A-Z0-9]{10,64}$ ]]; then
  echo "MACOS_NOTARY_KEY_ID must be an uppercase alphanumeric App Store Connect key ID of at least 10 characters." >&2
  exit 2
fi
if [[ ! "$FOLIOORB_NOTARY_ISSUER_ID" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]]; then
  echo "MACOS_NOTARY_ISSUER_ID must be the App Store Connect issuer UUID." >&2
  exit 2
fi

umask 077
NOTARY_KEY_PATH="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/folioorb-notary-key.XXXXXX")"
export NOTARY_KEY_PATH

cleanup() {
  rm -f "$NOTARY_KEY_PATH"
}
trap cleanup EXIT

python - <<'PY'
import base64
import binascii
import os
from pathlib import Path

try:
    private_key = base64.b64decode(
        os.environ["MACOS_NOTARY_PRIVATE_KEY"], validate=True
    )
except (KeyError, ValueError, binascii.Error) as exc:
    raise SystemExit("MACOS_NOTARY_PRIVATE_KEY is not valid base64") from exc
if not private_key:
    raise SystemExit("MACOS_NOTARY_PRIVATE_KEY decoded to an empty file")
if not (
    private_key.startswith(b"-----BEGIN PRIVATE KEY-----")
    and private_key.rstrip().endswith(b"-----END PRIVATE KEY-----")
):
    raise SystemExit("MACOS_NOTARY_PRIVATE_KEY is not a PKCS#8 PEM private key")
Path(os.environ["NOTARY_KEY_PATH"]).write_bytes(private_key)
PY

unset MACOS_NOTARY_PRIVATE_KEY
if ! openssl pkey -in "$NOTARY_KEY_PATH" -noout >/dev/null 2>&1; then
  echo "MACOS_NOTARY_PRIVATE_KEY is not a parseable private key." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FOLIOORB_NOTARY_KEY_PATH="$NOTARY_KEY_PATH" \
  "$SCRIPT_DIR/notarize_artifact.sh" "$KIND" "$ARTIFACT"
