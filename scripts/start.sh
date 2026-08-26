#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${FOLIOORB_DATA_DIR:-}" && -f .source-profile-path ]]; then
  IFS= read -r FOLIOORB_DATA_DIR < .source-profile-path
  export FOLIOORB_DATA_DIR
fi
PROFILE_DIR="${FOLIOORB_DATA_DIR:-.}"

if [[ ! -d venv ]]; then
  echo "No virtual environment found. Run ./scripts/setup.sh first."
  exit 1
fi

source venv/bin/activate
mkdir -p "$PROFILE_DIR/database"

echo "Starting FolioOrb at http://localhost:8000"
python run.py
