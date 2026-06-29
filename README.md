<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="static/img/brand/folio-orbit-mark-light.svg">
    <source media="(prefers-color-scheme: light)" srcset="static/img/brand/folio-orbit-mark-dark.svg">
    <img src="static/img/brand/folio-orbit-mark-dark.svg" alt="FolioSenseAI" width="285"/>
  </picture>
</p>

<h2 align="center">FolioSenseAI</h2>
<p align="center"><em>Your folio, finally making sense.</em></p>

<p align="center">
  <img src="https://img.shields.io/badge/release-v4.1-brightgreen?style=flat-square" alt="Release v4.1"/>
  <img src="https://img.shields.io/badge/tests-361%20passing-success?style=flat-square" alt="361 tests"/>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-0.136.3-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Claude-optional-D4A853?style=flat-square&logo=anthropic&logoColor=white" alt="Claude optional"/>
  <img src="https://img.shields.io/badge/SQLite-local-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite"/>
  <img src="https://img.shields.io/badge/Bootstrap-5.3.2-7952B3?style=flat-square&logo=bootstrap&logoColor=white" alt="Bootstrap"/>
  <img src="https://img.shields.io/badge/Chart.js-4.4.0-FF6384?style=flat-square&logo=chartdotjs&logoColor=white" alt="Chart.js"/>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="MIT License"/></a>
</p>

<p align="center">
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/ci.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/pylint.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/pylint.yml/badge.svg" alt="Pylint"/></a>
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/codeql.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"/></a>
</p>

---

<p align="center">
  <img src="docs/dashboard.png" alt="FolioSenseAI dashboard" width="860"/>
  <br/>
  <sub><em>Demo numbers. Real anxiety simulation.</em></sub>
</p>

<p align="center">
  <img src="docs/architecture.svg" alt="FolioSenseAI architecture" width="860"/>
</p>

---

FolioSenseAI is a **self-hosted portfolio intelligence dashboard** built on FastAPI + SQLite + vanilla JS. It turns live market data and a modular analytics engine into Hold / Add / Trim / Exit verdicts — optionally upgraded with Anthropic Claude narration when you bring a key. Runs entirely on your machine. No account. No subscription. No hot takes from the cloud unless you ask for them.

## Contents

- [What This Is](#-what-this-is)
- [Engineering Highlights](#-engineering-highlights)
- [Features](#-features)
- [Tech Stack](#️-tech-stack)
- [Install & Run](#-install--run)
- [Developer Setup](#-developer-setup)
- [Quality & CI](#-quality--ci)
- [Roadmap](#️-roadmap)
- [Contributing](#-contributing)
- [License & Disclaimer](#-license--disclaimer)

---

## ⚡ What This Is

| Audience | What you get |
| --- | --- |
| **Investors** | Live market context, a prioritised action plan, and Hold / Add / Trim / Exit verdicts with a thesis — not just a sparkline and a prayer |
| **Developers** | A production-patterned Python + FastAPI + SQLite project: 14+ modular services, mocked-service tests, a clean REST API, and no frontend framework tax. React was not harmed because it was never invited. |
| **Recruiters** | A full-stack AI/data product demonstrating API design, multi-layer caching, Anthropic SDK integration, analytics UX, CI/CD, and security hygiene — from scratch, in one repo |

<details>
<summary>📋 What's new in v4.1</summary>

- **In-dashboard API key panel** — click the brand mark, paste `sk-ant-*`, save. Key is validated client-side and server-side before touching disk. Server reconnects in-process. No terminal, no restart.
- **Live token cost tracking** — every Claude call accumulates real token counts. The cost HUD shows actual input/output tokens, a live cost figure, and a predicted per-run annotation — not a cache estimate.
- **Holdings table auto-refresh + first-click expand** — prices refresh on interval; rows expand on the very first click.
- **Sector graph proportional fills** — bars now scale relative to the top sector, with a `+N more` overflow note and a dot + track layout.

**From v4.0:** Portfolio Action Plan (Hold/Add/Trim/Exit with thesis, 24h cached), regime-aware context (SPY/TLT/VIX/UUP chip), News tab (live headlines + Claude cross-holding theme clusters).

**From v3.x:** `localStorage` instant table paint, shared `.info` cache across six services, background startup warmup, Overview/Holdings/Analytics zones, Base/Bull/Bear scenarios, look-through exposure, peer-relative positioning, earnings proximity flags.

</details>

---

## 🎯 Engineering Highlights

*The design decisions worth a second look, for anyone reading the code.*

**Dual-mode intelligence, single interface** — `/api/ai/*` serves both engines without branching at the route layer. The deterministic Local Intelligence engine (`investment_signal.py`, `market_regime.py`, `portfolio_exposure.py`, and friends) runs signals, scenarios, exposure, and regime analysis with zero external calls. Claude upgrades the same responses with narration when a key is present. No key = still fully functional. This isn't a placeholder fallback; it's the default mode for most users.

**Multi-layer caching with clear contracts** — quote prices are cached in-memory (60 s); Yahoo Finance `.info` is shared across six previously independent callers via `get_ticker_info()` (5 min market hours / 1 h closed); the holdings table paints from `localStorage` before the first HTTP response returns; AI responses persist to SQLite for 24 h with portfolio-drift invalidation so rebalancing clears a stale plan without manual intervention.

**Zero-restart API key configuration** — `POST /api/ai/configure-key` validates the key with `^sk-ant-[A-Za-z0-9_\-]{20,300}$` on both client and server, writes a single line to `.env`, and calls `reinitialize_client()` to hot-swap the Anthropic SDK client in-process. Uvicorn keeps running, the HUD mode chip flips from Local → Claude, and no terminal was opened.

**Frontend without a build step** — one HTML shell, vanilla JS, Bootstrap 5, Chart.js loaded from CDN. Analytics tabs instantiate Chart.js lazily on first activation. The design system is entirely CSS custom properties — no Sass, no PostCSS, no `node_modules`. The `localStorage` snapshot technique means the holdings table is interactive before the first API response lands.

**Modular, independently testable services** — each service has a single responsibility and is tested with mocked external calls, so the full suite runs offline and deterministically. `_collect_portfolio_signals_core()` is extracted and shared between the investment-signals endpoint and the action-plan endpoint to avoid computing the signal pipeline twice.

**361 tests, four CI checks** — pytest (mocked Yahoo Finance and Anthropic), Pylint, pip-audit (known CVE scanning), CodeQL (static analysis), dependency review, and a hygiene workflow that refuses secrets, databases, and OS noise. All checks run on Python 3.11 and 3.12.

---

## ✨ Features

### Dashboard zones

| Zone | What's there |
| --- | --- |
| **Overview** | Live P&L, weighted sector graph, market regime chip, portfolio briefing from Claude or Local Intelligence |
| **Holdings** | Per-ticker verdicts with confidence ranges and time horizons, move explanations, auto-refresh prices, expand for deep intelligence |
| **Analytics** | 5 sub-tabs — Performance, Risk, Exposure, Signals, Markets — with 20+ Chart.js widgets and per-chart AI insight lines |
| **News** | Live headlines for every holding, deduped and cached; Claude adds a portfolio briefing and cross-holding theme clusters |

<details>
<summary>📊 Analytics widgets</summary>

| Tab | Widgets |
| --- | --- |
| **Performance** | Return breakdown, cumulative P&L, projection vs S&P 500, benchmark tracker, monthly return heatmap |
| **Risk** | Risk/reward scatter, correlation matrix, HHI concentration score, max drawdown, beta, rolling volatility |
| **Exposure** | Sector tilt, geographic look-through, theme overlap |
| **Signals** | Conviction gap analysis, confidence spectrum |
| **Markets** | World index grid, macro alignment, geographic alignment |

Each tab has a per-tab AI insight bar and per-widget tip cards via `/api/ai/analytics-insights`. Widgets load lazily — only the active tab instantiates Chart.js.

</details>

### Intelligence engine

Every holding gets a verdict derived from benchmark, macro, sector, volume, and event context. Each verdict carries a confidence range, time horizon (`auto / trade / core / anchor`), and Base / Bull / Bear scenarios with probability bars.

<details>
<summary>🧬 How the engine is built</summary>

The core pipeline runs in `investment_signal.py` and calls out to modular services:

| Service | Responsibility |
| --- | --- |
| `investment_signal.py` | Core pipeline — horizon weights, confidence ranges, scenario builders, modifier hooks |
| `market_regime.py` | SPY/TLT/VIX/UUP regime detection, cached daily |
| `portfolio_exposure.py` | Look-through sector/country/theme, HHI concentration, duplicate detection |
| `peer_relative.py` | Own-range percentile vs peer median |
| `event_calendar.py` | Earnings proximity — 14-day flag, confidence cap |
| `verdict_calibration.py` | Snapshot logging for future hit-rate accountability |
| `verdict_ai_enhancement.py` | Claude tension gating — nudges only when inputs conflict; agreement skips the AI call |
| `holding_intelligence.py` | Deep per-ticker context, lazy-loaded on row expand |

Claude adds probability splits to scenarios and narrative quips when `force_local=False`. The gating logic means Claude is only invoked when it has something interesting to say — a signal conflict, an unusual scenario divergence — not on every request.

Verdict snapshots are logged to the `verdict_snapshots` SQLite table for future calibration reporting. The data is accumulating. The accountability will follow.

</details>

### Action Plan

Claude reads the full portfolio signal snapshot and returns a prioritised Hold / Add / Trim / Exit bucket plan with a thesis, top moves, and a market regime chip. Cached 24 h with portfolio-drift invalidation — rebalancing clears the stale plan automatically. Falls back to a deterministic local plan with plain-language headlines when Claude is unavailable.

<details>
<summary>🗂️ Caching strategy</summary>

| Layer | What | TTL |
| --- | --- | --- |
| In-memory (Python dict) | Yahoo Finance `.info` per ticker | 5 min (market hours) / 1 h (closed) |
| In-memory (Python dict) | Quote prices | 60 s |
| `localStorage` (browser) | Full holdings table snapshot | Until next successful live response |
| SQLite `ai_summaries` | Action Plan, briefing, analytics insights | 24 h with portfolio-drift invalidation |
| SQLite `verdict_snapshots` | Per-ticker verdict history | Persistent (calibration data) |

A daemon thread warms quotes, 1-year history closes, and world market data for all active holdings on server startup. The first real dashboard request hits a warm cache.

</details>

---

## 🏗️ Tech Stack

| Layer | Stack |
| --- | --- |
| **Backend** | Python 3.11+ · FastAPI 0.136.3 · Uvicorn 0.48.0 |
| **Data** | SQLite · SQLAlchemy 2.0.50 · Pydantic 2.13.4 |
| **Market Data** | yfinance 1.4.1 · Yahoo Finance |
| **AI** | Anthropic SDK 0.105.2 · Claude (optional) · Local Intelligence fallback |
| **Analytics** | pandas 3.0.3 · numpy 2.4.6 |
| **Frontend** | Bootstrap 5.3.2 · Bootstrap Icons · Chart.js 4.4.0 · Vanilla JS |
| **Quality** | pytest · Pylint · pip-audit · Dependency Review · CodeQL · security hygiene workflow |

<sub>No blockchain. No NFTs. No "AI agentic alpha swarm." We all survived.</sub>

---

## 🚀 Install & Run

FolioSenseAI runs entirely on your computer. No account needed, no data leaves your machine.

**One prerequisite:** Python 3.11+ — [download here](https://www.python.org/downloads/), click the yellow button, run the installer.

> **Windows only:** on the first installer screen, check **"Add Python to PATH"** before clicking Install.

### 🍎 Mac — one command

Open **Terminal** (⌘ Space → *Terminal* → Enter), paste, and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.1/scripts/install-mac.sh | bash
```

Downloads, installs, and places a **FolioSenseAI** shortcut on your Desktop. Browser opens automatically. **Next time:** double-click the Desktop shortcut.

### 🪟 Windows — one command

Open **PowerShell** (Win+R → `powershell` → Enter), paste, and press Enter:

```powershell
irm https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.1/scripts/install-win.ps1 | iex
```

Downloads, installs, and places a **FolioSenseAI** shortcut on your Desktop. Browser opens automatically. **Next time:** double-click the Desktop shortcut.

**Keep the Terminal / console window open while using the app — closing it stops the server.** Press Ctrl+C to stop.

### Claude API key (optional)

The app works fully offline with Local Intelligence. For Claude AI features — action plans, news briefings — click the **brand mark** in the top-left of the dashboard, paste your `sk-ant-*` key, and save. No restart required.

Get a key at [console.anthropic.com](https://console.anthropic.com/). Action Plan responses are cached 24 h so you won't be re-billed on every refresh.

### Updating

Run the install command again — it detects your existing `database/` and `.env`, preserves them, and starts the updated app.

<details>
<summary>🩹 Something not working?</summary>

| Symptom | Fix |
| --- | --- |
| `Python not found` | Install from [python.org](https://www.python.org/downloads/) and open a **new** terminal window. |
| Windows: `winget` fails | Install Python manually, check "Add to PATH", re-run the command. |
| Mac: `curl: command not found` | `xcode-select --install` — this shouldn't happen on modern macOS. |
| Mac: `bash: scripts/setup.sh: No such file or directory` | Your Desktop shortcut is outdated. Re-run the one-line install command above — it replaces the shortcut automatically. |
| Browser doesn't open | Navigate to [http://localhost:8000](http://localhost:8000) manually. |
| `localhost:8000` won't load | The terminal window must stay open — it is the server. |
| Port 8000 is busy | Stop the other app on that port, or change the port in `run.py`. |
| AI shows "Local" mode | Click the brand mark in the dashboard and paste your API key. |

</details>

<details>
<summary>⚙️ Manual install (advanced)</summary>

```bash
# Mac / Linux
curl -L -o FolioSenseAI.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v4.1.zip
unzip FolioSenseAI.zip && cd FolioSenseAI-release-v4.1
./scripts/setup.sh
```

```powershell
# Windows PowerShell
Invoke-WebRequest "https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v4.1.zip" -OutFile FolioSenseAI.zip
Expand-Archive FolioSenseAI.zip; cd FolioSenseAI-release-v4.1
.\scripts\setup.ps1
```

Daily start: `./scripts/start.sh` (Mac) or `.\scripts\start.ps1` (Windows).

</details>

---

## 👩‍💻 Developer Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
python run.py
```

| URL | Purpose |
| --- | --- |
| [`http://localhost:8000`](http://localhost:8000) | Dashboard |
| [`http://localhost:8000/docs`](http://localhost:8000/docs) | Interactive API docs (Swagger UI) |
| [`http://localhost:8000/health`](http://localhost:8000/health) | Health check |

<details>
<summary>🗂️ Project structure</summary>

```text
app/
├── main.py               — FastAPI app, middleware, static file serving, startup migrations
├── models.py             — SQLAlchemy ORM models
├── schemas.py            — Pydantic request/response contracts
├── routers/              — Route handlers: stocks, portfolio, ai, news
└── services/
    ├── stock_service.py          — quotes, history, world markets, shared .info cache
    ├── investment_signal.py      — core intelligence pipeline
    ├── holding_intelligence.py   — deep per-ticker context (lazy-loaded on expand)
    ├── ai_service.py             — Anthropic client, action_plan(), token tracking
    ├── news_service.py           — headline fetch, TTL cache, dedup
    ├── portfolio_analytics.py    — drawdown, beta, correlation, projection
    ├── portfolio_exposure.py     — look-through sector/country/theme, HHI
    ├── market_regime.py          — SPY/TLT/VIX/UUP regime detection
    ├── peer_relative.py          — own-range percentile vs peer median
    ├── event_calendar.py         — earnings proximity flags
    ├── verdict_calibration.py    — snapshot logging for hit-rate accountability
    ├── verdict_ai_enhancement.py — Claude tension gating
    └── ...
templates/
└── index.html            — single-page shell: four zones (Overview, Holdings, Analytics, News)
static/
├── js/                   — dashboard.js + analytics-charts.js
└── css/style.css         — design system via CSS custom properties
tests/                    — 361 tests; all external services mocked
scripts/                  — one-command install + start for Mac / Linux / Windows
```

</details>

<details>
<summary>🔌 API quick reference</summary>

| Group | Endpoints |
| --- | --- |
| **Market data** | `/api/stocks/prices`, `/api/stocks/history/{ticker}`, `/api/stocks/world-markets`, `/api/stocks/market-status` |
| **Portfolio** | `/api/portfolio/holdings`, `/api/portfolio/value`, `/api/portfolio/pnl`, `/api/portfolio/projection`, `/api/portfolio/risk-metrics`, `/api/portfolio/correlation` |
| **Analytics** | `/api/portfolio/drawdown`, `/api/portfolio/beta`, `/api/portfolio/rolling-volatility`, `/api/portfolio/sector-tilt`, `/api/portfolio/conviction-gaps`, `/api/portfolio/market-context` |
| **AI / Intelligence** | `/api/ai/investment-signals/all`, `/api/ai/portfolio-summary`, `/api/ai/portfolio-exposure`, `/api/ai/verdict-calibration`, `/api/ai/analytics-insights`, `/api/ai/intelligence/{ticker}/deep`, `/api/ai/action-plan`, `/api/ai/configure-key` |
| **News** | `/api/news/feed`, `/api/news/themes` |

Open [`/docs`](http://localhost:8000/docs) locally for the full interactive Swagger reference.

</details>

---

## 🧪 Quality & CI

```bash
python -m pytest -q
python -m compileall -q app run.py tests
python -m pylint $(git ls-files '*.py')
pip-audit -r requirements.txt
```

GitHub CI runs all checks on Python 3.11 and 3.12. Separate workflows cover Pylint, dependency audit/review, CodeQL static analysis, and a hygiene check that blocks secrets, databases, backups, and OS noise from the repo.

<details>
<summary>🔐 Local-first security model</summary>

- `.env` and `database/` are git-ignored; fresh installs start with an empty portfolio
- CORS defaults to local origins only
- API key is validated via regex on both client and server before touching disk; never logged
- Claude is optional and cached; Local Intelligence makes zero external AI calls
- Not a brokerage, advisor, oracle, or suspiciously confident uncle

</details>

---

## 🗺️ Roadmap

- [ ] CSV import / export
- [ ] Transaction history views
- [ ] Calibration reporting — the verdict snapshots are accumulating, but they need more history before the hit-rate numbers stop being anecdotal

---

## 🤝 Contributing

Issues and PRs welcome. For anything beyond a small fix, open an issue first to align on scope.

- `python -m pytest -q` and `python -m pylint $(git ls-files '*.py')` before submitting
- Keep changes focused — context lives in the PR description, not the code

---

## 📄 License & Disclaimer

Released under the [MIT License](LICENSE). Personal project, released for public use. **Not financial advice.** If you make or lose money because a dashboard on GitHub had nice colors, that is a fascinating life choice and also entirely on you.

<p align="center">
  Built with AI, caffeine, and a deeply normal interest in watching numbers move.<br/>
  ⭐ Star it if it helped you understand your portfolio — or if it at least insulted your diversification with better vocabulary than your last advisor.
</p>
