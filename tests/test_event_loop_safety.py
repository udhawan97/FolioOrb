"""Endpoints that block must be ``def``, so FastAPI runs them off the event loop.

FastAPI dispatches an ``async def`` endpoint onto the event loop and a plain
``def`` endpoint into a worker threadpool. The app runs a single uvicorn worker,
so there is exactly one event loop: an ``async def`` endpoint that makes a
*blocking* call — yfinance, ``requests``, the synchronous Anthropic client, or an
unbounded DB scan — holds that loop for its entire duration and every other
request queues behind it, however trivial.

That is not hypothetical here. ``GET /api/portfolio/`` is two indexed SELECTs
against local SQLite, and it is what the portfolio switcher's dropdown waits on.
When these endpoints were ``async def``, that dropdown inherited the latency of
whichever one happened to hold the loop — up to the 15s earnings timeout, or a
full Claude round-trip.

This guard used to name the blocking endpoints one by one. That list could only
ever catch a regression on a name somebody remembered to add to it, and fifty-six
endpoints were written as ``async def`` without ever appearing in it. So the
default is inverted: **every** registered endpoint must be ``def``, and the few
that genuinely await say so in ``AWAITS`` below. A new blocking endpoint is now
caught the moment it is registered, without anyone maintaining a list.
"""
import inspect

from app.routers import ai, dca, news, portfolio, review, stocks, system

ROUTERS = (ai, dca, news, portfolio, review, stocks, system)

# The only endpoints allowed to be `async def`, and the await that earns it.
# Anything here must genuinely suspend — an `async def` that never awaits is the
# bug this module exists to prevent, not an exemption from it.
AWAITS = {
    "import_holdings": "awaits UploadFile.read() on the uploaded CSV",
}


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


def test_every_endpoint_is_sync_unless_it_awaits():
    """No endpoint may be a coroutine function unless ``AWAITS`` justifies it."""
    offenders = []
    for module in ROUTERS:
        for name, endpoint in _registered_endpoints(module).items():
            if inspect.iscoroutinefunction(endpoint) and name not in AWAITS:
                offenders.append(f"{module.__name__}.{name}")
    assert not offenders, (
        "These endpoints run on the event loop and block it. Make them `def` so "
        "FastAPI runs them in the threadpool, or add them to AWAITS with the "
        "await that justifies it:\n  " + "\n  ".join(sorted(offenders))
    )


def test_awaiting_endpoints_still_await():
    """Every name in ``AWAITS`` must exist and still be a coroutine function.

    Converting one of these to ``def`` would block the loop on a real ``await``,
    which is a different bug from the one above — so pin it from both sides.
    """
    registered = {}
    for module in ROUTERS:
        registered.update(_registered_endpoints(module))
    for name, reason in AWAITS.items():
        endpoint = registered.get(name)
        assert endpoint is not None, f"AWAITS names {name}, which is not registered"
        assert inspect.iscoroutinefunction(endpoint), f"{name} no longer awaits: {reason}"


def test_guard_sees_every_router():
    """A router missing from ``ROUTERS`` would be silently unguarded."""
    from app.main import app  # noqa: PLC0415 — importing the built app is the point

    guarded = {name for module in ROUTERS for name in _registered_endpoints(module)}
    live = {
        route.endpoint.__name__
        for route in app.routes
        if getattr(route, "endpoint", None) is not None
        and str(getattr(route, "path", "")).startswith("/api/")
    }
    assert not live - guarded, f"unguarded API endpoints: {sorted(live - guarded)}"


def test_connection_pool_exceeds_request_concurrency():
    """The pool must not be the next thing that serializes those endpoints.

    Making the endpoints sync moves them off the event loop and lets them run
    genuinely in parallel — which raises peak concurrent DB connections.
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
