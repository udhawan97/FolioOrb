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
  <img src="https://img.shields.io/badge/release-v3.1-brightgreen?style=flat-square" alt="Release v3.1"/>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-0.136.3-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Claude-optional-D4A853?style=flat-square&logo=anthropic&logoColor=white" alt="Claude optional"/>
  <img src="https://img.shields.io/badge/SQLite-local-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite"/>
  <img src="https://img.shields.io/badge/Bootstrap-5.3.2-7952B3?style=flat-square&logo=bootstrap&logoColor=white" alt="Bootstrap"/>
  <img src="https://img.shields.io/badge/Chart.js-4.4.0-FF6384?style=flat-square&logo=chartdotjs&logoColor=white" alt="Chart.js"/>
</p>

<p align="center">
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/ci.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/pylint.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/pylint.yml/badge.svg" alt="Pylint"/></a>
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/codeql.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"/></a>
</p>

---

> **v3.1** — FolioSenseAI turns a local portfolio into a live analytics cockpit: prices, P&L, exposure overlap, risk, market regime, AI/local verdicts, and scenario thinking. Now with a shared data cache that stops Yahoo Finance from explaining itself three times per load, an instant-paint holdings table from localStorage, and a background warmup thread so the first real fetch hits warm data. Still not financial advice. Slightly faster at the side-eye.

<p align="center">
  <img src="docs/dashboard.png" alt="FolioSenseAI dashboard" width="860"/>
  <br/>
  <sub><em>Demo numbers. Real anxiety simulation.</em></sub>
</p>

---

## Contents

- [Why It Exists](#-why-it-exists)
- [v3 Highlights](#-v3-highlights)
- [Tech Stack](#️-tech-stack)
- [Install, Run, Update](#-install-run-update)
- [Developer Notes](#-developer-notes)
- [Release Checks](#-release-checks)
- [Roadmap](#️-roadmap)
- [Contributing](#-contributing)
- [License & Disclaimer](#-license--disclaimer)

---

## ⚡ Why It Exists

FolioSenseAI is a self-hosted FastAPI dashboard for investors who want more than "line went down." It explains portfolio movement, tracks allocation and risk, and generates Add / Hold / Trim style intelligence using either **Anthropic Claude** or a deterministic **Local Intelligence** engine.

- **For Investors:** live market context, portfolio diagnostics, and enough witty copy to make volatility feel personally curated.
- **For Developers:** a Python + FastAPI + SQLite project with modular services, vanilla JS charts, mocked external-service tests, and no frontend framework tax. React was not harmed because it was never invited.
- **For Portfolio Builders:** a polished full-stack AI/data product demonstrating local-first privacy, API design, analytics UX, response caching, CI, and security hygiene.

---

## 🧠 v3.1 Highlights

**New in v3.1**

- **Instant holdings table** — `localStorage` snapshot of the last good portfolio response paints the table immediately on load; fresh prices replace it in place as they arrive
- **Shared `.info` cache** — all services (quotes, analyst recs, holding intelligence, earnings calendar, move explainer, ETF price signal) draw from one cached Yahoo Finance scrape per ticker instead of each making their own network call
- **Background startup warmup** — a daemon thread pre-fetches quotes, price history, and world markets for active holdings so the first real request hits warm caches
- **Analytics Signals O(1) lookups** — watchlist filter and allocation-weight accumulation use a `Set` and `Map` respectively instead of repeated `Array.find` calls

**From v3.0**

- **Overview / Holdings / Analytics zones** with persistent tab state and cleaner navigation
- **Portfolio briefing card** powered by Claude or Local Intelligence
- **Add / Hold / Trim verdicts** with confidence ranges, time horizons, peer context, earnings flags, and Claude-vs-local tension
- **Look-through exposure** for sector, country, and theme overlap; duplicate holdings; and concentration risk
- **Market regime chip** using SPY, TLT, VIX, and UUP context — the macro mood ring has receipts
- **Base / Bull / Bear scenarios** with probability bars and "most likely" context
- **Analytics tab** covering performance, risk, exposure, signals, and markets
- **Local-first storage** with SQLite, git-ignored `.env`, and optional Claude API usage

<details>
<summary>📊 Analytics widgets</summary>

| Zone | Widgets |
| --- | --- |
| **Performance** | Return breakdown, cumulative P&L, projection vs S&P 500, benchmark tracker, monthly heatmap |
| **Risk** | Risk/reward scatter, correlation matrix, HHI concentration, drawdown, beta, rolling volatility |
| **Exposure** | Sector tilt, geographic look-through, theme overlap |
| **Signals** | Conviction gaps, confidence spectrum |
| **Markets** | World index grid, macro alignment, geographic alignment |

Each tab has an insight bar and per-widget tip cards via `/api/ai/analytics-insights`.

</details>

<details>
<summary>🧬 Intelligence engine</summary>

- Movement explanations using benchmark, macro, sector, volume, and event context
- Horizon-aware `auto`, `trade`, `core`, and `anchor` hold classes
- Confidence ranges beside headline scores
- Exposure, regime, peer, event, and calibration modifiers
- Verdict snapshots logged to SQLite for future hit-rate accountability
- Deep intelligence loaded only when a holding expands — eager loading is how dashboards become soup

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

## 🚀 Install, Run, Update

FolioSenseAI runs locally at [`http://localhost:8000`](http://localhost:8000). Your holdings stay on your machine unless you personally teach them to leave.

### Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.11+ | [python.org](https://www.python.org/downloads/) — reopen your terminal after installing |
| Git or a release ZIP | For cloning or downloading a release archive |
| A terminal | bash, zsh, or PowerShell |
| Anthropic API key | **Optional** — [console.anthropic.com](https://console.anthropic.com/). Market data and Local Intelligence work without it. |

### Fresh Install

<details open>
<summary>🍎 Mac / Linux</summary>

```bash
curl -L -o FolioSenseAI-v3.1.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v3.1.zip
unzip FolioSenseAI-v3.1.zip
cd FolioSenseAI-release-v3.1
./scripts/setup.sh
```

</details>

<details>
<summary>🪟 Windows PowerShell</summary>

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v3.1.zip" -OutFile "FolioSenseAI-v3.1.zip"
Expand-Archive -Path "FolioSenseAI-v3.1.zip" -DestinationPath .
cd FolioSenseAI-release-v3.1
.\scripts\setup.ps1
```

</details>

The setup script creates `venv/`, installs pinned dependencies, creates `database/`, writes `.env` if missing, and starts the app. Keep the terminal open while using the dashboard — it is the engine room, not decorative clutter.

### Daily Start

```bash
./scripts/start.sh          # Mac / Linux
.\scripts\start.ps1         # Windows PowerShell
```

### Update

<details open>
<summary>🧳 From a release ZIP</summary>

1. Stop the app (`Ctrl+C`).
2. Back up `database/` and `.env`.
3. Download the new release into a **new folder** — do not overwrite in place.
4. Copy your backed-up `database/` and `.env` into the new folder.
5. Run setup once, then use the start script going forward.

```bash
# Mac / Linux
./scripts/setup.sh --no-start
./scripts/start.sh
```

```powershell
# Windows
.\scripts\setup.ps1 -NoStart
.\scripts\start.ps1
```

</details>

<details>
<summary>🌿 From git</summary>

```bash
# Mac / Linux
git pull --ff-only
./scripts/setup.sh --no-start
./scripts/start.sh
```

```powershell
# Windows
git pull --ff-only
.\scripts\setup.ps1 -NoStart
.\scripts\start.ps1
```

</details>

v3.1 has no database schema changes and no new `.env` fields — drop in your existing `database/` and `.env` and start. The `verdict_snapshots` table from v3.0 carries over as-is.

<details>
<summary>🤖 Claude API setup (optional)</summary>

Add to `.env`, then restart:

```env
ANTHROPIC_API_KEY=sk-ant-your-real-key-goes-here
```

Claude API usage is billed separately from Claude Pro. Responses are cached aggressively — billing anxiety is a design smell.

</details>

<details>
<summary>🩹 Common fixes</summary>

| Symptom | Fix |
| --- | --- |
| `Python 3.11+ is required` | Install Python from [python.org](https://www.python.org/downloads/) and reopen the terminal. |
| PowerShell blocks scripts | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`. |
| `Permission denied` on Mac/Linux | Run `chmod +x scripts/setup.sh scripts/start.sh`. |
| `localhost:8000` will not load | Keep the terminal running and confirm the app did not crash. |
| Port `8000` is busy | Stop the other app using that port, or change the port in `run.py`. |
| AI features are disabled | Add `ANTHROPIC_API_KEY` to `.env` and restart. |

</details>

---

## 👩‍💻 Developer Notes

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
python run.py
```

Local URLs:

| URL | Purpose |
| --- | --- |
| [`http://localhost:8000`](http://localhost:8000) | Dashboard |
| [`http://localhost:8000/docs`](http://localhost:8000/docs) | Interactive API docs (Swagger UI) |
| [`http://localhost:8000/health`](http://localhost:8000/health) | Health check |

<details>
<summary>🗂️ Project structure</summary>

```text
app/
├── main.py          — FastAPI app, middleware, static serving, startup migrations
├── models.py        — SQLAlchemy ORM models
├── schemas.py       — Pydantic request/response contracts
├── routers/         — API routes (stocks, portfolio, AI intelligence)
└── services/        — market data, analytics, exposure, regime, projections, verdicts
templates/
└── index.html       — single-page dashboard shell
static/
├── js/              — dashboard interactions and analytics charts
└── css/style.css    — design system, layout, responsive states
tests/               — mocked external services, analytics coverage, UI behavior checks
scripts/             — setup and start scripts for Mac/Linux and Windows
```

</details>

<details>
<summary>🔌 API quick reference</summary>

| Group | Endpoints |
| --- | --- |
| **Market data** | `/api/stocks/prices`, `/api/stocks/history/{ticker}`, `/api/stocks/world-markets`, `/api/stocks/market-status` |
| **Portfolio** | `/api/portfolio/holdings`, `/api/portfolio/value`, `/api/portfolio/pnl`, `/api/portfolio/projection`, `/api/portfolio/risk-metrics`, `/api/portfolio/correlation` |
| **Analytics** | `/api/portfolio/drawdown`, `/api/portfolio/beta`, `/api/portfolio/rolling-volatility`, `/api/portfolio/sector-tilt`, `/api/portfolio/conviction-gaps`, `/api/portfolio/market-context` |
| **AI / Intelligence** | `/api/ai/investment-signals/all`, `/api/ai/portfolio-summary`, `/api/ai/portfolio-exposure`, `/api/ai/verdict-calibration`, `/api/ai/analytics-insights`, `/api/ai/intelligence/{ticker}/deep` |

Open [`/docs`](http://localhost:8000/docs) locally for the full interactive FastAPI reference.

</details>

---

## 🧪 Release Checks

```bash
python -m pytest -q
python -m compileall -q app run.py tests
python -m pylint $(git ls-files '*.py')
pip-audit -r requirements.txt
```

GitHub CI runs all checks on Python 3.11 and 3.12. Additional workflows cover Pylint, dependency audit/review, CodeQL, and a hygiene check that blocks tracked secrets, databases, backups, and OS noise.

<details>
<summary>🔐 Local-first security</summary>

- `.env` and SQLite databases are git-ignored
- Fresh installs start with an empty portfolio unless `DEFAULT_HOLDINGS` is set
- CORS defaults to local origins only
- Claude is optional and cached; Local Intelligence makes no external AI API calls
- This is a personal project — not a brokerage, advisor, oracle, or suspiciously confident uncle

</details>

---

## 🗺️ Roadmap

- [ ] CSV import / export
- [ ] Transaction history views
- [ ] News section
- [ ] Calibration reporting once verdict snapshots have enough history to stop being anecdotal

---

## 🤝 Contributing

Issues and pull requests are welcome. For anything beyond a small fix, open an issue first to align on scope.

- Run `python -m pytest -q` and `python -m pylint $(git ls-files '*.py')` before submitting
- Keep changes focused; the PR description is where context lives, not the code

---

## 📄 License & Disclaimer

Personal project, released for public use. **Not financial advice.** If you make or lose money because a dashboard on GitHub had nice colors, that is a fascinating life choice and also entirely on you.

<p align="center">
  Built with AI, caffeine, and a deeply normal interest in watching numbers move.<br/>
  ⭐ Star it if it helped you understand your portfolio. Or at least insult it with better vocabulary.
</p>
