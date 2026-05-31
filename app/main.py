from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Stock Portfolio Dashboard",
    description="AI-powered dashboard for managing and analyzing stock portfolios",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "API is healthy and running."}
