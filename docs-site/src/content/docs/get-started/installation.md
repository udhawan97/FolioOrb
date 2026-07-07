---
title: Installation
description: Get FolioSenseAI running locally on Mac, Linux, or Windows.
---

FolioSenseAI runs on your computer as a local web app at `http://localhost:8000`.

## Prerequisites

- Python 3.11 or newer from [python.org](https://www.python.org/downloads/)
- Internet access for market data from Yahoo Finance through `yfinance`
- Optional: an Anthropic API key for Claude-powered briefings and action plans

## Mac / Linux

```bash
git clone https://github.com/udhawan97/FolioSenseAI.git
cd FolioSenseAI
./scripts/setup.sh
```

## Windows PowerShell

```powershell
git clone https://github.com/udhawan97/FolioSenseAI.git
cd FolioSenseAI
.\scripts\setup.ps1
```

The setup script creates a virtual environment, installs dependencies, creates local
config if needed, prepares the `database/` folder, and starts the app.

## Day-to-day use

Once setup has run once:

```bash
./scripts/start.sh
```

```powershell
.\scripts\start.ps1
```

Keep the terminal window open while using FolioSenseAI — closing it stops the local server.

## Manual developer setup

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
mkdir -p database
python run.py
```

## Useful local URLs

| URL | Purpose |
| --- | --- |
| `http://localhost:8000` | Dashboard |
| `http://localhost:8000/docs` | Interactive Swagger API docs |
| `http://localhost:8000/health` | Health check |

## Updating

```bash
git pull
python -m pip install -r requirements.txt
python run.py
```

The install scripts preserve existing `.env` and `database/` files, so re-running the
installer is safe.
