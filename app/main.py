import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from starlette.middleware.gzip import GZipMiddleware
from app.routers import stocks, portfolio, ai
from app.routers import news
from app.routers import system
from app.config import settings
from app.database import engine
from app.schema_meta import apply_migrations_safely
from app.paths import resource_dir
from app.version import __version__

# Absolute paths to bundled resources so the app works whether it is run from a
# source checkout or a frozen desktop bundle (where the working directory and the
# resource location are not the same).
_RESOURCE_DIR = resource_dir()
_STATIC_DIR = _RESOURCE_DIR / "static"
_TEMPLATE_FILE = _RESOURCE_DIR / "templates" / "index.html"

logger = logging.getLogger(__name__)


def _run_startup_warmup() -> None:
    """
    Pre-fetch quotes, history, and world markets for the active holdings so the
    first dashboard load hits warm caches instead of waiting on cold Yahoo
    requests. Runs in a background thread; any failure is logged and ignored.
    """
    try:
        from app.database import SessionLocal
        from app.models import Holding
        from app.services.stock_service import DEFAULT_HOLDINGS, warm_caches
        from app.services.timing_signal import get_batched_history_closes
        from app.routers.stocks import _get_world_markets_cached

        with SessionLocal() as db:
            tickers = [
                str(row[0]).upper()
                for row in db.query(Holding.ticker)
                .filter(Holding.is_active.is_(True))
                .all()
            ] or list(DEFAULT_HOLDINGS)

        warm_caches(tickers)
        get_batched_history_closes(tickers)
        _get_world_markets_cached()
        logger.info("Startup cache warmup complete for %d tickers", len(tickers))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Startup cache warmup failed; exception_type=%s", type(exc).__name__)


# lifespan runs once when the server starts up.
# We use it to create all database tables before the app begins accepting requests.
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create tables and apply migrations inside a protected sequence: a version
    # bump on an existing database is preceded by a verified backup and, on
    # failure, restored automatically. See app/schema_meta.py.
    result = apply_migrations_safely(engine)
    if result.ran_migration:
        logger.info(
            "Schema migrated v%d -> v%d (backed_up=%s)",
            result.previous_schema_version,
            result.schema_version,
            result.backed_up,
        )
    # Warm caches off the main thread so startup isn't blocked on Yahoo.
    threading.Thread(target=_run_startup_warmup, daemon=True).start()
    # Record whether this is the first run on a freshly installed version, so the
    # UI can show a one-time "holdings intact" confirmation.
    from app.services import update_service

    update_service.note_launch()
    # Quietly check for updates ~30 s after boot, then daily (respects the
    # auto-check setting; never installs anything on its own).
    update_service.start_auto_check_scheduler()
    yield  # The app runs while we're "inside" this yield

# Create the FastAPI application instance
app = FastAPI(
    title="FolioOrb",
    description=(
        "FolioOrb helps explain portfolio movement by surfacing "
        "market context and AI-generated insights for holdings."
    ),
    version=__version__,
    lifespan=lifespan,
)

# Allow the local dashboard to call the API without exposing it to every origin.
# Methods are restricted to only what the API actually uses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)

# Serve static files (CSS, JS, images) from the /static folder
# Files at static/css/style.css → URL: /static/css/style.css
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

with open(_TEMPLATE_FILE, encoding="utf-8") as _f:
    _dashboard_html = _f.read()

# Register the route groups defined in our router files
app.include_router(stocks.router)
app.include_router(portfolio.router)
app.include_router(ai.router)
app.include_router(news.router)
app.include_router(system.router)


@app.get("/")
async def dashboard():
    """Serve the main dashboard HTML page."""
    return HTMLResponse(_dashboard_html)

@app.get("/health")
async def health_check():
    """Simple endpoint to confirm the server is running."""
    return {"status": "healthy"}
