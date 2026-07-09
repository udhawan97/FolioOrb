import os
from dotenv import load_dotenv

from app.paths import data_dir, is_frozen

# Load variables from the .env file into the process environment.
# This must run before we call os.getenv() below. In a source checkout
# data_dir() is the repo root, so this loads ./.env exactly as before; in a
# frozen app it loads the .env from the per-user data directory.
load_dotenv(data_dir() / ".env")


def _csv_env(name: str, default: str = "", uppercase: bool = False) -> list[str]:
    """Parse comma-separated environment values into normalized non-empty items."""
    raw = os.getenv(name, default)
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return [item.upper() for item in items] if uppercase else items


def _default_database_url() -> str:
    """SQLite location used when DATABASE_URL is not set explicitly.

    Source runs keep the historical relative path so the working directory
    stays clean; frozen apps store the database under the per-user data dir.
    """
    if is_frozen():
        db_path = data_dir() / "database" / "portfolio.db"
        return f"sqlite:///{db_path.as_posix()}"
    return "sqlite:///./database/portfolio.db"


class Settings:
    """
    Central place for all app configuration.
    Values come from environment variables, with safe defaults for local development.
    In production, set these variables in your environment instead of the .env file.
    """
    # Path to the SQLite database file
    DATABASE_URL: str = os.getenv("DATABASE_URL") or _default_database_url()
    # Anthropic API key for AI features (leave blank to disable AI endpoints)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    # When DEBUG=True, SQLAlchemy prints every SQL query to the console.
    # Defaults to False — set DEBUG=True in .env for local development only.
    # Frozen desktop builds ship without a .env, so this stays False for users.
    DEBUG: bool = os.getenv("DEBUG", "False") == "True"
    SECRET_KEY: str = (
        os.getenv("SECRET_KEY")
        or os.getenv("APP_SECRET_KEY")
        or "change-me-in-production"
    )
    CORS_ALLOWED_ORIGINS: list[str] = _csv_env(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    )
    APP_NAME: str = "FolioOrb"
    APP_DESCRIPTION: str = (
        "FolioOrb helps explain portfolio movement by surfacing market context "
        "and AI-generated insights for holdings."
    )
    # Optional comma-separated tickers pre-loaded when the default portfolio is created.
    # Empty by default so forks do not inherit anyone's personal portfolio.
    DEFAULT_HOLDINGS: list[str] = _csv_env("DEFAULT_HOLDINGS", uppercase=True)


# Single shared settings object — import this everywhere instead of creating Settings()
settings = Settings()
