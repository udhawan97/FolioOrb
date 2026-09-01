"""The world-markets fan-out and its cache, now that both live below the routers.

This used to be a hand-rolled `(expiry, payload)` global inside the stocks
router, which forced `app/main.py` to import a private router function to warm
it. The behaviour pinned here is what moving it under `ttl_cache` bought:
memoisation, a fresh list per caller, and no caching of a fully-dead strip.
"""
from app.routers import stocks as stocks_router
from app.services import world_markets


def _priced(ticker="^GSPC", price=100.0):
    return {"ticker": ticker, "name": "Index", "region": "US", "flag": "US",
            "available": True, "price": price,
            "day_change": 1.0, "day_change_pct": 1.0}


def _dead(ticker="^GSPC"):
    return {"ticker": ticker, "name": "Index", "region": "US", "flag": "US",
            "available": False, "price": None,
            "day_change": None, "day_change_pct": None}


def test_a_successful_fan_out_is_fetched_once(monkeypatch):
    calls = []

    def fetch(market):
        calls.append(market["ticker"])
        return _priced(market["ticker"])

    monkeypatch.setattr(world_markets, "fetch_world_market", fetch)

    first = world_markets.get_world_markets_cached()
    second = world_markets.get_world_markets_cached()

    assert len(first) == len(world_markets.WORLD_MARKETS)
    assert first == second
    assert len(calls) == len(world_markets.WORLD_MARKETS)  # not twice


def test_each_caller_gets_its_own_list(monkeypatch):
    monkeypatch.setattr(
        world_markets, "fetch_world_market", lambda m: _priced(m["ticker"])
    )

    first = world_markets.get_world_markets_cached()
    first.clear()

    assert len(world_markets.get_world_markets_cached()) == len(
        world_markets.WORLD_MARKETS
    )


def test_a_fully_dead_strip_is_retried_rather_than_remembered(monkeypatch):
    """A brief Yahoo outage must not pin an all-zero strip for the window."""
    attempts = []

    def fetch(market):
        attempts.append(market["ticker"])
        return _dead(market["ticker"])

    monkeypatch.setattr(world_markets, "fetch_world_market", fetch)

    world_markets.get_world_markets_cached()
    first_round = len(attempts)
    world_markets.get_world_markets_cached()

    assert len(attempts) == first_round * 2


def test_fetch_world_market_never_raises(monkeypatch):
    def boom(_ticker):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr(world_markets.market_data, "get_fast_info", boom)

    row = world_markets.fetch_world_market(world_markets.WORLD_MARKETS[0])

    assert row["available"] is False
    assert row["price"] is None and row["day_change_pct"] is None
    assert row["name"] == world_markets.WORLD_MARKETS[0]["name"]


def test_genuine_flat_market_remains_available(monkeypatch):
    monkeypatch.setattr(
        world_markets.market_data,
        "get_fast_info",
        lambda _ticker: {"last_price": 100.0, "previous_close": 100.0},
    )

    row = world_markets.fetch_world_market(world_markets.WORLD_MARKETS[0])

    assert row["available"] is True
    assert row["price"] == 100.0
    assert row["day_change"] == 0.0
    assert row["day_change_pct"] == 0.0


def test_partial_quote_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(
        world_markets.market_data,
        "get_fast_info",
        lambda _ticker: {"last_price": 100.0, "previous_close": None},
    )

    row = world_markets.fetch_world_market(world_markets.WORLD_MARKETS[0])

    assert row["available"] is False
    assert row["price"] is None
    assert row["day_change"] is None
    assert row["day_change_pct"] is None


def test_mixed_fan_out_keeps_rows_independent_and_caches_the_live_rows(monkeypatch):
    calls = []
    first_ticker = world_markets.WORLD_MARKETS[0]["ticker"]

    def fetch(market):
        calls.append(market["ticker"])
        if market["ticker"] == first_ticker:
            return _dead(market["ticker"])
        return _priced(market["ticker"])

    monkeypatch.setattr(world_markets, "fetch_world_market", fetch)

    first = world_markets.get_world_markets_cached()
    second = world_markets.get_world_markets_cached()

    assert first == second
    assert first[0]["available"] is False
    assert all(row["available"] is True for row in first[1:])
    assert len(calls) == len(world_markets.WORLD_MARKETS)


def test_the_router_and_the_startup_warmup_share_one_cache(monkeypatch):
    """The layering fix: neither caller reaches into the other.

    `app.main` used to do `from app.routers.stocks import
    _get_world_markets_cached` — the composition root importing a private name
    out of an HTTP router, purely because the cache lived in the wrong layer.
    """
    calls = []
    monkeypatch.setattr(
        world_markets,
        "fetch_world_market",
        lambda m: (calls.append(m["ticker"]), _priced(m["ticker"]))[1],
    )

    warmed = world_markets.get_world_markets_cached()
    served = stocks_router.get_world_markets()

    assert served["markets"] == warmed
    assert len(calls) == len(world_markets.WORLD_MARKETS)  # warmup primed it
    # The router no longer owns a cache for anyone else to reach into.
    assert not hasattr(stocks_router, "_get_world_markets_cached")
    assert not hasattr(stocks_router, "_WORLD_MARKETS_CACHE")
