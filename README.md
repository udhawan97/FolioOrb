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
  <img src="https://img.shields.io/badge/release-v1.1-brightgreen?style=flat-square" alt="Release v1.1"/>
</p>

<p align="center">
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/ci.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/pylint.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/pylint.yml/badge.svg" alt="Pylint"/></a>
  <a href="https://github.com/udhawan97/FolioSenseAI/actions/workflows/codeql.yml"><img src="https://github.com/udhawan97/FolioSenseAI/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"/></a>
</p>

---

> **Because "I don't know why my portfolio is down" is only acceptable once.**
>
> FolioSenseAI tracks your holdings, pulls live prices from Yahoo Finance, and asks Claude AI to explain what on earth is happening — market context, sector moves, macro events, analyst takes. All the excuses reasons you need, in one dashboard.

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
- Real-time prices and daily gain/loss for all holdings
- Total portfolio value and daily P&L *(color-coded — green good, red bad, you know the drill)*
- Allocation, return, and performance-history views
- Market open/closed indicator with auto-refresh countdown — so you can watch it drop in real time

### 🧠 Portfolio Intelligence *(the whole point)*
- **Movement explanations** — macro, sector, news, and company context for each holding
- **Portfolio-level AI analysis** — diversification themes, concentration risks, notable movers
- **Holding coverage** — ETF sectors, regions, themes, and benchmark context
- **Analyst recommendations** and ETF quality labels *(take with an appropriate grain of salt)*

### ⚙️ Portfolio Management
- Add and remove holdings from the UI
- Update share counts and average cost basis
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
| 🎨 **Frontend** | Bootstrap 5 · Chart.js · Vanilla JS | Zero frontend frameworks harmed in the making |
| 🔐 **Config** | python-dotenv | Secrets stay secret. Your ticker picks do not. |

---

## 🚀 Local Setup

### Fast Install

You'll need **Python 3.11+** from [python.org](https://www.python.org/downloads/). On Windows, check **Add Python to PATH** during install.

The Anthropic API key is optional. Without it, FolioSenseAI still runs with live market data and portfolio tracking; AI explanations stay disabled until you add a key from [console.anthropic.com](https://console.anthropic.com/).

These commands install the GitHub release [v1.1](https://github.com/udhawan97/FolioSenseAI/releases/tag/release-v1.1).

**Mac / Linux**

```bash
curl -L -o FolioSenseAI-v1.1.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v1.1.zip
unzip FolioSenseAI-v1.1.zip
cd FolioSenseAI-release-v1.1
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v1.1.zip" -OutFile "FolioSenseAI-v1.1.zip"
Expand-Archive -Path "FolioSenseAI-v1.1.zip" -DestinationPath .
cd FolioSenseAI-release-v1.1
.\scripts\setup.ps1
```

The setup script creates the virtual environment, installs dependencies, creates `.env`, generates a local secret key, creates the database folder, and starts the app.

Open [http://localhost:8000](http://localhost:8000). Your local portfolio is created automatically the first time the dashboard asks for data.

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
| `GET` | `/api/stocks/market-status` | Is the market open (and punishing you)? |

</details>

<details>
<summary>💼 Portfolio</summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/portfolio/holdings` | All active holdings |
| `POST` | `/api/portfolio/holdings` | Add a holding |
| `PUT` | `/api/portfolio/holdings/{id}` | Update shares/cost |
| `DELETE` | `/api/portfolio/holdings/{id}` | Remove a holding (touch grass) |
| `GET` | `/api/portfolio/value` | Portfolio value, allocation, daily P&L |
| `GET` | `/api/portfolio/pnl` | Historical returns and realized P&L |
| `POST` | `/api/portfolio/seed` | Backward-compatible first-run helper; usually no longer needed |

</details>

<details>
<summary>🤖 AI Intelligence</summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/ai/summary/{ticker}` | AI summary for one holding |
| `GET` | `/api/ai/summaries/all` | AI summaries for all holdings |
| `GET` | `/api/ai/portfolio-insight` | Portfolio-level AI analysis |
| `GET` | `/api/ai/explain-move/{ticker}` | Why is this thing moving? |
| `GET` | `/api/ai/explain-moves/all` | Why is everything moving? |
| `GET` | `/api/ai/holding-intelligence/all` | Coverage and benchmark context |
| `GET` | `/api/ai/analyst-recommendations/all` | Analyst takes and ETF quality labels |
| `GET` | `/api/ai/cache/stats` | Cache stats and estimated API cost |
| `DELETE` | `/api/ai/cache/clear` | Clear cached summaries |

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

- [ ] Real-time WebSocket price updates
- [ ] Transaction history views
- [ ] Price alerts
- [ ] PostgreSQL support for cloud deployments
- [ ] AI-powered rebalancing suggestions
- [ ] Export portfolio to CSV
- [ ] Cope with market volatility *(stretch goal)*

---

## 📄 License

Personal project. **Not financial advice.** If you make or lose money based on a dashboard you found on GitHub, that's entirely on you. No warranties, express or implied, for your portfolio or your life choices.

---

<p align="center">
  Built with 🤖 AI, ☕ caffeine, and a concerning interest in watching numbers move.<br/>
  ⭐ Star this repo if it helped you feel better about your losses.
</p>
