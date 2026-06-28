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

> **v4.1** — FolioSenseAI now lets you configure Claude from the dashboard itself. Paste your API key into the new in-UI key panel, and the app validates, saves, and reconnects without a restart. Real token counts accumulate in-session and surface in the cost HUD — you see what every Claude call actually spent, not an estimate. The holdings table auto-refreshes, expands on first click, and loads faster. The Overview sector graph renders proportional fills with proper overflow handling.

<p align="center">
  <img src="docs/dashboard.png" alt="FolioSenseAI dashboard" width="860"/>
  <br/>
  <sub><em>Demo numbers. Real anxiety simulation.</em></sub>
</p>

<p align="center">
  <img src="docs/architecture.svg" alt="FolioSenseAI architecture diagram" width="860"/>
</p>

---

## Contents

- [Why It Exists](#-why-it-exists)
- [v4.1 Highlights](#-v41-highlights)
- [Tech Stack](#️-tech-stack)
- [Install, Run, Update](#-install-run-update)
- [Developer Notes](#-developer-notes)
- [Release Checks](#-release-checks)
- [Roadmap](#️-roadmap)
- [Contributing](#-contributing)
- [License & Disclaimer](#-license--disclaimer)

---

## ⚡ Why It Exists

FolioSenseAI is a self-hosted FastAPI dashboard for investors who want more than "line went down." It explains portfolio movement, tracks allocation and risk, and generates Add / Hold / Trim / Exit intelligence using either **Anthropic Claude** or a deterministic **Local Intelligence** engine.

- **For Investors:** live market context, portfolio diagnostics, a prioritized action plan, and enough witty copy to make volatility feel personally curated.
- **For Developers:** a Python + FastAPI + SQLite project with modular services, vanilla JS charts, mocked external-service tests, and no frontend framework tax. React was not harmed because it was never invited.
- **For Portfolio Builders:** a polished full-stack AI/data product demonstrating local-first privacy, API design, analytics UX, response caching, CI, and security hygiene.

---

## 🧠 v4.1 Highlights

**New in v4.1**

- **In-dashboard API key panel** — click the brand mark, paste your `sk-ant-*` key, and the dashboard validates, writes it to `.env`, and reconnects Claude without a restart. No terminal required. The key is validated client-side and server-side against the canonical Anthropic format before touching disk.
- **Live token cost tracking** — every Claude call accumulates real token counts session-wide. The cost HUD shows actual input/output tokens, a live cost figure, and a predicted per-run annotation — so you see exactly what each scan costs, not an estimate from cache occupancy.
- **Holdings table auto-refresh + first-click expand** — prices refresh on an interval automatically; rows now expand on the very first click without the previous two-click workaround.
- **Overview sector graph refactor** — proportional fills scaled relative to the top sector, leading dot + track layout, and an overflow note for portfolios with more sectors than the strip can show.
- **361 tests** — up from 356 in v4.0.

**From v4.0**

- **Portfolio Action Plan** — Claude reads your full book and returns a prioritized Hold / Add / Trim / Exit bucket plan with a thesis and top moves per bucket. Cached 24 h with portfolio-state drift invalidation so it stays fresh without re-billing you every refresh. Falls back to a deterministic local plan instantly when Claude is unavailable or when you'd prefer the quiet.
- **Regime-aware context** — the Action Plan surfaces the current market regime (risk-on / risk-off / neutral) alongside the Claude thesis so bucket decisions have macro backdrop, not just holding-level math.
- **News tab** — a fourth dashboard zone pulls live headlines for every active holding via yfinance, deduped, cached, and grouped by ticker. Claude-mode adds a portfolio-wide briefing and cross-holding theme clusters (one Haiku call) so you can see which macro story is hitting three positions at once.

**From v3.1**

- **Instant holdings table** — `localStorage` snapshot paints the table before the first network request leaves the building; live prices replace it in place
- **Shared `.info` cache** — one cached Yahoo Finance scrape per ticker shared across quotes, analyst recs, intelligence, earnings calendar, move explainer, and ETF price signals
- **Background startup warmup** — a daemon thread pre-fetches quotes, history, and world markets for active holdings on server start

**From v3.0**

- **Overview / Holdings / Analytics zones** with persistent tab state
- **Portfolio briefing card** powered by Claude or Local Intelligence
- **Add / Hold / Trim verdicts** with confidence ranges, time horizons, peer context, earnings flags, and Claude-vs-local tension
- **Look-through exposure** for sector, country, and theme overlap; duplicate holdings; and concentration risk
- **Market regime chip** using SPY, TLT, VIX, and UUP context
- **Base / Bull / Bear scenarios** with probability bars
- **Analytics tab** covering performance, risk, exposure, signals, and markets

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

## 🚀 Install & Run

FolioSenseAI runs entirely on your computer. No account needed, no data leaves your machine.

**One prerequisite:** Python 3.11+ — [download here](https://www.python.org/downloads/), click the yellow button, run the installer.
> **Windows only:** on the first installer screen, check **"Add Python to PATH"** before clicking Install.

---

### 🍎 Mac — one command

Open **Terminal** (press **⌘ Space**, type *Terminal*, press **Enter**), paste the line below, and press **Enter**:

```bash
curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.1/scripts/install-mac.sh | bash
```

That's it. The script downloads FolioSenseAI, installs dependencies, and puts a **FolioSenseAI** shortcut on your Desktop. Your browser opens automatically when the app is ready.

**Next time:** double-click the **FolioSenseAI** icon on your Desktop.

---

### 🪟 Windows — one command

Open **PowerShell** (press **Win+R**, type `powershell`, press **Enter**), paste the line below, and press **Enter**:

```powershell
irm https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.1/scripts/install-win.ps1 | iex
```

That's it. The script downloads FolioSenseAI, installs dependencies, and puts a **FolioSenseAI** shortcut on your Desktop. Your browser opens automatically when the app is ready.

**Next time:** double-click the **FolioSenseAI** icon on your Desktop.

---

**Keep the Terminal / console window open while using the app — closing it stops the server.** Press **Ctrl+C** to stop.

---

### Claude API key (optional)

The app works fully offline with Local Intelligence. For Claude AI features (action plans, news briefings), click the **brand mark** in the top-left of the dashboard, paste your `sk-ant-*` key, and save — no restart needed.

Get a key at [console.anthropic.com](https://console.anthropic.com/). Action Plan responses are cached 24 h so you won't be re-billed on every refresh.

---

### Updating to a new version

Run the install command again — it preserves your portfolio data and settings automatically, then starts the updated app.

---

<details>
<summary>🩹 Something not working?</summary>

| Symptom | Fix |
| --- | --- |
| `Python not found` | Install Python from [python.org](https://www.python.org/downloads/) and open a **new** terminal window. |
| Windows: `winget` fails | Install Python manually, check "Add to PATH", then re-run the command. |
| Mac: `curl: command not found` | This shouldn't happen on any modern Mac — reinstall macOS command-line tools: `xcode-select --install`. |
| Browser doesn't open | Navigate to [http://localhost:8000](http://localhost:8000) manually. |
| `localhost:8000` won't load | The terminal window must stay open — it is the server. |
| Port 8000 is busy | Stop the other app on that port, or change the port in `run.py`. |
| AI shows "Local" mode | Click the brand mark in the dashboard and paste your API key. |

</details>

<details>
<summary>⚙️ Manual install (advanced)</summary>

If you prefer to manage the files yourself:

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
├── routers/         — API routes (stocks, portfolio, AI intelligence, news)
└── services/        — market data, analytics, exposure, regime, projections, verdicts, news
templates/
└── index.html       — single-page dashboard shell (four zones: Overview, Holdings, Analytics, News)
static/
├── js/              — dashboard interactions and analytics charts
└── css/style.css    — design system, layout, responsive states
tests/               — mocked external services, analytics coverage, action plan, news service
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
| **AI / Intelligence** | `/api/ai/investment-signals/all`, `/api/ai/portfolio-summary`, `/api/ai/portfolio-exposure`, `/api/ai/verdict-calibration`, `/api/ai/analytics-insights`, `/api/ai/intelligence/{ticker}/deep`, `/api/ai/action-plan`, `/api/ai/configure-key` |
| **News** | `/api/news/feed`, `/api/news/themes` |

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
