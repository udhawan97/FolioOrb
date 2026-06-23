import os
from dotenv import load_dotenv

# Load variables from the .env file into the process environment.
# This must run before we call os.getenv() below.
load_dotenv()


def _csv_env(name: str, default: str = "", uppercase: bool = False) -> list[str]:
    """Parse comma-separated environment values into normalized non-empty items."""
    raw = os.getenv(name, default)
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return [item.upper() for item in items] if uppercase else items


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
    SECRET_KEY: str = (
        os.getenv("SECRET_KEY")
        or os.getenv("APP_SECRET_KEY")
        or "change-me-in-production"
    )
    CORS_ALLOWED_ORIGINS: list[str] = _csv_env(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    )
    APP_NAME: str = "FolioSenseAI"
    APP_DESCRIPTION: str = (
        "FolioSenseAI helps explain portfolio movement by surfacing market context "
        "and AI-generated insights for holdings."
    )
    # Optional comma-separated tickers pre-loaded when the default portfolio is created.
    # Empty by default so forks do not inherit anyone's personal portfolio.
    DEFAULT_HOLDINGS: list[str] = _csv_env("DEFAULT_HOLDINGS", uppercase=True)


# Single shared settings object — import this everywhere instead of creating Settings()
settings = Settings()
