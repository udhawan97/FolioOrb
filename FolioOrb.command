#!/usr/bin/env bash
# Mac launcher — double-click this file to install (first run) and start FolioOrb.
# First time only: right-click → Open to bypass the macOS security prompt.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    osascript -e 'display alert "Python not found" message "Install Python 3.11+ from python.org, then double-click this file again." buttons {"OK"} default button "OK"'
    exit 1
fi

if [ ! -d venv ]; then
    echo "Setting up FolioOrb for the first time — this takes about a minute..."
    echo
    bash scripts/setup.sh --no-start
fi

echo
echo "Starting FolioOrb..."
echo "Your browser will open automatically at http://localhost:8000"
echo "Keep this window open while using the app.  Press Ctrl+C to stop."
echo
source venv/bin/activate
python run.py
