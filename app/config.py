import logging
import os
from dotenv import load_dotenv

from app.paths import prepare_runtime_profile
from app.services.ticker import ticker_shape_is_safe

logger = logging.getLogger(__name__)

# Resolve the database and writable data root as one profile before any launcher
# can create a database/WAL, backup lock, settings file, update marker, or legacy
# migration. Only after the read-only validation passes is the root prepared and
# its dotenv loaded (process values still win because override=False).
_RUNTIME_PROFILE = prepare_runtime_profile()
load_dotenv(_RUNTIME_PROFILE.env_source, override=False)
# Dotenv may contain stale ownership keys from an older development setup. The
# profile was already selected and validated before dotenv loading, so freeze
# both ownership values to that exact result. This prevents later ``data_dir``
# callers from recomputing a different root while SQLAlchemy keeps the original
# database URL.
os.environ["FOLIOORB_DATA_DIR"] = str(_RUNTIME_PROFILE.data_root)
os.environ["DATABASE_URL"] = _RUNTIME_PROFILE.database_url


def _csv_env(name: str, default: str = "", uppercase: bool = False) -> list[str]:
    """Parse comma-separated environment values into normalized non-empty items."""
    raw = os.getenv(name, default)
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return [item.upper() for item in items] if uppercase else items


def _seed_tickers(name: str) -> list[str]:
    """Comma-separated seed symbols, keeping only those shaped like a ticker.

    Named rather than dropped silently: this is the one path that seeds a holding
    without going through the request schemas, so a typo in `.env` would otherwise
    plant a row nothing can price and give no clue why it never loads.
    """
    kept, skipped = [], []
    for symbol in _csv_env(name, uppercase=True):
        (kept if ticker_shape_is_safe(symbol) else skipped).append(symbol)
    if skipped:
        logger.warning(
            "Ignoring %s entries that are not shaped like a ticker: %s",
            name,
            ", ".join(skipped),
        )
    return kept


class Settings:
    """
    Central place for all app configuration.
    Values come from environment variables, with safe defaults for local development.
    In production, set these variables in your environment instead of the .env file.
    """
    # Path to the SQLite database file
    DATABASE_URL: str = _RUNTIME_PROFILE.database_url
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
    DEFAULT_HOLDINGS: list[str] = _seed_tickers("DEFAULT_HOLDINGS")


# Single shared settings object — import this everywhere instead of creating Settings()
settings = Settings()
