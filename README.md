# FolioSenseAI

FolioSenseAI helps explain portfolio movement by surfacing market context, news, and AI-generated insights for holdings.

## Live Demo

> Deploy link will go here after deployment.

---

## What It Does

FolioSenseAI tracks a personal portfolio in real time, pulls market data from Yahoo Finance, and uses AI-generated context to help explain what may be moving each holding.

**Default holdings:** NOW · QTUM · VOO · CGDV · IBIT · VT · ITA · IEMG · SETM · WSML

### Dashboard

- Live prices and daily gain/loss for all holdings
- Total portfolio value and daily P&L
- Color-coded performance
- Allocation, return, and performance-history views
- Market open/closed indicator with auto-refresh countdown
- Responsive dashboard UI

### Portfolio Intelligence

- Holding-level movement explanations with market, sector, macro, news, and company context
- Portfolio-level AI analysis for diversification themes, concentration risks, and notable movers
- Holding coverage details for ETFs, sectors, regions, themes, and benchmarks
- Analyst recommendations for stocks and ETF quality labels where available

### Portfolio Management

- Add or remove holdings from the dashboard UI
- Update share counts and average cost basis
- Soft-delete holdings while preserving historical trade data

---

## Why FolioSenseAI?

FolioSenseAI turns portfolio noise into understandable signals. Instead of only showing what a holding is, it helps explain why it may be moving by connecting price action, market news, and AI-generated context.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python, FastAPI, Uvicorn |
| Database | SQLite, SQLAlchemy ORM |
| AI | Anthropic Claude |
| Market Data | yfinance |
| Frontend | Bootstrap 5, Chart.js, Vanilla JS |

---

## Project Structure

```text
FolioSenseAI/
├── app/
│   ├── main.py                 # FastAPI app, middleware, startup
│   ├── config.py               # Settings from environment variables
│   ├── database.py             # SQLAlchemy engine and session
│   ├── models.py               # Database table definitions
│   ├── schemas.py              # Pydantic request/response validation
│   ├── routers/
│   │   ├── stocks.py           # Live price and market-status endpoints
│   │   ├── portfolio.py        # Portfolio and holdings endpoints
│   │   └── ai.py               # AI insight endpoints
│   └── services/
│       ├── stock_service.py
│       ├── ai_service.py
│       ├── move_explainer.py
│       ├── holding_intelligence.py
│       ├── analyst_recommendation.py
│       ├── etf_quality.py
│       └── security_type.py
├── static/
│   ├── css/style.css
│   └── js/dashboard.js
├── templates/
│   └── index.html
├── tests/
├── database/
├── .env.example
├── requirements.txt
└── run.py
```

---

## Local Setup

### Prerequisites

- Python 3.11 or newer
- Git
- An Anthropic API key for AI features

### 1. Clone and install

```bash
git clone git@github.com:udhawan97/FolioSenseAI.git
cd FolioSenseAI

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```text
ANTHROPIC_API_KEY=your_anthropic_api_key_here
APP_SECRET_KEY=generate_a_random_string_here
DEBUG=True
DATABASE_URL=sqlite:///./database/portfolio.db
```

### 3. Run the app

```bash
python run.py
```

Open [http://localhost:8000](http://localhost:8000).

- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check: [http://localhost:8000/health](http://localhost:8000/health)

### 4. Seed your portfolio

On first run, call the seed endpoint to create the default portfolio:

```bash
curl -X POST http://localhost:8000/api/portfolio/seed
```

Then update share counts and average costs from the **Manage** button on the dashboard.

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
| GET | `/api/portfolio/value` | Portfolio value, allocation, and daily P&L |
| GET | `/api/portfolio/pnl` | Historical return and realized P&L data |
| GET | `/api/ai/summary/{ticker}` | AI summary for one holding |
| GET | `/api/ai/summaries/all` | AI summaries for all holdings |
| GET | `/api/ai/portfolio-insight` | Portfolio-level AI analysis |
| GET | `/api/ai/explain-move/{ticker}` | Movement explanation for one holding |
| GET | `/api/ai/explain-moves/all` | Movement explanations for all holdings |
| GET | `/api/ai/holding-intelligence/all` | Holding coverage and benchmark context |
| GET | `/api/ai/analyst-recommendations/all` | Analyst recommendations and ETF quality labels |
| GET | `/api/ai/cache/stats` | Cache stats and estimated cost |
| DELETE | `/api/ai/cache/clear` | Clear cached summaries |

---

## Running Tests

```bash
python -m pytest tests/ -v
```

Tests use mocked external services where practical.

---

## Deployment Notes

The current repository does not include a deployment manifest such as `render.yaml`, `vercel.json`, `netlify.toml`, a `Dockerfile`, or a `Procfile`. For deployment, create the service using the Python/FastAPI start command appropriate for your host, then set the same environment variables used in `.env`.

For Uvicorn-based hosts, the app import path is:

```text
app.main:app
```

---

## Cost

| Service | Cost |
|---------|------|
| yfinance market data | Free |
| SQLite database | Free |
| Anthropic Claude | Depends on usage |
| Hosting | Depends on provider |

---

## Roadmap

- [ ] Real-time WebSocket price updates
- [ ] Transaction history views
- [ ] Price alerts
- [ ] PostgreSQL for persistent cloud storage
- [ ] AI-powered rebalancing suggestions
- [ ] Export portfolio to CSV

---

## License

Personal project. Not intended for redistribution or financial advice.
