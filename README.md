<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="static/img/brand/folio-orbit-mark-light.svg">
    <source media="(prefers-color-scheme: light)" srcset="static/img/brand/folio-orbit-mark-dark.svg">
    <img src="static/img/brand/folio-orbit-mark-dark.svg" alt="FolioSenseAI" width="300"/>
  </picture>
</p>

<h2 align="center">FolioSenseAI</h2>
<p align="center"><em>Your portfolio's therapist. Explains the red. Won't fix it.</em></p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-0.136-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Claude_AI-Anthropic-D4A853?style=flat-square&logo=anthropic&logoColor=white" alt="Claude AI"/>
  <img src="https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite"/>
  <img src="https://img.shields.io/badge/Bootstrap-5-7952B3?style=flat-square&logo=bootstrap&logoColor=white" alt="Bootstrap 5"/>
  <img src="https://img.shields.io/badge/Chart.js-FF6384?style=flat-square&logo=chartdotjs&logoColor=white" alt="Chart.js"/>
  <img src="https://img.shields.io/badge/release-v3-brightgreen?style=flat-square" alt="Release v3"/>
</p>

<p align="center">
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/ci.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/pylint.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/pylint.yml/badge.svg" alt="Pylint"/></a>
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/codeql.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"/></a>
</p>

---

> **v3 is here: FolioSenseAI finally admits your portfolio has overlap, a mood, a preferred timeline, and a whole Analytics tab.**
>
> FolioSenseAI still tracks your holdings, pulls live prices from Yahoo Finance, and lets Claude and Local Intelligence argue politely over Add/Hold/Trim. v3 adds look-through exposure, market-regime context, peer comparisons, earnings risk flags, Base/Bull/Bear scenarios with probability bars, and a verdict card that breathes instead of screaming in a grid. The dashboard now splits into **Overview**, **Holdings**, and **Analytics** zones — with a portfolio briefing card, five analytics sub-tabs (Performance, Risk, Exposure, Signals, Markets), and per-widget insight lines. The navbar got an overflow menu so the top bar stops looking like an aircraft cockpit. Very composed. Still judging you.

---

## 📸 Snapshot

<p align="center">
  <img src="docs/dashboard.png" alt="FolioSenseAI Dashboard" width="850"/>
  <br/>
  <sub><em>Numbers are fake to protect the traumatized investor.</em></sub>
</p>


---

## ✨ Features

### 📊 Live Dashboard
- **Three dashboard zones** — **Overview** (hero stats, briefing, charts), **Holdings** (verdict table), and **Analytics** (deep charts); zone choice persists in browser storage
- Real-time prices and daily gain/loss for all holdings
- Total portfolio value and daily P&L *(semantic color tokens — green means up, red means down, not "we liked this palette")*
- Allocation, return, and performance-history views
- **Portfolio briefing card** — AI mode asks Claude for a plain-English book narrative; Local mode serves a free deterministic digest of movers and drivers
- Market open/closed indicator with auto-refresh countdown — so you can watch it drop in real time
- **Navbar overflow menu** — theme, text size, pet mode, and AI-cost controls tucked into one Apple-style settings sheet
- **Live feed HUD** with refresh state, force-refresh control, and Claude API heartbeat
- **Claude offline guidance** with direct setup steps when AI features are paused
- **Last-sync resilience** that keeps the last good market-data timestamp visible if a refresh fails
- **Portfolio Butler companion** — a lightweight dashboard pet with witty market reactions; animates on hover so it doesn't fidget while you're trying to read losses

### 🧠 Portfolio Intelligence *(the whole point)*
- **Movement explanations** — macro, sector, benchmark, volume, earnings, and company context for each holding
- **Portfolio-level AI analysis** — diversification themes, concentration risks, notable movers
- **Holding coverage** — ETF sectors, regions, themes, and benchmark context
- **FolioSense × Claude verdicts** — Add, Hold, Trim, or Needs Data calls with confidence, reasons, risks, and one-line color commentary
- **Local Intelligence labels** that make offline verdicts clear when Claude is not connected
- **Claude / Local Intelligence toggle** — choose deterministic local quips without disconnecting your API key
- **Anchor Hold** — mark any position as a long-term anchor; FolioSense never trims it, instead surfaces better add moments when price dips below its own trend; toggleable from the verdict card or Manage Holdings
- **Time horizons** — cycle Auto → Trade → Core so the same signals weigh differently depending on whether you're flirting or marrying the position
- **Confidence ranges** — low/high band around the score, because certainty is a lifestyle brand, not a portfolio metric
- **Base / Bull / Bear scenarios** — three plausible paths with pills, probability bars, and Claude's "most likely" pick when AI is connected
- **Book exposure strip** — look-through sector, country, and theme overlap, duplicate tickers, and concentration (HHI) so you can't pretend diversification is just owning five tech ETFs
- **Market backdrop chip** — regime read from SPY/TLT/VIX/UUP with component weight shifts
- **Vs-peers line** — where the holding sits in its own range versus peer median *(humble brag or humble bruise)*
- **Earnings event chip** — flags names with earnings inside 14 days and caps overconfidence accordingly
- **Claude tension flags** — when local math and Claude disagree, the card says so instead of smiling through it
- **Verdict calibration footnotes** — snapshots logged over time so confidence buckets can eventually be held accountable
- **Deep read on expand** — richer holding intelligence loads async when you open a row, not while the whole table is already late for something
- **Market-mood awareness** — live price momentum now tempers marginal calls before the app gets too enthusiastic
- **Portfolio health quip** — a coarse read on the whole book, including concentration and dominant action mix
- **ETF holdings fallback** — optional Claude-seeded holdings when market data providers leave an ETF's top holdings blank
- **Analyst recommendations** and ETF quality labels *(take with an appropriate grain of salt)*
- **Claude texting animation** — Holding Intel now cues a subtle bottom-right chat animation while analysis runs

### 📈 Analytics *(new in v3)*
- **Five sub-tabs** — Performance, Risk, Exposure, Signals, and Markets, each with lazy-rendered Chart.js visualizations
- **Per-tab insight bar** — Claude or Local Intelligence one-liner for the active analytics section, plus per-widget insight lines beneath each chart
- **Performance** — total return breakdown, cumulative P&L history, growth projection (avg / best / worst vs S&P 500), benchmark tracker, monthly return calendar heatmap
- **Risk** — risk/reward scatter, correlation matrix, HHI concentration gauge, drawdown underwater chart, portfolio beta dial, rolling volatility
- **Exposure** — sector tilt vs S&P 500, geographic look-through bars with country flags, theme overlap treemap
- **Signals** — conviction gaps (verdict vs position size) and confidence spectrum (allocation-weighted score distribution)
- **Markets** — global index correlation grid, macro-alignment scatter, and look-through geographic alignment vs world markets

### ⚙️ Portfolio Management
- Add and remove holdings from the UI
- Update share counts and average cost basis
- Research-mode watchlist entries can be added without share counts
- Ticker validation catches invalid symbols before they sneak into your portfolio wearing a fake mustache
- Realized-sale rows can be deleted when your historical bookkeeping gets a little too creative
- Soft-delete holdings while preserving historical trade data *(because your mistakes deserve to be remembered)*

---

## 🏗️ Tech Stack

*No blockchain. No NFTs. No regrets.*

| Layer | Technology | Why |
|-------|------------|-----|
| 🐍 **Backend** | Python 3.11+ · FastAPI · Uvicorn | Fast, async, and doesn't make you cry |
| 🗄️ **Database** | SQLite · SQLAlchemy 2.0 · Pydantic v2 | ACID-compliant, unlike your trading decisions |
| 🤖 **AI** | Anthropic Claude | Smarter than CNBC. Low bar. Cleared it. |
| 📈 **Market Data** | yfinance · Yahoo Finance | Free real-time data — the only free thing in investing |
| 🎨 **Frontend** | Bootstrap 5 · Chart.js · chartjs-chart-matrix · chartjs-chart-treemap · Vanilla JS | Zero React frameworks harmed in the making |
| 🔐 **Config** | python-dotenv | Secrets stay secret. Your ticker picks do not. |

---

## 🚀 Local Setup

### Before You Start

You do not need to be a developer to run FolioSenseAI locally. Think of this like installing a small private dashboard on your own computer:

- Install **Python 3.11 or newer** from [python.org](https://www.python.org/downloads/). On Windows, make sure **Add Python to PATH** is checked during install.
- Use **Terminal** on Mac or Linux. Use **PowerShell** on Windows.
- Copy and paste one command block at a time. If a prompt asks for an Anthropic API key, paste it or press **Enter** to skip AI features for now.
- Keep the Terminal or PowerShell window open while using the app. Closing it stops the local server.
- The dashboard runs only on your computer at `http://localhost:8000`; it is not publishing your portfolio to the internet.

### Fast Install

The Anthropic API key is optional. Without it, FolioSenseAI still runs with live market data and portfolio tracking; AI explanations stay disabled until you add a key from [console.anthropic.com](https://console.anthropic.com/).

These commands install the latest `main` branch (v3). Prefer a frozen zip? Grab [release-v2.4](https://github.com/udhawan97/FolioSenseAI/releases/tag/release-v2.4) and accept that you're living in the past with excellent sync-state hygiene.

**Mac / Linux**

```bash
curl -L -o FolioSenseAI-main.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/heads/main.zip
unzip FolioSenseAI-main.zip
cd FolioSenseAI-main
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioSenseAI/archive/refs/heads/main.zip" -OutFile "FolioSenseAI-main.zip"
Expand-Archive -Path "FolioSenseAI-main.zip" -DestinationPath .
cd FolioSenseAI-main
.\scripts\setup.ps1
```

The setup script creates the virtual environment, installs dependencies, creates `.env`, generates a local secret key, creates the database folder, and starts the app.

Open [http://localhost:8000](http://localhost:8000). Your local portfolio is created automatically the first time the dashboard asks for data.

### What Success Looks Like

When setup works, your Terminal or PowerShell window will say:

```text
Starting FolioSenseAI at http://localhost:8000
```

Leave that window running, then open [http://localhost:8000](http://localhost:8000) in Chrome, Edge, Safari, or Firefox.

### Starting Later

After the first install, use the lighter start script:

```bash
./scripts/start.sh
```

Windows:

```powershell
.\scripts\start.ps1
```

### Optional AI Setup

If you skipped the Anthropic key during setup, open `.env` and set:

```env
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

The API key costs a little money per AI query, roughly pennies. AI explanations are cached, so refreshing the dashboard does not keep spending.

#### Getting Your Own Anthropic API Key

This is the tiny toll booth that lets FolioSenseAI ask Claude for portfolio explanations. Your brokerage anxiety remains locally sourced.

1. Go to the [Anthropic Console](https://console.anthropic.com/) and sign in or create an account.
2. Open the API keys area. Anthropic may ask you to create a workspace or add billing first; this is normal capitalism, sadly.
3. Create a new API key and give it a boring name like `FolioSenseAI Local`.
4. Copy the key right away. Treat it like a password with better vocabulary.
5. Open the `.env` file in the FolioSenseAI folder and paste it like this:

```env
ANTHROPIC_API_KEY=sk-ant-your-real-key-goes-here
```

6. Save `.env`, stop the app with `Ctrl+C`, then restart it:

```bash
./scripts/start.sh
```

Windows:

```powershell
.\scripts\start.ps1
```

Tips before Claude starts analyzing your portfolio with unsettling calm:

- Do not paste your API key into GitHub, screenshots, Slack, email, or anywhere public. If it leaks, delete it in the Anthropic Console and create a new one.
- Start with a small billing limit if Anthropic offers one. The app caches AI responses, but budgets are cheaper than surprises.
- The Claude web subscription and the Anthropic API are separate. Having Claude Pro does not automatically make API usage free.
- You can leave the key blank. The dashboard still tracks holdings and market data; it just loses the AI therapist chair.

### Quick Fixes

| If you see this | Try this |
|-----------------|----------|
| `Python 3.11+ is required` | Install the latest Python from [python.org](https://www.python.org/downloads/), then close and reopen Terminal or PowerShell. |
| PowerShell blocks the script | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`, then run the setup command again. |
| `Permission denied` on Mac/Linux | Run `chmod +x scripts/setup.sh scripts/start.sh`, then try `./scripts/setup.sh` again. |
| Browser says the site cannot be reached | Make sure the Terminal or PowerShell window is still running and shows `http://localhost:8000`. |
| Port `8000` is already in use | Close the other local app using that port, or stop it and run the start script again. |
| AI features are disabled | Add `ANTHROPIC_API_KEY=your_key_here` to `.env`, save it, then restart the app. |
| Market data looks delayed or unavailable | Wait a minute and refresh. Yahoo Finance data can be delayed, rate-limited, or unavailable outside market hours. |

### Developer Setup

Prefer doing everything manually? Fair enough.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Windows:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

If PowerShell blocks scripts, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

If yfinance complains about certificates, run:

```bash
pip install --upgrade certifi
```

---

### 🔗 Useful URLs *(once running)*

| URL | What's there |
|-----|-------------|
| `http://localhost:8000` | The dashboard |
| `http://localhost:8000/docs` | Swagger API docs (surprisingly pretty) |
| `http://localhost:8000/health` | Health check endpoint |

---

## 🪄 What's New In v3

**FolioSenseAI v3 is the "your portfolio is a system, not a bag of tickers" release: richer local intelligence, Claude that can disagree on purpose, a full Analytics zone, and a dashboard that finally learned negative space.**

- Added **dashboard zones** — Overview, Holdings, and Analytics with persistent tab state and zone-aware chart lifecycle.
- Added **portfolio briefing card** — `/api/ai/portfolio-summary` with AI (Claude Haiku, 24 h cache) and Local deterministic modes.
- Added **Analytics zone** with five sub-tabs (Performance, Risk, Exposure, Signals, Markets), lazy Chart.js charts, and per-widget insight lines via `/api/ai/analytics-insights`.
- Added **portfolio analytics engine** — risk metrics, correlation, drawdown, contribution, benchmark comparison, return calendar, beta, rolling vol, sector tilt, conviction gaps, confidence spectrum, macro alignment, and growth projection endpoints under `/api/portfolio/*`.
- Added **look-through portfolio exposure** — sector, country, theme overlap, duplicate detection, and HHI concentration so "diversified" has to earn the title.
- Added **market regime context** from SPY/TLT/VIX/UUP with cached daily weight shifts for the backdrop chip.
- Added **peer-relative positioning** — own-range percentile vs peer median, for when you need to know if you're early, late, or merely emotional.
- Added **earnings event awareness** — names with earnings inside 14 days get capped confidence and a polite panic note.
- Added **time horizons** (`auto` / `trade` / `core` / `anchor`) with a cycle pill on the verdict card and Manage Holdings support.
- Added **confidence ranges** (`range_low` / `range_high`) beside the headline score.
- Added **Base / Bull / Bear scenarios** with local paths plus Claude probability splits (`likely`, `sc_p`, `sc_w`) when AI is connected.
- Added **Claude tension gating** — nudges only when inputs conflict (`agrees`, `tension`, `flip_if`); agreement does not get performative drama.
- Added **verdict calibration snapshots** — logged to SQLite with bucket summaries *(hit-rate reporting matures when forward prices catch up)*.
- Added API endpoints for **`/api/ai/portfolio-exposure`**, **`/api/ai/verdict-calibration`**, **`/api/ai/intelligence/{ticker}/deep`**, **`/api/ai/portfolio-summary`**, and **`/api/ai/analytics-insights`**.
- Added **`/api/stocks/world-markets`** and **`/api/stocks/history/batch`** for analytics and market-context charts.
- Extended **`/api/ai/investment-signals/all`** with `portfolio_exposure`, `regime`, `calibration_summary`, and per-signal `regime_context`, `peer_relative`, `events`, `exposure_context`, `calibration_footnote`.
- Polished the **verdict card layout** — flex spacing, roomier confidence panel, scenario pills that don't feel like compressed fortune cookies.
- Added a **navbar overflow menu** for theme, text size, pet mode, and inline AI-cost detail — fewer buttons fighting for oxygen.
- Introduced **semantic color tokens** (`--color-gain/loss/neutral/state/brand`) so green always means money up, not "design liked it."
- Renamed **Timing signal → Time horizon** in tooltips because words should mean things.
- Tightened **global state** so mode toggles, sync HUD, and verdict rendering stop stepping on each other's toes.
- **286 tests passing** — including coverage for analytics wiring, portfolio briefing, projection, nav overflow, semantic tokens, scenario normalization, and calibration logging.

### v3 Release Notes

**For users:** v3 makes verdicts feel less like a single hot take and more like a briefing: exposure overlap, market mood, peer context, earnings risk, three scenarios, and — when Claude is connected — a probability bar for which future is least delusional. The new **Analytics** tab adds performance, risk, exposure, signal, and market charts with plain-English insight lines. The **Overview** zone adds a portfolio briefing card. Settings live in the overflow menu, colors mean what they say, and the pet only wiggles when you hover like a normal companion.

**For developers:** v3 bumps the FastAPI app to `3.0.0`, adds `portfolio_exposure.py`, `market_regime.py`, `peer_relative.py`, `event_calendar.py`, `verdict_calibration.py`, `verdict_ai_enhancement.py`, `portfolio_analytics.py`, `portfolio_projection.py`, and `analytics_insights.py`; extends `investment_signal.py` with horizon weights, confidence ranges, scenario builders, and modifier hooks; extends Claude prompts in `ai_service.py` for disagreement, scenario-probability, briefing, and analytics-narrator fields; adds `VerdictSnapshot` persistence; ships `analytics-charts.js` plus a large `dashboard.js` / `style.css` pass for zones, exposure strips, regime chips, scenario UI, and nav overflow; bumps static asset cache keys to `style.css?v=86`, `dashboard.js?v=79`, `analytics-charts.js?v=8`. `force_local=true` still skips Claude; all local intelligence features work offline.

---

## 🪄 What's New In v2.4

**FolioSenseAI v2.4 is the mode-control release: Claude when you want the charm, Local Intelligence when you want deterministic quiet, and fresher-feeling market data without extra drama.**

- Added a **Claude AI / Local Intel toggle** in the top bar so you can skip Claude quip generation for the session while keeping the rest of the dashboard live.
- Added `force_local=true` support to `/api/ai/investment-signals/all`, returning deterministic fallback quips without spending Claude calls.
- Added persistent local-mode preference via browser storage, with verdict labels and helper copy updating in place.
- Added a 60-second quote cache around Yahoo Finance calls to make repeated dashboard loads and validations snappier.
- Improved the **Last synced** HUD behavior so failed refreshes keep the last good timestamp and explain when stale prices are being shown.
- Fixed a race condition where overlapping `loadPortfolioValue` calls could fight over the chart canvas and produce false "Refresh failed" flashes; HUD state is now committed before rendering so a rendering error never clears a good sync time.
- Tightened the percentage column in the target-trend list so triple-digit values never wrap or truncate.
- Polished the mode toggle placement, disabled/offline state, and dashboard pet copy so Claude and Local Intelligence can share the room like adults with excellent boundaries.

### v2.4 Release Notes

**For users:** v2.4 gives you a clean choice: let Claude add personality to verdicts, or switch to Local Intel for deterministic, no-API quips. The dashboard also feels faster on repeat quote reads and behaves more gracefully when a refresh fails.

**For developers:** v2.4 bumps the FastAPI app to `2.4.0`, adds the `force_local` query path on the batch investment-signal endpoint, introduces a short-lived quote cache in `stock_service`, updates dashboard fetches to honor forced-local mode, adds an in-flight guard and pre-render HUD commit to fix sync-state race conditions, widens the percentage column in the target-trend list, and bumps the dashboard script cache key.

---

## 🪄 What's New In v2.3

**FolioSenseAI v2.3 is the graceful-offline release: clearer no-key behavior, sharper local labels, cleaner day-change polish, and one less thing for CodeQL to side-eye.**

- Added **Claude offline setup guidance** directly in the brand callout, including the Anthropic Console link, `.env` key name, and restart steps.
- Updated verdict copy so offline results show **Local Intelligence Verdict** instead of implying Claude is actively whispering into the dashboard.
- Added dynamic verdict kicker updates so reconnecting Claude restores the FolioSense × Claude label automatically.
- Improved **day-change rendering** with a reusable styled cell, cleaner caret alignment, and less inline styling.
- Hardened timing-signal logging by sanitizing untrusted ticker values before they reach log output.
- Preserved the local-first experience: live market data, deterministic signals, portfolio math, and cached/fallback notes still work when Claude is offline.

### v2.3 Release Notes

**For users:** v2.3 makes FolioSenseAI much less cryptic when Claude is not connected. The app now shows what is local, what is AI-backed, and exactly how to restore Claude. No guessing, no séance, no “why is this button judging me?” energy.

**For developers:** v2.3 bumps the FastAPI app to `2.3.0`, updates dashboard release metadata, sanitizes ticker values in timing-signal logging, replaces inline day-change icon styling with CSS, and improves offline/online verdict label synchronization in `dashboard.js`.


## 🔐 Clean-Slate Fork Safety

This repo is designed so forks start without personal portfolio data:

- `.env` stays local and is ignored by Git.
- SQLite databases and database backups are ignored.
- A fresh database creates an empty local portfolio on first use.
- `DEFAULT_HOLDINGS` is optional and stays in your own `.env` if you want starter tickers.
- `CORS_ALLOWED_ORIGINS` defaults to local app origins instead of `*`.

If you previously committed a real database backup, delete it from the current tree and purge it from Git history before treating the public repo as clean.

---

## 📡 API Reference

Full interactive docs at `/docs` when running locally. Here's the cheat sheet:

<details>
<summary>📈 Market Data</summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/stocks/prices` | Live prices for all holdings |
| `GET` | `/api/stocks/price/{ticker}` | Single ticker price |
| `GET` | `/api/stocks/history/{ticker}?period=1mo` | Historical OHLCV data |
| `GET` | `/api/stocks/history/batch?tickers=AAPL,MSFT&period=1mo` | Batched historical closes for multiple tickers (v3) |
| `GET` | `/api/stocks/market-status` | Is the market open (and punishing you)? |
| `GET` | `/api/stocks/world-markets` | Global index quotes for Markets analytics (v3) |

</details>

<details>
<summary>💼 Portfolio</summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/portfolio/holdings` | All active holdings |
| `POST` | `/api/portfolio/holdings` | Add a holding |
| `PUT` | `/api/portfolio/holdings/{id}` | Update shares/cost |
| `DELETE` | `/api/portfolio/holdings/{id}` | Remove a holding (touch grass) |
| `DELETE` | `/api/portfolio/trades/{trade_id}` | Remove one realized sale and refresh today's snapshot |
| `GET` | `/api/portfolio/value` | Portfolio value, allocation, daily P&L |
| `GET` | `/api/portfolio/pnl` | Historical returns and realized P&L |
| `GET` | `/api/portfolio/projection` | Growth scenarios (avg / best / worst) vs S&P 500 (v3) |
| `GET` | `/api/portfolio/risk-metrics` | Annualized return/volatility per holding (v3) |
| `GET` | `/api/portfolio/correlation` | Daily-return correlation matrix (v3) |
| `GET` | `/api/portfolio/drawdown` | Underwater drawdown series from snapshots (v3) |
| `GET` | `/api/portfolio/contribution?period=day` | Per-holding P&L contribution — day, week, or month (v3) |
| `GET` | `/api/portfolio/benchmark-comparison` | Portfolio vs S&P 500 cumulative return (v3) |
| `GET` | `/api/portfolio/return-calendar` | Monthly return heatmap (v3) |
| `GET` | `/api/portfolio/beta` | Portfolio beta vs S&P 500 (v3) |
| `GET` | `/api/portfolio/rolling-volatility` | Trailing 30-day annualized vol series (v3) |
| `GET` | `/api/portfolio/sector-tilt` | Sector overweight/underweight vs S&P 500 (v3) |
| `GET` | `/api/portfolio/conviction-gaps` | Verdict vs position-size mismatches (v3) |
| `GET` | `/api/portfolio/confidence-spectrum` | Allocation-weighted confidence distribution (v3) |
| `GET` | `/api/portfolio/market-context` | World indices with portfolio correlation (v3) |
| `GET` | `/api/portfolio/macro-alignment` | Index correlation vs geographic exposure (v3) |
| `POST` | `/api/portfolio/seed` | Backward-compatible first-run helper; usually no longer needed |

</details>

<details>
<summary>🤖 AI Intelligence</summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/ai/summary/{ticker}` | AI summary for one holding |
| `GET` | `/api/ai/summaries/all` | AI summaries for all holdings |
| `GET` | `/api/ai/move-explanation/{ticker}` | Why is this thing moving? |
| `GET` | `/api/ai/move-explanations/all` | Why is everything moving? |
| `GET` | `/api/ai/intelligence/{ticker}` | Coverage and benchmark context for one holding |
| `GET` | `/api/ai/intelligence/all/batch` | Coverage and benchmark context for all holdings |
| `GET` | `/api/ai/investment-signal/{ticker}` | FolioSense × Claude verdict for one holding |
| `GET` | `/api/ai/investment-signals/all` | FolioSense × Claude verdicts for all holdings; add `?force_local=true` for deterministic local quips; includes exposure, regime, and calibration context in v3 |
| `GET` | `/api/ai/portfolio-exposure` | Look-through sector/country/theme overlap, duplicates, and concentration (v3) |
| `GET` | `/api/ai/verdict-calibration` | Verdict snapshot buckets and calibration summary (v3) |
| `GET` | `/api/ai/intelligence/{ticker}/deep` | Deep holding intelligence loaded on demand (v3) |
| `GET` | `/api/ai/portfolio-summary` | Portfolio briefing card — `mode=ai` or `mode=local` (v3) |
| `GET` | `/api/ai/analytics-insights` | Per-tab and per-widget analytics insight lines — `mode=ai` or `mode=local` (v3) |
| `GET` | `/api/ai/analyst-recommendation/{ticker}` | Analyst take and ETF quality label for one holding |
| `GET` | `/api/ai/analyst-recommendations/all` | Analyst takes and ETF quality labels for all holdings |
| `GET` | `/api/ai/cache/stats` | Cache stats and estimated API cost |
| `GET` | `/api/ai/heartbeat` | Claude API reachability for the dashboard HUD |

</details>

---

## 🧪 Tests

```bash
python -m pytest tests/ -v
```

External services are mocked. *(Real integration tests would cost money. Claude is cheap but not free.)*

---

## 🛡️ GitHub Checks

The repo now has a tiny robot compliance department. It does not wear a tie, but it will absolutely block nonsense.

| Check | What it does | Vibe |
|-------|--------------|------|
| **CI** | Installs dependencies, compiles Python, imports the FastAPI app, and runs the test suite on Python 3.11 and 3.12 | Makes sure the app still has a pulse |
| **Pylint** | Runs static analysis on pull requests and pushes to `main` | Complains professionally |
| **Dependency Audit** | Uses `pip-audit` against `requirements.txt` | Checks whether a package has entered its villain era |
| **Dependency Review** | Reviews dependency changes in pull requests and fails on moderate-or-worse known vulnerabilities | Stops suspicious packages at the door |
| **CodeQL** | Runs GitHub code scanning for Python security and quality issues | Reads the code like it has trust issues |
| **Security Hygiene** | Blocks local secrets, databases, backups, and OS confetti from being tracked | Protects you from committing your digital laundry |
| **Dependabot** | Checks Python packages and GitHub Actions monthly | Gently nags the dependencies into the present |

These checks run on GitHub Actions, so pull requests get the useful red/green lights before anything lands on `main`. If a check fails, read the log before blaming the market. The market is innocent this time. Probably.

---

## 💰 Cost Breakdown

| Service | Cost |
|---------|------|
| yfinance market data | 🆓 Free |
| SQLite database | 🆓 Free |
| Self-hosted app | 🆓 Free |
| Anthropic Claude | 💸 ~Pennies per AI query, cached aggressively |
| Your time reading this README | 💸 Sunk cost |

---

## 🗺️ Roadmap

*No promises. No timeline. It's a side project.*

- [ ] CSV Uploads and Downloads
- [ ] Transaction history views
- [ ] News Section

---

## 📄 License

Personal project. **Not financial advice.** If you make or lose money based on a dashboard you found on GitHub, that's entirely on you. No warranties, express or implied, for your portfolio or your life choices.

---

<p align="center">
  Built with 🤖 AI, ☕ caffeine, and a concerning interest in watching numbers move.<br/>
  ⭐ Star this repo if it helped you feel better about your losses.
</p>
