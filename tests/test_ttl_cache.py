"""Tests for the shared TTL cache decorator.

The clock is injected everywhere, so nothing here sleeps: a window closes the
moment a test says it does.
"""
# The stub fetchers declare parameters they never read — the point of several
# tests is what the wrapper does with a parameter, not what the body does.
# pylint: disable=unused-argument
from __future__ import annotations

import threading

import pytest

from app.services.ttl_cache import clear_all, ttl_cache


class _Clock:
    """Stand-in for ``time.monotonic`` that only moves when a test says so."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _counting_fetcher(clock: _Clock, ttl: float = 100.0, **options):
    """A fetcher that records every call it was allowed to make."""
    calls: list[str] = []

    @ttl_cache(ttl=ttl, now=clock, **options)
    def fetch(ticker: str) -> str:
        calls.append(ticker)
        return f"quote:{ticker}"

    return fetch, calls


# ── Hit and miss ──────────────────────────────────────────────────────────────

def test_second_call_is_served_from_the_store():
    clock = _Clock()
    fetch, calls = _counting_fetcher(clock)

    assert fetch("AAPL") == "quote:AAPL"
    assert fetch("AAPL") == "quote:AAPL"
    assert calls == ["AAPL"]


def test_distinct_arguments_get_distinct_entries():
    clock = _Clock()
    fetch, calls = _counting_fetcher(clock)

    fetch("AAPL")
    fetch("MSFT")
    fetch("AAPL")

    assert calls == ["AAPL", "MSFT"]


def test_entries_carry_the_expiry_payload_shape_the_app_already_uses():
    clock = _Clock(start=1_000.0)
    fetch, _ = _counting_fetcher(clock, ttl=300)

    fetch("AAPL")

    assert fetch.cache == {("AAPL",): (1_300.0, "quote:AAPL")}


# ── Expiry ────────────────────────────────────────────────────────────────────

def test_entry_is_refetched_once_its_window_closes():
    clock = _Clock()
    fetch, calls = _counting_fetcher(clock, ttl=100)

    fetch("AAPL")
    clock.advance(99)
    fetch("AAPL")
    clock.advance(2)
    fetch("AAPL")

    assert calls == ["AAPL", "AAPL"]


def test_an_entry_expires_exactly_at_its_expiry_not_after():
    clock = _Clock()
    fetch, calls = _counting_fetcher(clock, ttl=100)

    fetch("AAPL")
    clock.advance(100)
    fetch("AAPL")

    assert calls == ["AAPL", "AAPL"]


def test_refetch_extends_the_window_from_the_new_call():
    clock = _Clock(start=1_000.0)
    fetch, _ = _counting_fetcher(clock, ttl=100)

    fetch("AAPL")
    clock.advance(150)
    fetch("AAPL")

    assert fetch.cache[("AAPL",)][0] == 1_250.0


def test_expired_entries_are_evicted_on_the_next_store():
    clock = _Clock()
    fetch, _ = _counting_fetcher(clock, ttl=100)

    fetch("AAPL")
    clock.advance(200)
    fetch("MSFT")

    assert list(fetch.cache) == [("MSFT",)]


# ── force_refresh ─────────────────────────────────────────────────────────────

def test_force_refresh_bypasses_a_live_entry():
    clock = _Clock()
    fetch, calls = _counting_fetcher(clock)

    fetch("AAPL")
    fetch("AAPL", force_refresh=True)

    assert calls == ["AAPL", "AAPL"]


def test_force_refresh_replaces_the_stored_entry():
    clock = _Clock(start=1_000.0)
    fetch, _ = _counting_fetcher(clock, ttl=100)

    fetch("AAPL")
    clock.advance(10)
    fetch("AAPL", force_refresh=True)

    assert fetch.cache[("AAPL",)] == (1_110.0, "quote:AAPL")


def test_a_fetcher_that_ignores_force_refresh_never_sees_it():
    clock = _Clock()
    seen: list[dict] = []

    @ttl_cache(ttl=100, now=clock)
    def fetch(ticker: str, **extra) -> str:
        seen.append(dict(extra))
        return ticker

    assert fetch("AAPL", force_refresh=True) == "AAPL"
    assert seen == [{}]


def test_a_fetcher_that_declares_force_refresh_has_it_forwarded():
    clock = _Clock()
    seen: list[bool] = []

    @ttl_cache(ttl=100, now=clock)
    def fetch(ticker: str, *, force_refresh: bool = False) -> str:
        seen.append(force_refresh)
        return ticker

    fetch("AAPL", force_refresh=True)
    fetch("MSFT")

    assert seen == [True, False]


def test_force_refresh_never_takes_part_in_the_key():
    clock = _Clock()
    calls: list[str] = []

    @ttl_cache(ttl=100, now=clock)
    def fetch(ticker: str, *, force_refresh: bool = False) -> str:
        calls.append(ticker)
        return ticker

    fetch("AAPL", force_refresh=True)
    fetch("AAPL")

    assert calls == ["AAPL"]
    assert list(fetch.cache) == [("AAPL",)]


def test_a_positional_force_refresh_is_rejected_at_decoration_time():
    with pytest.raises(TypeError, match="keyword-only"):

        @ttl_cache(ttl=100)
        def _fetch(ticker: str, force_refresh: bool = False) -> str:
            return ticker


# ── TTL as a callable ─────────────────────────────────────────────────────────

def test_a_callable_ttl_is_read_at_store_time():
    clock = _Clock()
    window = {"seconds": 60.0}  # the market-hours TTL, in miniature
    calls: list[str] = []

    @ttl_cache(ttl=lambda: window["seconds"], now=clock)
    def fetch(ticker: str) -> str:
        calls.append(ticker)
        return ticker

    fetch("AAPL")
    clock.advance(100)

    window["seconds"] = 900.0  # market closed: remember it far longer
    fetch("AAPL")
    clock.advance(100)
    fetch("AAPL")

    assert calls == ["AAPL", "AAPL"]


# ── Key derivation ────────────────────────────────────────────────────────────

def test_a_key_function_collapses_calls_onto_one_entry():
    clock = _Clock()
    calls: list[str] = []

    @ttl_cache(ttl=100, now=clock, key=lambda ticker: ticker.upper())
    def fetch(ticker: str) -> str:
        calls.append(ticker)
        return ticker

    fetch("aapl")
    fetch("AAPL")

    assert calls == ["aapl"]
    assert list(fetch.cache) == ["AAPL"]


def test_a_key_function_mirrors_the_fetchers_parameter_names():
    clock = _Clock()

    @ttl_cache(ttl=100, now=clock, key=lambda ticker, period: (ticker.upper(), period))
    def fetch(ticker: str, period: str = "1mo") -> str:
        return f"{ticker}:{period}"

    fetch("aapl", "1y")

    assert list(fetch.cache) == [("AAPL", "1y")]


def test_omitted_arguments_land_on_the_same_entry_as_their_defaults():
    clock = _Clock()
    calls: list[tuple[str, str]] = []

    @ttl_cache(ttl=100, now=clock)
    def fetch(ticker: str, period: str = "1mo") -> str:
        calls.append((ticker, period))
        return f"{ticker}:{period}"

    fetch("AAPL")
    fetch("AAPL", "1mo")
    fetch("AAPL", period="1mo")

    assert calls == [("AAPL", "1mo")]


def test_a_key_function_can_ignore_an_argument_that_is_not_identity():
    clock = _Clock()
    calls: list[float] = []

    # A per-call timeout says how to fetch, not what is fetched.
    @ttl_cache(ttl=100, now=clock, key=lambda timeout: None)
    def heartbeat(timeout: float = 2.0) -> str:
        calls.append(timeout)
        return "live"

    heartbeat()
    heartbeat(timeout=5.0)

    assert calls == [2.0]


def test_keyword_only_and_variadic_arguments_reach_the_default_key():
    clock = _Clock()

    @ttl_cache(ttl=100, now=clock)
    def fetch(ticker: str, *forms: str, limit: int = 8, **extra) -> str:
        return ticker

    fetch("AAPL", "8-K", limit=3, source="edgar")

    assert list(fetch.cache) == [
        ("AAPL", "8-K", ("limit", 3), ("source", "edgar")),
    ]


# ── What is worth remembering ─────────────────────────────────────────────────

def test_a_raised_exception_is_never_remembered():
    clock = _Clock()
    calls: list[str] = []

    @ttl_cache(ttl=100, now=clock)
    def fetch(ticker: str) -> str:
        calls.append(ticker)
        raise RuntimeError("EDGAR is down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            fetch("AAPL")

    assert calls == ["AAPL", "AAPL"]
    assert not fetch.cache


@pytest.mark.parametrize("empty", [None, [], {}, 0, ""])
def test_empty_answers_are_remembered_by_default(empty):
    clock = _Clock()
    calls: list[str] = []

    @ttl_cache(ttl=100, now=clock)
    def fetch(ticker: str):
        calls.append(ticker)
        return empty

    assert fetch("AAPL") == empty
    assert fetch("AAPL") == empty
    assert calls == ["AAPL"]


def test_cache_when_keeps_an_empty_answer_out_of_the_store():
    clock = _Clock()
    rows: list[dict] = []
    calls: list[str] = []

    @ttl_cache(ttl=100, now=clock, cache_when=bool)
    def fetch(ticker: str) -> list[dict]:
        calls.append(ticker)
        return list(rows)

    assert not fetch("AAPL")
    rows.append({"close": 1.0})
    assert fetch("AAPL") == [{"close": 1.0}]
    assert fetch("AAPL") == [{"close": 1.0}]

    assert calls == ["AAPL", "AAPL"]


def test_cache_when_sees_the_returned_value():
    clock = _Clock()
    seen: list[dict] = []

    @ttl_cache(ttl=100, now=clock, cache_when=lambda result: not result.get("error"))
    def fetch(ticker: str) -> dict:
        seen.append({"ticker": ticker})
        return {"ticker": ticker, "error": "unavailable"}

    fetch("AAPL")
    fetch("AAPL")

    assert not fetch.cache
    assert len(seen) == 2


# ── Aliasing ──────────────────────────────────────────────────────────────────

def test_without_copy_callers_share_the_stored_payload():
    clock = _Clock()

    @ttl_cache(ttl=100, now=clock)
    def fetch(ticker: str) -> list[str]:
        return [ticker]

    assert fetch("AAPL") is fetch("AAPL")


def test_copy_hands_every_caller_its_own_payload():
    clock = _Clock()

    @ttl_cache(ttl=100, now=clock, copy=list)
    def fetch(ticker: str) -> list[str]:
        return [ticker]

    first = fetch("AAPL")
    first.append("corrupted")

    assert fetch("AAPL") == ["AAPL"]


def test_a_rejected_value_is_returned_without_being_copied():
    # Lets a fetcher answer "couldn't resolve this" with a value the copier
    # can't touch — the sentinel edgar needs to tell an empty filing list
    # apart from an unresolvable ticker.
    clock = _Clock()

    @ttl_cache(
        ttl=100,
        now=clock,
        cache_when=lambda rows: rows is not None,
        copy=list,
    )
    def fetch(ticker: str) -> list[str] | None:
        return None if ticker == "VOO" else [ticker]

    assert fetch("VOO") is None
    assert not fetch.cache
    assert fetch("AAPL") == ["AAPL"]


def test_copy_protects_the_entry_from_the_call_that_created_it():
    clock = _Clock()

    @ttl_cache(ttl=100, now=clock, copy=dict)
    def fetch(ticker: str) -> dict:
        return {"ticker": ticker}

    fetch("AAPL")["ticker"] = "corrupted"

    assert fetch("AAPL") == {"ticker": "AAPL"}


def test_copy_is_only_as_deep_as_the_copier_given():
    # `dict` protects the top level and shares what's nested — precisely what
    # `return dict(cached[1])` does in these modules today. Pinned so the
    # migration doesn't mistake it for a bug and quietly deepen it.
    clock = _Clock()

    @ttl_cache(ttl=100, now=clock, copy=dict)
    def fetch(ticker: str) -> dict:
        return {"ticker": ticker, "periods": []}

    fetch("AAPL")["periods"].append("mutated")

    assert fetch("AAPL")["periods"] == ["mutated"]


# ── Clearing ──────────────────────────────────────────────────────────────────

def test_cache_clear_drops_this_fetchers_entries():
    clock = _Clock()
    fetch, calls = _counting_fetcher(clock)

    fetch("AAPL")
    fetch.cache_clear()
    assert not fetch.cache

    fetch("AAPL")
    assert calls == ["AAPL", "AAPL"]


def test_clear_all_resets_every_cache_in_the_process():
    clock = _Clock()
    quotes, quote_calls = _counting_fetcher(clock)
    news, news_calls = _counting_fetcher(clock)

    quotes("AAPL")
    news("AAPL")
    clear_all()
    quotes("AAPL")
    news("AAPL")

    assert quote_calls == ["AAPL", "AAPL"]
    assert news_calls == ["AAPL", "AAPL"]


# ── Threads ───────────────────────────────────────────────────────────────────

def test_misses_are_not_serialized_behind_the_store_lock():
    # The fan-outs in news, earnings and timing all fetch concurrently. If the
    # lock were held across the fetch, these two threads could never meet and
    # the barrier would break.
    barrier = threading.Barrier(2, timeout=5)
    results: dict[str, str] = {}

    @ttl_cache(ttl=100)
    def fetch(ticker: str) -> str:
        barrier.wait()
        return f"quote:{ticker}"

    def run(ticker: str) -> None:
        results[ticker] = fetch(ticker)

    threads = [threading.Thread(target=run, args=(t,)) for t in ("AAPL", "MSFT")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert results == {"AAPL": "quote:AAPL", "MSFT": "quote:MSFT"}


def test_concurrent_callers_leave_one_coherent_entry():
    ready = threading.Barrier(8, timeout=5)
    results: list[str] = []
    lock = threading.Lock()

    @ttl_cache(ttl=100)
    def fetch(ticker: str) -> str:
        return f"quote:{ticker}"

    def run() -> None:
        ready.wait()
        for _ in range(50):
            value = fetch("AAPL")
            with lock:
                results.append(value)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 400
    assert set(results) == {"quote:AAPL"}
    assert list(fetch.cache) == [("AAPL",)]


# ── Single flight ─────────────────────────────────────────────────────────────
#
# Startup warms the caches on a background thread while the browser's first page
# load asks for the same tickers. Both missed, so both fetched: every quote was
# pulled twice, in parallel, and the duplicates competed for the GIL doing pandas
# work. One fetch per key per window is the point of these.

def _blocking_fetcher(ttl=100.0, fail=False):
    """A fetcher that parks inside the call until the test releases it."""
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    @ttl_cache(ttl=ttl)
    def fetch(ticker: str) -> str:
        calls.append(ticker)
        entered.set()
        release.wait(timeout=5)
        if fail:
            raise RuntimeError("vendor down")
        return f"quote:{ticker}"

    return fetch, calls, entered, release


def _gather(fetch, ticker, count):
    """Run `fetch(ticker)` on `count` threads; return (threads, results, errors)."""
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def run() -> None:
        try:
            value = fetch(ticker)
        except BaseException as exc:  # noqa: BLE001 — the test asserts on it
            with lock:
                errors.append(exc)
        else:
            with lock:
                results.append(value)

    threads = [threading.Thread(target=run) for _ in range(count)]
    return threads, results, errors


def test_concurrent_misses_on_one_key_fetch_once():
    fetch, calls, entered, release = _blocking_fetcher()

    leader, leader_results, _ = _gather(fetch, "AAPL", 1)
    leader[0].start()
    assert entered.wait(timeout=5), "leader never reached the fetch"

    followers, follower_results, _ = _gather(fetch, "AAPL", 7)
    for thread in followers:
        thread.start()
    release.set()
    for thread in [*leader, *followers]:
        thread.join(timeout=10)

    assert calls == ["AAPL"], "the seven followers should have waited, not refetched"
    assert leader_results + follower_results == ["quote:AAPL"] * 8


def test_single_flight_is_per_key_so_fan_outs_still_run_in_parallel():
    # The whole reason the lock was never held across the fetch. Two tickers must
    # still be able to meet inside their fetches; a barrier proves they overlap.
    barrier = threading.Barrier(2, timeout=5)
    results: dict[str, str] = {}

    @ttl_cache(ttl=100)
    def fetch(ticker: str) -> str:
        barrier.wait()
        return f"quote:{ticker}"

    threads = [
        threading.Thread(target=lambda t=t: results.__setitem__(t, fetch(t)))
        for t in ("AAPL", "MSFT")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert results == {"AAPL": "quote:AAPL", "MSFT": "quote:MSFT"}


def test_a_failing_leader_does_not_strand_its_followers():
    # An exception is still never stored, so the followers cannot be handed one.
    # They fetch for themselves rather than inheriting the failure or hanging.
    fetch, calls, entered, release = _blocking_fetcher(fail=True)

    leader, _, leader_errors = _gather(fetch, "AAPL", 1)
    leader[0].start()
    assert entered.wait(timeout=5)

    followers, _, follower_errors = _gather(fetch, "AAPL", 3)
    for thread in followers:
        thread.start()
    release.set()
    for thread in [*leader, *followers]:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in [*leader, *followers])
    assert len(leader_errors) == 1
    assert len(follower_errors) == 3
    assert calls  # they retried rather than hanging on a leader that never stored


def test_a_fetcher_that_reenters_its_own_cache_does_not_deadlock():
    # Recursion through the same key on one thread must not wait on itself.
    depth = {"n": 0}

    @ttl_cache(ttl=100)
    def fetch(ticker: str) -> str:
        depth["n"] += 1
        if depth["n"] < 2:
            return fetch(ticker)
        return f"quote:{ticker}"

    assert fetch("AAPL") == "quote:AAPL"
    assert depth["n"] == 2


def test_force_refresh_does_not_wait_on_another_threads_fetch():
    # A forced call is asking for a value newer than now; inheriting an in-flight
    # fetch that started earlier would quietly defeat that.
    fetch, calls, entered, release = _blocking_fetcher()

    leader, _, _ = _gather(fetch, "AAPL", 1)
    leader[0].start()
    assert entered.wait(timeout=5)

    forced: list[str] = []
    forcer = threading.Thread(
        target=lambda: forced.append(fetch("AAPL", force_refresh=True))
    )
    forcer.start()
    release.set()
    for thread in [*leader, forcer]:
        thread.join(timeout=10)

    assert forced == ["quote:AAPL"]
    assert calls == ["AAPL", "AAPL"], "the forced call must fetch on its own"


# ── Identity ──────────────────────────────────────────────────────────────────

def test_the_wrapper_keeps_the_fetchers_name_and_docstring():
    @ttl_cache(ttl=100)
    def fetch(ticker: str) -> str:
        """Fetch one quote."""
        return ticker

    assert fetch.__name__ == "fetch"
    assert fetch.__doc__ == "Fetch one quote."
