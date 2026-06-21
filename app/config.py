import os
from dotenv import load_dotenv

# Load variables from the .env file into the process environment.
# This must run before we call os.getenv() below.
load_dotenv()


class Settings:
    """
    Central place for all app configuration.
    Values come from environment variables, with safe defaults for local development.
    In production, set these variables in your environment instead of the .env file.
    """
    # Path to the SQLite database file
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./database/portfolio.db")
    # Anthropic API key for AI features (leave blank to disable AI endpoints)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    # When DEBUG=True, SQLAlchemy prints every SQL query to the console
    DEBUG: bool = os.getenv("DEBUG", "True") == "True"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    APP_NAME: str = "FolioSenseAI"
    APP_DESCRIPTION: str = (
        "FolioSenseAI helps explain portfolio movement by surfacing market context, "
        "news, and AI-generated insights for holdings."
    )
    # Default stock tickers pre-loaded when seeding the portfolio for the first time
    DEFAULT_HOLDINGS: list[str] = [
        "NOW", "QTUM", "VOO", "CGDV", "IBIT",
        "VT", "ITA", "IEMG", "SETM", "WSML",
    ]


# Single shared settings object — import this everywhere instead of creating Settings()
settings = Settings()
