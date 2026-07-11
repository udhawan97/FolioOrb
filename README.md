<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="static/img/brand/folio-orbit-mark-light-animated.svg">
    <source media="(prefers-color-scheme: light)" srcset="static/img/brand/folio-orbit-mark-dark-animated.svg">
    <img src="static/img/brand/folio-orbit-mark-dark-animated.svg" alt="FolioOrb" width="285">
  </picture>
</p>

<h1 align="center">FolioOrb</h1>

<p align="center"><em>Your folio, finally making sense.</em></p>

<p align="center">
  A portfolio dashboard that pulls in your holdings, live market data, risk signals, and news,<br>
  then gives you plain hold, trim, or exit calls — with the reasoning laid out, not just a verdict.
</p>

<p align="center">
  <strong>Runs entirely on your machine</strong> — use it in your browser as a local web app, or install it as a
  <br>desktop app on macOS or Windows. No account, no cloud, nothing phones home.
</p>

<p align="center">
  <a href="https://udhawan97.github.io/FolioOrb/">
    <img src="static/img/brand/visit-website.svg" alt="Explore the live website — real product demos, downloads, and docs" width="440">
  </a>
</p>

<p align="center">
  <sub><a href="https://udhawan97.github.io/FolioOrb/"><strong>udhawan97.github.io/FolioOrb</strong></a> — watch the dashboard work, then run it yourself.</sub>
</p>

<p align="center">
  <a href="https://github.com/udhawan97/FolioOrb/releases/latest"><img src="https://img.shields.io/github/v/release/udhawan97/FolioOrb?style=flat-square&color=brightgreen" alt="Latest release"></a>
  <a href="https://github.com/udhawan97/FolioOrb/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/udhawan97/FolioOrb/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
  <a href="https://github.com/udhawan97/FolioOrb/releases"><img src="https://img.shields.io/github/downloads/udhawan97/FolioOrb/total?style=flat-square&color=blue" alt="Downloads"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Windows%20%C2%B7%20Linux-555?style=flat-square" alt="macOS, Windows, Linux">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-blue?style=flat-square" alt="Apache 2.0 License"></a>
</p>

<p align="center">
  <a href="#run-it-your-way">🚀 Run it</a> ·
  <a href="#what-it-does">🧠 Features</a> ·
  <a href="https://udhawan97.github.io/FolioOrb/">🌐 Website &amp; Docs</a> ·
  <a href="#for-developers">🛠️ Developers</a>
</p>

---

## Run It Your Way

FolioOrb is the same dashboard whichever way you launch it — a local server that renders in a browser view. Pick what fits you:

| | 🌐 Web app | 🖥️ Desktop app |
| --- | --- | --- |
| **What you get** | Run it from source; use it in your browser at `localhost:8000` | A ready-to-run installer that opens the dashboard in its own window |
| **You need** | Python 3.11+ | Nothing — it's fully self-contained |
| **Platforms** | macOS · Windows · Linux | macOS (Apple Silicon) · Windows (x64) |
| **Get started** | [Setup ↓](#setup) | Download below |

**Desktop downloads** — no Python, no terminal:

| Platform | Download | Install guide |
| --- | --- | --- |
| **macOS** (Apple Silicon) | [**Download .dmg**](https://github.com/udhawan97/FolioOrb/releases/latest) | [Install on macOS](https://udhawan97.github.io/FolioOrb/install-macos/) |
| **Windows** (x64) | [**Download .exe**](https://github.com/udhawan97/FolioOrb/releases/latest) | [Install on Windows](https://udhawan97.github.io/FolioOrb/install-windows/) |

> **Heads up:** early builds aren't code-signed yet, so the first launch shows a warning on both macOS and Windows — expected for an open-source app. The [install guides](https://udhawan97.github.io/FolioOrb/download/) show exactly what you'll see, and every release ships a `SHA256SUMS.txt` so you can [verify your download](https://udhawan97.github.io/FolioOrb/download/#verify-your-download).

## What It Does

Most portfolio trackers stop at the number. Green means good, red means bad — and if you want to know *why*, that's a separate tab, a separate app, or a group chat with someone who read the news this morning and you didn't.

FolioOrb closes that gap: holdings, live prices, risk math, market regime, news, and optional Claude-written narration, all in one place that runs on your own machine and reports to nobody. It doesn't connect to a brokerage and it doesn't place trades — but it will tell you, with a straight face, whether your "diversified" portfolio is actually just four tech stocks in a trench coat.

| Do this | Get this |
| --- | --- |
| 📊 Add holdings and watchlist tickers | Live value, cost basis, daily change, unrealized gain, and allocation |
| 🧭 Open a ticker | A Hold / Add / Trim / Exit verdict with confidence, horizon, and scenario context |
| ✅ Check the action plan | Bucketed portfolio moves with thesis text, priorities, and regime context |
| 📈 Open Analytics | Performance, risk, exposure, beta, drawdown, volatility, sector tilt, and signals |
| 🗞️ Open News | Grouped headlines for everything you hold or watch, plus optional Claude themes |
| 📥 Import / export CSV | Move holdings in and out — a strict template locally, or let Claude map a messy brokerage export onto it |
| 🔐 Paste a Claude key | The dashboard validates it, writes `.env`, and reconnects — no restart |

> **Local Intelligence is not a downgraded mode.** It's the deterministic engine that runs the dashboard by default. Claude adds narration *on top* — it never gates the core experience, and everything it generates is cached in SQLite so refreshing doesn't mean paying again.

<p align="center">
  <img src="docs/dashboard.webp" alt="The FolioOrb dashboard showing a demo portfolio: total value, today's P&amp;L, sector map, and today's impact" width="820">
  <br>
  <sub><em>The real dashboard, running a demo portfolio. Local market context, optional Claude explanations. Still not financial advice. Very much a dashboard.</em></sub>
</p>

## Meet Senpai

<img src="static/img/brand/folio-orbit-icon.svg" alt="Senpai" width="54" align="left">

**Senpai** is the small orbiting mark in the corner of the dashboard — it watches your portfolio so you don't have to stare at it alone. It reads the room: sharp when Claude is narrating, dry on Local Intelligence, quietly sympathetic when Claude is offline. Tap it for a new line; it also talks on its own, whether you asked it to or not. Senpai doesn't manage your portfolio. Senpai has *opinions* about your portfolio. [Say hello →](https://udhawan97.github.io/FolioOrb/meet-senpai/)

<br clear="left">

## Setup

Two ways to run FolioOrb — the same app either way. Your holdings and `.env` are always kept out of the app itself, so updates and reinstalls never touch your data.

<details open>
<summary><strong>🌐 Run as a web app — from source (macOS · Windows · Linux)</strong></summary>

<br>

Needs **Python 3.11+**. Clone, run the setup script once, and the dashboard opens in your browser:

```bash
git clone https://github.com/udhawan97/FolioOrb.git
cd FolioOrb
./scripts/setup.sh          # Windows (PowerShell): .\scripts\setup.ps1
```

The setup script creates a virtual environment, installs dependencies, writes a local `.env`, prepares `database/`, and starts the app at <http://localhost:8000>. After the first run, start it any time with `./scripts/start.sh` (or `.\scripts\start.ps1`) and open that URL in any browser.

</details>

<details>
<summary><strong>🖥️ Install the desktop app (macOS · Windows)</strong></summary>

<br>

No Python required — the installer bundles everything and runs the same dashboard in its own window:

- **macOS (Apple Silicon):** download the [`.dmg`](https://github.com/udhawan97/FolioOrb/releases/latest), open it, and drag **FolioOrb** to Applications. [Full guide](https://udhawan97.github.io/FolioOrb/install-macos/)
- **Windows (x64):** download the [`.exe`](https://github.com/udhawan97/FolioOrb/releases/latest) and run the installer. [Full guide](https://udhawan97.github.io/FolioOrb/install-windows/)

The app checks for updates in the background and installs them only with your go-ahead. Your database and `.env` live in your per-user data directory, never inside the app.

</details>

<details>
<summary><strong>⚡ One-line install (web app, from source)</strong></summary>

<br>

Downloads the latest release and sets up a local Python environment for you. Read the scripts first — they're short: [mac](scripts/install-mac.sh) · [win](scripts/install-win.ps1).

```bash
curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioOrb/main/scripts/install-mac.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/udhawan97/FolioOrb/main/scripts/install-win.ps1 | iex
```

Set `FOLIO_REF` (e.g. `latest-main`) to install a specific tag or the dev channel.

</details>

<details>
<summary><strong>🔐 Optional: connect Claude</strong></summary>

<br>

FolioOrb works fully without Claude — Local Intelligence handles verdicts, analytics, and summaries on its own. To add Claude-powered briefings and action plans, provide an Anthropic key either in the dashboard (click the brand mark, paste an `sk-ant-*` key) or in `.env` (`ANTHROPIC_API_KEY=...`, then restart). The key format is validated before it's saved.

</details>

## 🔭 What's Brewing

FolioOrb already earns a place on your machine — but this is very much the opening chapter, and the lab is open. Here's what's *on the radar* for future releases. Think of it as a sneak peek through the workshop window, not a pinky promise carved in stone.

| | On the radar | The gist | Status |
| --- | --- | --- | --- |
| ⚖️ | **Target weights & drift** | Set the mix you're aiming for, then see at a glance how far today's prices have nudged you off plan. | Next up in the lab |
| 🗂️ | **More than one portfolio** | Give your retirement account and your fun-money account their own separate scoreboards. | On the radar |
| 🧾 | **Tax-season trade export** | Hand your accountant a tidy CSV of every closed trade — the detail behind the year-end recap. | Next up in the lab |
| 💸 | **Income & dividends view** | See what your portfolio pays *you* back for the privilege of holding it. | Being explored |
| 🔮 | **A what-if simulator** | Preview a buy or a trim *before* you touch anything real. Regret-free rehearsals. | Being explored |

> **The fine print, minus the lawyers:** This roadmap is less of a blood oath and more of a friendly sneak peek. FolioOrb is built part-time, so priorities may shift and exact dates are deliberately missing in action — but the direction is clear: more useful, more polished, more delightful, one release at a time.

Got a feature you'd fight for? [Open an issue](https://github.com/udhawan97/FolioOrb/issues/new) — Senpai reads every one and has opinions about most.

## For Developers

A compact FastAPI + SQLite + vanilla-JS app with no frontend build step — easy to run and pull apart one service at a time. It's a plain web app at heart; the desktop builds just wrap that same app in a native window.

<details>
<summary><strong>Setup, run, and quality checks</strong></summary>

<br>

```bash
python3 -m venv venv && source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python run.py                       # http://localhost:8000

# Quality checks
python -m compileall -q app run.py tests
python -m pytest -q
python -m pylint $(git ls-files '*.py')
```

| URL | Purpose |
| --- | --- |
| `http://localhost:8000` | Dashboard |
| `http://localhost:8000/docs` | Interactive Swagger API docs |
| `http://localhost:8000/health` | Health check |

</details>

<details>
<summary><strong>Architecture &amp; project layout</strong></summary>

<br>

```mermaid
flowchart LR
    browser["Browser dashboard<br>HTML, CSS, vanilla JS, Chart.js"]
    api["FastAPI app<br>routers, middleware, static serving"]
    services["Service layer<br>signals, analytics, news, AI, market data"]
    db["SQLite<br>holdings, snapshots, AI cache, verdict history"]
    yahoo["Yahoo Finance<br>prices, history, headlines"]
    claude["Anthropic Claude<br>optional narration and plans"]

    browser <--> api
    api <--> services
    services <--> db
    services <--> yahoo
    services -. optional .-> claude
```

The browser view is identical whether you open `localhost:8000` yourself or launch the desktop app — the desktop build (PyInstaller + pywebview) runs the same FastAPI server in-process behind a native window.

| Layer | Stack |
| --- | --- |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Data | SQLite, SQLAlchemy 2, Pydantic 2 |
| Market data | `yfinance` / Yahoo Finance |
| AI | Anthropic SDK (optional), local deterministic fallback |
| Frontend | Single HTML shell, Bootstrap 5, Chart.js, vanilla JS |
| Desktop | PyInstaller + pywebview → DMG (create-dmg) / EXE (Inno Setup) |
| Quality | pytest, Pylint, pip-audit, CodeQL, Dependency Review |

```text
app/            FastAPI app, config, DB, models, schemas, routers/, services/
desktop/        Desktop entry point (uvicorn + native window)
templates/      Dashboard HTML shell
static/         CSS, JS, brand assets
packaging/      PyInstaller spec, Inno Setup script, app icons
scripts/        Setup, start, install, and icon-generation scripts
tests/          Offline-focused pytest suite with mocked external services
docs-site/      Astro + Starlight docs + landing page
```

</details>

<details>
<summary><strong>Build the desktop installers</strong></summary>

<br>

```bash
python -m pip install -r requirements.txt -r requirements-desktop.txt
python -m PyInstaller packaging/pyinstaller/FolioOrb.spec
python packaging/pyinstaller/fix_macos_bundle_symlinks.py dist   # macOS only
# Smoke-test the frozen bundle:
#   macOS:   dist/FolioOrb.app/Contents/MacOS/FolioOrb --smoke
#   Windows: dist\FolioOrb\FolioOrb.exe --smoke
```

Then `create-dmg` (macOS) or `iscc` (Windows) wrap it into an installer. Full commands: [Build from source](https://udhawan97.github.io/FolioOrb/build-from-source/#build-the-desktop-installers).

</details>

## Release Workflow

Version lives in one place — `app/version.py`. Pushing a `v*` tag builds both desktop installers on native GitHub runners, smoke-tests each frozen bundle, and only then publishes the DMG, EXE, and `SHA256SUMS.txt` to a GitHub Release. A red build never replaces a good release. Every merge to `main` also refreshes a rolling `latest-main` prerelease for testing.

```
main merge / v* tag → tests → build macOS + Windows → smoke test → GitHub Release → website buttons
```

Details and the code-signing roadmap: [Releases &amp; versioning](https://udhawan97.github.io/FolioOrb/releases-and-versioning/).

## Troubleshooting

<details>
<summary><strong>Common first-launch issues (desktop app)</strong></summary>

<br>

| Symptom | Fix |
| --- | --- |
| macOS: *"Apple cannot check it for malicious software"* | Expected (unsigned). **System Settings → Privacy &amp; Security → Open Anyway**. [Steps](https://udhawan97.github.io/FolioOrb/install-macos/#first-launch-the-gatekeeper-warning) |
| Windows: *"Windows protected your PC"* (SmartScreen) | Click **More info → Run anyway**. [Steps](https://udhawan97.github.io/FolioOrb/install-windows/#first-launch-the-smartscreen-warning) |
| Windows: blank window | Install the [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/) and relaunch |
| Is my download genuine? | [Verify](https://udhawan97.github.io/FolioOrb/download/#verify-your-download) against the release's `SHA256SUMS.txt` |
| Data missing after update | It isn't — data lives outside the app, in your user data directory |

More setup and runtime help: [Troubleshooting &amp; FAQ](https://udhawan97.github.io/FolioOrb/troubleshooting/).

</details>

## Privacy

FolioOrb is local-first, not cloud-hosted. Holdings and snapshots live in local SQLite; config and API keys live in a local `.env` that's excluded from git. Market data is requested from Yahoo Finance; Claude prompts are sent to Anthropic *only* when you enable Claude features. Generated AI summaries are cached locally. Full detail: [Privacy &amp; data handling](https://udhawan97.github.io/FolioOrb/privacy/).

## Contributing

Issues and pull requests are welcome. For a feature, a short issue describing the use case before the PR saves a round trip. Keep changes scoped, run the quality checks above, and don't be surprised if Senpai has opinions about your diff.

## License

Released under the [Apache License 2.0](LICENSE). This project is for education, analysis, and portfolio exploration. It is **not financial advice**, does not place trades, and is not a substitute for professional judgment.

<p align="center">
  <sub>Built to make portfolio context easier to read, easier to question, and slightly less spreadsheet-haunted.<br>
  If FolioOrb talked you out of panic-selling on a red Tuesday, a star costs nothing and Senpai will absolutely take credit for it.</sub>
</p>
