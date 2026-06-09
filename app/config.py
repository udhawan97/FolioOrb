from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env file

# ── Configuration Settings ─────────────────────────────────────────────
class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./database/portfolio.db")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    DEBUG: bool = os.getenv("DEBUG", "True") == "True"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    APP_NAME: str = "Stock Portfolio Dashboard"
    DEFAULT_HOLDINGS: list[str] = [
        "NOW", "QTUM", "VOO", "CGDV", "IBIT",
        "VT", "ITA", "IEMG", "SETM", "WSML"
    ]

settings = Settings()

