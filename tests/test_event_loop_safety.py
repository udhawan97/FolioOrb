"""Endpoints that block must be ``def``, so FastAPI runs them off the event loop.

FastAPI dispatches an ``async def`` endpoint onto the event loop and a plain
``def`` endpoint into a worker threadpool. The app runs a single uvicorn worker,
so there is exactly one event loop: an ``async def`` endpoint that makes a
*blocking* call — yfinance, ``requests``, the synchronous Anthropic client, or an
unbounded DB scan — holds that loop for its entire duration and every other
request queues behind it, however trivial.

That is not hypothetical here. ``GET /api/portfolio/`` is two indexed SELECTs
against local SQLite, and it is what the portfolio switcher's dropdown waits on.
When the endpoints below were ``async def``, that dropdown inherited the latency
of whichever one happened to hold the loop — up to the 15s earnings timeout, or a
full Claude round-trip.

Why this guard is an inverted list
----------------------------------
It used to be an allowlist: a table naming the endpoints known to block, checked
for still being ``def``. That shape can only rot in one direction. It never
mentioned ``news`` at all, and named 1 of 13 ``dca`` routes, so roughly thirty
blocking ``async def`` handlers were structurally invisible to it — including
``get_news_themes``, which made a synchronous Anthropic round-trip on the loop.

So the rule is inverted: **every** registered endpoint on **every** router must
be ``def`` unless it is named in ``GENUINELY_ASYNC`` below, with a reason. A new
blocking endpoint fails by default, and making one async is a deliberate edit to
this file rather than an omission from it.
"""
import importlib
import inspect
import pkgutil

import app.routers

# endpoint name -> why it is allowed to occupy the event loop.
# The bar: it must either `await` real async I/O, or do no I/O at all.
GENUINELY_ASYNC = {
    "import_holdings": "awaits UploadFile.read() — genuine async I/O",
    "verify_review_bundle_upload": "streams a bounded body and offloads verification",
    "get_market_status": "pure clock arithmetic, no I/O to hand to a thread",
}


def _all_routers():
    """Every router module under app.routers, discovered rather than listed.

    Discovery is the point: a new router file is covered the day it is added,
    which is exactly what the old hand-maintained module list failed to do.
    """
    modules = []
    for info in pkgutil.iter_modules(app.routers.__path__):
        module = importlib.import_module(f"app.routers.{info.name}")
        if hasattr(module, "router"):
            modules.append(module)
    return modules


def _registered_endpoints(module):
    """Map endpoint name -> the callable actually registered on the router.

    Read off ``router.routes`` rather than the module namespace so a decorator
    that wrapped the handler would be caught too. FastAPI keeps included routers
    nested under the app, so the router is the stable thing to inspect.
    """
    return {
        route.endpoint.__name__: route.endpoint
        for route in module.router.routes
        if getattr(route, "endpoint", None) is not None
    }


def test_every_router_is_discovered():
    """The sweep must actually see the routers, or it passes vacuously."""
    names = {m.__name__.rsplit(".", 1)[-1] for m in _all_routers()}
    assert {"ai", "dca", "news", "portfolio", "review", "stocks", "system"} <= names


def test_no_endpoint_blocks_the_event_loop():
    """Every endpoint is `def` unless explicitly excused in GENUINELY_ASYNC."""
    offenders = []
    for module in _all_routers():
        for name, endpoint in _registered_endpoints(module).items():
            if name in GENUINELY_ASYNC:
                continue
            if inspect.iscoroutinefunction(endpoint):
                offenders.append(f"{module.__name__}.{name}")
    assert not offenders, (
        "These endpoints are `async def`, so FastAPI runs them on the single "
        "event loop and every other request queues behind them. Make them "
        "`def` (FastAPI will threadpool them), or add them to GENUINELY_ASYNC "
        "with a reason if they truly await:\n  " + "\n  ".join(sorted(offenders))
    )


def test_genuinely_async_endpoints_are_still_async():
    """The excused list must not rot either — each entry stays registered and async."""
    registered = {}
    for module in _all_routers():
        registered.update(_registered_endpoints(module))

    for name, reason in GENUINELY_ASYNC.items():
        endpoint = registered.get(name)
        assert endpoint is not None, f"{name} is no longer registered ({reason})"
        assert inspect.iscoroutinefunction(endpoint), (
            f"{name} is excused from the sync rule because it {reason}, but it "
            f"is no longer `async def` — drop it from GENUINELY_ASYNC."
        )


def test_connection_pool_exceeds_request_concurrency():
    """The pool must not be the next thing that serializes those endpoints.

    Making the endpoints above sync moves them off the event loop and lets them
    run genuinely in parallel — which raises peak concurrent DB connections.
    ``get_db`` holds its connection for the whole request, network time included,
    so a pool smaller than peak concurrency just relocates the stall from the
    loop into ``QueuePool.get()``.

    FastAPI's threadpool tops out at 40 workers; startup warmup adds ~10 threads.
    The ceiling has to clear that, or the two halves of this fix cancel out.
    """
    from app.database import engine  # noqa: PLC0415 — import cost is the point

    pool = engine.pool
    ceiling = pool.size() + pool._max_overflow  # pylint: disable=protected-access
    assert ceiling >= 50, f"pool ceiling {ceiling} is below peak request concurrency"
