import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

# Create the database directory if it doesn't already exist
os.makedirs("database", exist_ok=True)

_IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")

# Create the database engine — this is the single connection to our SQLite file.
# check_same_thread=False is required by SQLite when used with FastAPI's async workers.
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG,  # Prints all SQL queries to the console when DEBUG=True
)


if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        """
        Tune SQLite for the app's concurrency profile. Sync FastAPI handlers run in
        a threadpool and a background warmup thread plus several ThreadPoolExecutors
        issue reads/writes at once, so plain rollback-journal mode raises
        "database is locked" under contention.

        WAL lets readers and a writer proceed concurrently; busy_timeout makes a
        blocked writer wait instead of failing immediately; synchronous=NORMAL is
        the safe, faster pairing with WAL for a local single-file app.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

# SessionLocal is a factory: calling SessionLocal() opens a new database session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# All SQLAlchemy models must inherit from this Base class so SQLAlchemy
# knows which classes represent database tables
class Base(DeclarativeBase):
    pass


def get_db():
    """
    FastAPI dependency that provides a database session for each request.

    Usage in a route:
        @router.get("/example")
        def my_route(db: Session = Depends(get_db)):
            ...

    The session is automatically closed after the request finishes,
    even if an error occurred (guaranteed by the finally block).
    """
    db = SessionLocal()
    try:
        yield db  # FastAPI injects this db object into the route function
    finally:
        db.close()


def ensure_startup_migrations():
    """Apply tiny idempotent SQLite migrations that create_all cannot cover."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(holdings)")).fetchall()
        }
        if "hold_class" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE holdings "
                    "ADD COLUMN hold_class VARCHAR(20) NOT NULL DEFAULT 'auto'"
                )
            )
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "verdict_snapshots" not in tables:
            conn.execute(
                text(
                    "CREATE TABLE verdict_snapshots ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "ticker VARCHAR(10) NOT NULL, "
                    "action VARCHAR(20) NOT NULL, "
                    "confidence INTEGER NOT NULL DEFAULT 0, "
                    "local_score INTEGER, "
                    "ai_score INTEGER, "
                    "price_at_scan FLOAT, "
                    "hold_class VARCHAR(20) NOT NULL DEFAULT 'auto', "
                    "generated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            conn.execute(
                text("CREATE INDEX ix_verdict_snapshots_ticker ON verdict_snapshots (ticker)")
            )
            conn.execute(
                text(
                    "CREATE INDEX ix_verdict_snapshots_generated_at "
                    "ON verdict_snapshots (generated_at)"
                )
            )

        _ensure_performance_indexes(conn, tables)


def _ensure_performance_indexes(conn, tables: set) -> None:
    """
    Add composite indexes that back the app's hot query paths, plus a UNIQUE index
    that enforces one portfolio_snapshots row per (portfolio_id, snapshot_date).

    Idempotent (CREATE INDEX IF NOT EXISTS). Existing databases predating the unique
    index may already hold duplicate snapshot rows, so those are collapsed to the
    most recent row per day before the unique index is created.
    """
    # Holdings: every dashboard read filters portfolio_id + is_active.
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_holdings_portfolio_active "
            "ON holdings (portfolio_id, is_active)"
        )
    )

    # Realized trades: filtered by portfolio_id (and grouped by ticker).
    if "realized_trades" in tables:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_realized_trades_pid_ticker "
                "ON realized_trades (portfolio_id, ticker)"
            )
        )

    # Portfolio snapshots: one row per portfolio per day (upserted on refresh).
    if "portfolio_snapshots" in tables:
        conn.execute(
            text(
                "DELETE FROM portfolio_snapshots WHERE id NOT IN ("
                "SELECT MAX(id) FROM portfolio_snapshots "
                "GROUP BY portfolio_id, snapshot_date)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_portfolio_snapshots_pid_date "
                "ON portfolio_snapshots (portfolio_id, snapshot_date)"
            )
        )
