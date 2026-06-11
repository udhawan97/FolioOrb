# Stock Analysis App 📈

An AI-powered personal stock portfolio dashboard with live market data, interactive charts, and Claude AI-generated insights — built with Python and FastAPI.

## Live Demo

> Deploy link will go here after deployment to Render.

---

## What It Does

This dashboard tracks a personal portfolio of 10 holdings in real time. Every price is fetched live from Yahoo Finance. Every summary is written by Claude AI based on actual market data — not pre-written templates.

**Portfolio tracked:** NOW · QTUM · VOO · CGDV · IBIT · VT · ITA · IEMG · SETM · WSML

### Dashboard

![Dashboard screenshot — add one after Week 1 Day 5] - To be added

- Live prices and daily gain/loss for all holdings
- Total portfolio value and daily P&L
- Color-coded performance (green up, red down)
- 5-day sparkline chart per holding
- Market open/closed indicator with auto-refresh countdown
- Fully responsive — works on mobile

### Portfolio Analytics

- Doughnut chart showing allocation by holding
- Unrealized gain/loss per position (when average cost is set)
- Best and worst performer cards
- Portfolio value breakdown with allocation percentages

### AI Insights (Powered by Claude)

- **Per-holding summaries** — Claude generates a 2-sentence update for each stock, grounded in real price data. Example:
  > *"VOO gained 0.61% today to $547.23, reflecting broad strength in large-cap U.S. equities. As an S&P 500 index fund, it remains the portfolio's largest and most diversified core holding."*

- **Portfolio-level insight** — A 3-4 sentence analysis of the full portfolio, noting diversification themes, concentration risks, and notable movers. Example:
  > *"Your portfolio gained $142 (0.58%) today, led by IBIT (+1.24%) and QTUM (+0.89%). The portfolio balances U.S. equity exposure through VOO and CGDV with international diversification via VT and IEMG, while alternative growth comes from bitcoin (IBIT), quantum computing (QTUM), and aerospace (ITA)."*

- **Smart caching** — AI summaries are cached and only regenerated when price moves more than 0.5%, keeping API costs near zero.

### Portfolio Management

- Add or remove holdings from the dashboard UI — no code needed
- Update share counts and average cost basis
- Soft-delete preserves historical data

### Security

- Password-protected login with bcrypt hashing
- Session cookies (httponly, samesite=strict)
- Rate-limited login endpoint (5 attempts/minute)
- Security headers on every response (X-Frame-Options, CSP, HSTS)
- Input validation and SQL injection protection via SQLAlchemy ORM
- Secrets managed via environment variables — never in code

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Database | SQLite, SQLAlchemy 2.0 ORM |
| AI | Anthropic Claude |
| Stock Data | yfinance (Yahoo Finance) |
| Frontend | Bootstrap 5.3, Chart.js 4, Vanilla JS |
| Auth | Passlib (bcrypt), cookie sessions |
| Deployment | Render |

**Why these choices:**
- **FastAPI** over Flask — async support, auto-generated `/docs` interface, Pydantic validation
- **SQLite** — zero setup, single file, sufficient for personal use
- **Claude Haiku** — fastest and cheapest Claude model; ~$0.002 per full portfolio refresh
- **yfinance** — no API key required, generous rate limits for personal use
- **Bootstrap 5** — professional dark theme with zero configuration

---

## Project Structure

```
stock-analysis-app/
├── app/
│   ├── main.py              # FastAPI app, middleware, startup
│   ├── config.py            # Settings from environment variables
│   ├── database.py          # SQLAlchemy engine and session
│   ├── models.py            # Database table definitions
│   ├── schemas.py           # Pydantic request/response validation
│   ├── routers/
│   │   ├── stocks.py        # GET /api/stocks/* — live price endpoints
│   │   ├── portfolio.py     # CRUD /api/portfolio/* — holdings management
│   │   ├── ai.py            # GET /api/ai/* — Claude summary endpoints
│   │   └── auth.py          # POST /login, GET /logout
│   └── services/
│       ├── stock_service.py # yfinance integration + async fetching
│       ├── ai_service.py    # Claude API calls + prompt engineering
│       └── auth_service.py  # Password hashing, session management
├── static/
│   ├── css/style.css        # Custom styles on top of Bootstrap
│   └── js/dashboard.js      # Fetch API calls, Chart.js, UI logic
├── templates/
│   ├── index.html           # Main dashboard
│   └── login.html           # Login page
├── tests/
│   ├── test_stock_service.py
│   ├── test_ai_service.py
│   └── test_portfolio_router.py
├── database/                # SQLite .db file lives here (gitignored)
├── .env.example             # Template — copy to .env and fill in values
├── .gitignore
├── requirements.txt
├── Procfile                 # Render deployment
├── render.yaml              # Render service configuration
└── run.py                   # Development server entry point
```

---

## Local Setup

### Prerequisites

- Python 3.12
- Git
- An Anthropic API key (get one free at [console.anthropic.com](https://console.anthropic.com))

### 1. Clone and install

```bash
git clone git@github.com:udhawan97/stock-analysis-app.git
cd stock-analysis-app

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
DASHBOARD_PASSWORD_HASH=your-bcrypt-hash
SESSION_SECRET_KEY=your-random-secret
DEBUG=True
DATABASE_URL=sqlite:///./database/portfolio.db
```

To generate your password hash:

```bash
python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('your_password'))"
```

### 3. Run the app

```bash
python run.py
```

Open [http://localhost:8000](http://localhost:8000) — you will be redirected to the login page.

- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check: [http://localhost:8000/health](http://localhost:8000/health)

### 4. Seed your portfolio

On first run, call the seed endpoint to create the default portfolio with all 10 holdings:

```bash
curl -X POST http://localhost:8000/api/portfolio/seed
```

Then update your share counts via the **Manage** button on the dashboard.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stocks/prices` | Live prices for all holdings |
| GET | `/api/stocks/price/{ticker}` | Single ticker price |
| GET | `/api/stocks/history/{ticker}?period=1mo` | Historical OHLCV data |
| GET | `/api/stocks/market-status` | US market open/closed |
| GET | `/api/portfolio/holdings` | All active holdings |
| POST | `/api/portfolio/holdings` | Add a holding |
| PUT | `/api/portfolio/holdings/{id}` | Update shares/cost |
| DELETE | `/api/portfolio/holdings/{id}` | Remove a holding |
| GET | `/api/ai/summary/{ticker}` | AI summary for one holding |
| GET | `/api/ai/summaries/all` | AI summaries for all holdings |
| GET | `/api/ai/portfolio-insight` | Portfolio-level AI analysis |
| GET | `/api/ai/cache/stats` | Cache stats and estimated cost |
| DELETE | `/api/ai/cache/clear` | Clear cached summaries |

---

## Running Tests

```bash
pytest tests/ -v
```

Tests use mocked external services — no real API calls are made during testing.

---

## Deployment (Render)

1. Push to GitHub
2. Create a new Web Service on [render.com](https://render.com) — connect this repo
3. Add environment variables in the Render dashboard (same keys as `.env`, without `DEBUG=True`)
4. Render auto-deploys on every push to `main`

Free tier note: the service sleeps after 15 minutes of inactivity and takes ~30 seconds to wake up on the next request.

---

## Cost

| Service | Cost |
|---------|------|
| yfinance (stock data) | Free |
| SQLite (database) | Free |
| Render (hosting) | Free tier |
| Claude Haiku (AI) | ~$0.002 per full portfolio refresh |
| **Total (typical month)** | **~$0.50–$2.00** |

---

## Roadmap

- [ ] Real-time WebSocket price updates
- [ ] Transaction history (buy/sell tracking)
- [ ] Price alerts via email
- [ ] PostgreSQL for persistent cloud storage
- [ ] AI-powered rebalancing suggestions
- [ ] Export portfolio to CSV

---

## License

Personal project. Not intended for redistribution or financial advice.

---

*Built as a learning project following a structured 4-week full-stack AI development curriculum.*
