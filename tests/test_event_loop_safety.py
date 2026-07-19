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

Each entry below blocks for a reason worth naming, so a future edit can tell
whether the constraint still applies. Adding ``async`` back to any of them is the
regression this guards.
"""
import inspect

from app.routers import ai, dca, portfolio

# endpoint function name -> what blocks inside it
BLOCKING_ENDPOINTS = {
    ai: {
        "get_ai_cache_stats": "loads every AISummary row, then estimates tokens in Python",
        "get_all_move_explanations": "serial explain_move with lazy per-holding fetches",
        "get_all_intelligence": "serial get_holding_intelligence plus an ETF fan-out",
        "get_all_investment_signals": "full scan_portfolio: quotes, history, regime",
        "get_all_analyst_recommendations": "serial per-ticker .info scrape",
        "get_portfolio_summary": "snapshot build plus a synchronous Anthropic call",
        "get_action_plan": "scan_portfolio plus a synchronous Anthropic call",
    },
    portfolio: {
        "get_earnings_radar": "8-thread yfinance fan-out behind a 15s timeout",
        "get_pnl": "scans the realized-trade and snapshot tables",
        "get_portfolio_market_context": "calls the sync get_world_markets() inline",
        "get_macro_alignment": "calls the sync get_world_markets() inline",
        "get_conviction_gaps": "delegates to get_all_investment_signals",
        "get_confidence_spectrum": "delegates to get_all_investment_signals",
    },
    dca: {
        "run_catchup": "fetches daily closes per plan, serially",
    },
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


def test_blocking_endpoints_are_sync():
    """None of the blocking endpoints may be a coroutine function."""
    offenders = []
    for module, endpoints in BLOCKING_ENDPOINTS.items():
        registered = _registered_endpoints(module)
        for name, reason in endpoints.items():
            endpoint = registered.get(name)
            assert endpoint is not None, f"{module.__name__}.{name} is not registered"
            if inspect.iscoroutinefunction(endpoint):
                offenders.append(f"{module.__name__}.{name} — {reason}")
    assert not offenders, (
        "These endpoints block, so they must be `def` (threadpool) rather than "
        "`async def` (event loop):\n  " + "\n  ".join(offenders)
    )


def test_guard_covers_every_router_it_names():
    """Every name in the table above must still exist, so the guard can't rot."""
    for module, endpoints in BLOCKING_ENDPOINTS.items():
        registered = _registered_endpoints(module)
        missing = sorted(set(endpoints) - set(registered))
        assert not missing, f"{module.__name__} no longer registers: {missing}"


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


def test_csv_import_stays_async():
    """The one endpoint that genuinely awaits must keep its `async def`.

    ``import_holdings`` awaits ``UploadFile.read()``. Converting it would be a
    different bug from the one above, so pin it explicitly.
    """
    endpoint = _registered_endpoints(portfolio)["import_holdings"]
    assert inspect.iscoroutinefunction(endpoint)
