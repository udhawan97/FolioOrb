"""A symbol arriving as a URL path segment must pass the ticker-shape rule.

``app/services/ticker.py`` exists so one definition of "what a symbol is" can be
applied *before* the value reaches a vendor URL or a log line. Request **bodies**
get that for free through ``app/schemas.py``; the read side did not. Of the ten
``/{ticker}`` routes, only ``/insider-activity`` and ``/fundamentals`` checked
the shape — the other eight handed the raw path segment to the services. An
80-character junk symbol was answered with 200 by every unguarded route and 422
by the two guarded ones.

Why this guard is an inverted list
----------------------------------
Like ``tests/test_event_loop_safety.py``, the rule is inverted: **every**
registered route carrying a ``{ticker}`` path parameter must reject a malformed
symbol, unless it is named in ``SHAPE_EXEMPT`` with a reason. A new ``/{ticker}``
route added without the guard fails by default, rather than being invisible to a
list someone forgot to extend.
"""

import importlib
import pkgutil

import pytest

import app.routers
from app.routers import stocks
from app.services.ticker import TICKER_SHAPE_MESSAGE

# route path -> why it may accept a symbol this rule would reject.
SHAPE_EXEMPT: dict[str, str] = {}

# Rejected by TICKER_PATTERN: 80 chars (max is 10) and a '/'-free payload, so it
# survives routing and reaches the handler exactly as a real caller would send it.
HOSTILE_SYMBOL = "A" * 80

# Short enough to clear a route's own `max_length` constraint, so the rejection
# has to come from the ticker rule rather than incidentally from a length check.
# `;` is outside TICKER_PATTERN.
HOSTILE_SHORT = "AA;RM"


def _all_routers():
    """Every router module under app.routers, discovered rather than listed."""
    modules = []
    for info in pkgutil.iter_modules(app.routers.__path__):
        module = importlib.import_module(f"app.routers.{info.name}")
        if hasattr(module, "router"):
            modules.append(module)
    return modules


def _ticker_path_routes():
    """(module, route) for every registered GET route with a {ticker} segment."""
    found = []
    for module in _all_routers():
        for route in module.router.routes:
            path = getattr(route, "path", "")
            if "{ticker}" in path and "GET" in getattr(route, "methods", set()):
                found.append((module, route))
    return found


def test_the_sweep_actually_finds_the_ticker_routes():
    # A discovery bug would make every parametrised case below vacuously pass.
    # Pinned exactly: a new /{ticker} route should update this number knowingly.
    assert len(_ticker_path_routes()) == 10


@pytest.mark.parametrize(
    "module,route",
    _ticker_path_routes(),
    ids=[f"{m.__name__.split('.')[-1]}:{r.path}" for m, r in _ticker_path_routes()],
)
def test_malformed_path_ticker_is_rejected(module, route, api_client):
    if route.path in SHAPE_EXEMPT:
        pytest.skip(SHAPE_EXEMPT[route.path])

    client = api_client(module.router)
    url = route.path.replace("{ticker}", HOSTILE_SYMBOL)
    response = client.get(url)

    assert response.status_code == 422, (
        f"{route.path} accepted a malformed symbol ({response.status_code}); "
        "the raw path segment reaches the services and the vendor URL"
    )
    # 422 for the right reason: a missing unrelated required parameter would
    # also be a 422, and would satisfy the sweep without the guard.
    assert TICKER_SHAPE_MESSAGE in response.text, (
        f"{route.path} returned 422 for some other reason than the ticker shape"
    )


def _symbol_query_routes():
    """(module, route, param) for every GET route taking a symbol as a query param.

    Keyed on the parameter *name*, so a third `?tickers=` route added later is
    swept automatically rather than needing to be remembered here — the path
    sweep above could never see these, and both routes that carry a symbol this
    way were unguarded until they were found in review.
    """
    found = []
    for module in _all_routers():
        for route in module.router.routes:
            if "GET" not in getattr(route, "methods", set()):
                continue
            if "{ticker}" in getattr(route, "path", ""):
                continue
            for param in getattr(getattr(route, "dependant", None), "query_params", []):
                if param.name in {"ticker", "tickers"}:
                    found.append((module, route, param.name))
    return found


def test_the_query_param_sweep_finds_both_known_carriers():
    paths = {route.path for _m, route, _p in _symbol_query_routes()}
    assert {"/api/stocks/history/batch", "/api/review/compare"} <= paths, paths


@pytest.mark.parametrize(
    "module,route,param",
    _symbol_query_routes(),
    ids=[f"{r.path}?{p}" for _m, r, p in _symbol_query_routes()],
)
def test_a_symbol_in_the_query_string_is_checked_too(module, route, param, api_client):
    client = api_client(module.router)
    response = client.get(f"{route.path}?{param}={HOSTILE_SHORT}")

    assert response.status_code == 422, (
        f"{route.path}?{param}= forwarded a malformed symbol "
        f"({response.status_code}); a symbol in the query string is still a symbol"
    )
    assert TICKER_SHAPE_MESSAGE in response.text, (
        f"{route.path}?{param}= returned 422 for some other reason than the "
        "ticker shape — a length or type constraint is not the shape rule"
    )


def test_batch_history_still_accepts_valid_symbols(api_client):
    client = api_client(stocks.router)
    assert client.get("/api/stocks/history/batch?tickers=AAPL,msft").status_code == 200
