#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

NO_START=0
if [[ "${1:-}" == "--no-start" ]]; then
  NO_START=1
fi

find_python() {
  for candidate in python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
      then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.11+ is required. Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

echo "Using $("$PYTHON_BIN" --version)"

if [[ ! -d venv ]]; then
  echo "Creating virtual environment..."
  "$PYTHON_BIN" -m venv venv
fi

source venv/bin/activate

echo "Installing dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p database

if [[ ! -f .env ]]; then
  SECRET_KEY="$(python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"

  ANTHROPIC_API_KEY=""
  if [[ -t 0 ]]; then
    printf "Anthropic API key for AI features (optional, press Enter to skip): "
    read -r ANTHROPIC_API_KEY
  fi

  cat > .env <<EOF
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
SECRET_KEY=${SECRET_KEY}
DEBUG=True
DATABASE_URL=sqlite:///./database/portfolio.db
CORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
DEFAULT_HOLDINGS=
EOF
  echo "Created .env with local defaults."
else
  echo "Using existing .env."
fi

if [[ "$NO_START" -eq 1 ]]; then
  echo "Setup complete. Start the app with ./scripts/start.sh"
  exit 0
fi

echo "Starting FolioOrb at http://localhost:8000"
python run.py
