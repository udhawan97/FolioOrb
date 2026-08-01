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

# Coroutine endpoints that are not ours to convert, or that hold the loop for a
# bounded constant time rather than for I/O. Kept apart from AWAITS so the rule
# there stays exactly "it suspends"; these are simply out of scope.
NOT_BLOCKING = {
    "openapi": "FastAPI's own schema route",
    "swagger_ui_html": "FastAPI's own docs route",
    "swagger_ui_redirect": "FastAPI's own docs route",
    "redoc_html": "FastAPI's own docs route",
    "dashboard": "returns the template string read once at import — no I/O",
    "health_check": "returns a literal dict — no I/O",
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


def _walk_endpoints(router):
    """Every endpoint reachable from ``router``, however deeply nested.

    FastAPI does not keep included routers flat on ``app.routes``. Each one
    arrives wrapped in a ``_IncludedRouter`` that holds the real ``APIRouter``
    under ``original_router`` — and whose own ``routes`` attribute is a *string*,
    so a naive recursion iterates it character by character, finds no endpoints,
    and terminates. Walking only the top level, or walking it naively, yields the
    four docs routes and nothing else: a guard built on either compares against
    an effectively empty set and passes whatever is registered. The size floor in
    the test below exists because that failure is otherwise silent.
    """
    nested = getattr(router, "original_router", None)
    if nested is not None:
        yield from _walk_endpoints(nested)
        return
    routes = getattr(router, "routes", None)
    if not isinstance(routes, (list, tuple)):
        return
    for route in routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            yield endpoint
        else:
            yield from _walk_endpoints(route)


def test_guard_sees_every_router():
    """A router missing from ``ROUTERS`` would be silently unguarded."""
    from app.main import app  # noqa: PLC0415 — importing the built app is the point

    guarded = {name for module in ROUTERS for name in _registered_endpoints(module)}
    live = {endpoint.__name__ for endpoint in _walk_endpoints(app)}
    # Sanity floor: the walk must actually find the API, or this proves nothing.
    assert len(live) > 90, f"route walk found only {len(live)} endpoints"
    stale = sorted(guarded - live)
    assert not stale, f"guard names endpoints the app never registers: {stale}"

    unguarded = live - guarded - set(NOT_BLOCKING)
    assert not unguarded, f"unguarded endpoints: {sorted(unguarded)}"


def test_every_reachable_endpoint_is_sync_unless_it_awaits():
    """The same rule, applied to the built app rather than the router modules.

    ``test_every_endpoint_is_sync_unless_it_awaits`` trusts ``ROUTERS`` to be
    complete. This one trusts nothing and walks what the app actually serves.
    """
    from app.main import app  # noqa: PLC0415 — importing the built app is the point

    allowed = set(AWAITS) | set(NOT_BLOCKING)
    offenders = sorted(
        endpoint.__name__
        for endpoint in _walk_endpoints(app)
        if inspect.iscoroutinefunction(endpoint) and endpoint.__name__ not in allowed
    )
    assert not offenders, f"these endpoints block the event loop: {offenders}"


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
