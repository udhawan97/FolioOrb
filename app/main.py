from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import stocks, portfolio
from app.database import engine
from app import models  # Import models so SQLAlchemy knows about them


# ── Lifespan context manager ──────────────────────────────────────────
# This runs code at server startup and shutdown
# Modern FastAPI uses this instead of the older @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    # === STARTUP ===
    print("Starting up...")
    # Create all database tables (safe to run multiple times)
    models.Base.metadata.create_all(bind=engine)
    print("Database tables created/verified.")
    yield  # Server runs here
    # === SHUTDOWN ===
    print("Shutting down...")


app = FastAPI(
    title="Stock Portfolio Dashboard",
    description="AI-powered personal portfolio tracker",
    version="0.3.0",
    lifespan=lifespan,  # ← Connect the lifespan handler
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(portfolio.router)


@app.get("/")
async def root():
    return {"message": "Stock Portfolio Dashboard API", "version": "0.3.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
