from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Create the FastAPI application instance ──────────────────────────
app = FastAPI(
    title="Stock Portfolio Dashboard",
    description="AI-powered dashboard for managing and analyzing stock portfolios",
    version="0.1.0",
)

# ── CORS Middleware ───────────────────────────────────────────────────
# CORS = Cross-Origin Resource Sharing
# This allows our HTML frontend (which the browser loads) to make API
# requests to our Python backend. Without this, the browser blocks it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────
# @app.get means: "when someone makes a GET request to this URL, run this function"
# async def means this function can pause and wait (for databases, APIs) efficiently

@app.get("/")
async def root():
    return {
        "message": "Welcome to the Stock Portfolio Dashboard API!",
        "version": "0.1.0",
        "docs": "Vist /docs for API documentation.",
        "portfolio": [
            "NOW",
            "QTUM",
            "VOO",
            "CGDV",
            "IBIT",
            "VT",
            "ITA",
            "IEMG",
            "SETM",
            "WSML",
        ],
    }


# ── Health Check ──────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "API is healthy and running."}
