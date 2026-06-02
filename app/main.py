from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import stocks

# ── Create the FastAPI application instance ──────────────────────────
app = FastAPI(
    title="Stock Portfolio Dashboard",
    description="AI-powered dashboard for managing and analyzing stock portfolios",
    version="0.2.0",
)

# ── CORS Middleware ───────────────────────────────────────────────────
# requests to our Python backend. Without this, the browser blocks it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────
app.include_router(stocks.router)



@app.get("/")
async def root():
    return {
        "message": "Welcome to the Stock Portfolio Dashboard API!",
        "version": "0.1.0",
        "endpoints": {
            "all_prices": "/api/stocks/prices",
            "single_price": "/api/stocks/price/{ticker}",
            "history": "/api/stocks/history/{ticker}?period=1mo",
            "docs": "/docs",
        },
    }


# ── Health Check ──────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "API is healthy and running."}
