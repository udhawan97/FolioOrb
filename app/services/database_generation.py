"""Process generation and cutover guard; safe to import before the database engine."""
from functools import wraps
from pathlib import Path
import threading

class _ProcessGeneration:
    def __init__(self):
        self.lock = threading.RLock()
        self.epoch = 0


_STATE = _ProcessGeneration()
_ORIGIN = "_folio_csv_origin"


def guard():
    """Use one ordering for CSV operations and supported database cutover."""
    return _STATE.lock


def identity(engine):
    """Identify the current canonical file, without opening a database connection."""
    database = engine.url.database
    if engine.dialect.name != "sqlite":
        raise OSError("CSV confirmation requires SQLite")
    if database in (None, "", ":memory:"):
        return (_STATE.epoch, "memory")
    path = Path(database).expanduser().resolve()
    if Path(str(path) + ".restore-in-progress").exists():
        raise OSError("Database recovery is incomplete")
    stat = path.stat()
    return (_STATE.epoch, str(path), stat.st_dev, stat.st_ino)


def track_connection(connection):
    """Stamp an engine once, before migrations and runtime requests use it."""
    engine = connection.engine
    if engine.dialect.name != "sqlite" or hasattr(engine, _ORIGIN):
        return
    with _STATE.lock:
        if not hasattr(engine, _ORIGIN):
            try:
                initial = identity(engine)
            except OSError:
                initial = (_STATE.epoch, "unavailable")
            setattr(engine, _ORIGIN, initial)


def origin(engine):
    return getattr(engine, _ORIGIN, None)


def guarded(function):
    @wraps(function)
    def run(*args, **kwargs):
        with _STATE.lock:
            return function(*args, **kwargs)
    return run


def replacement(function):
    """Invalidate old capabilities before any supported restore can publish bytes."""
    @wraps(function)
    def run(*args, **kwargs):
        with _STATE.lock:
            _STATE.epoch += 1
            return function(*args, **kwargs)
    return run
