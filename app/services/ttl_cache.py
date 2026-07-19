"""
app/services/ttl_cache.py

The one place that decides what "remember this for a while" means.

Every network-backed fetcher here had grown its own copy of the same six lines:
a module-level ``dict`` of ``key -> (expiry_monotonic, payload)``, a TTL
constant, a ``time.monotonic()`` read, an expiry comparison, a ``force_refresh``
escape hatch, and a store on the success path. Ten modules, twenty-one clock
reads, and no seam at which caching policy could be altered — changing the
clock, eviction, or what counts as worth remembering meant editing ten files
and hoping they agreed.

``ttl_cache`` is that seam. Expiry, the clock, storage, eviction, bypass, key
derivation, negative caching, aliasing, and locking live behind one decorator.
A fetcher now says only *what* to remember and *for how long*::

    @ttl_cache(ttl=_quote_ttl, key=normalize_ticker)
    def get_stock_data(ticker: str) -> dict:
        ...

    @ttl_cache(
        ttl=300,
        key=lambda ticker, period: (ticker.upper(), period),
        cache_when=bool,
    )
    def get_historical_prices(ticker: str, period: str = "1mo") -> list[dict]:
        ...

What the wrapper adds to a fetcher's interface:

  * a ``force_refresh`` keyword that bypasses the stored entry. The fetcher
    doesn't have to know it exists — the wrapper consumes it. A fetcher that
    *declares* it keyword-only (``*, force_refresh: bool = False``) gets it
    forwarded as well, which is how a filings lookup passes the bypass down to
    the CIK lookup underneath it. Either way it never takes part in the key.
  * ``.cache_clear()`` to drop this fetcher's entries, and ``.cache``, the live
    store, for tests that seed or inspect one. Entries keep the
    ``(expiry, payload)`` shape the hand-rolled caches used, so a module can
    still publish its own dict: ``_QUOTE_CACHE = get_stock_data.cache``.

What gets remembered:
  Only a normal return. A raised exception is never stored, so a failure is
  retried on the next call instead of being pinned for the whole TTL. Every
  value a fetcher *returns* is stored by default, including ``None``, ``[]``
  and ``{}`` — callers depend on that negative caching: the earnings radar
  stores a ``None`` so a ticker with no known date isn't re-scraped for six
  hours, and news stores an empty list. Fetchers that must not remember an
  empty answer say so with ``cache_when=bool``, the way historical prices does.

Clock and threads:
  The clock is read once per call and used both for the expiry comparison and
  for the new entry's expiry, so a TTL window starts when the call starts —
  matching the caches this replaces. The lock guards the store only, never the
  fetch: holding it across a twenty-second network call would serialize the
  concurrent fan-outs in news, earnings and timing.

  Concurrent misses on *one* key are deduplicated instead: the first caller
  fetches and the rest wait for its answer. Startup warms these caches on a
  background thread at the same moment the browser's first page load asks for
  the same tickers, and before this every quote was pulled twice — in parallel,
  with the duplicates competing for the GIL doing pandas work. Deduplication is
  safe here because the fetchers are pure reads of an external API: it changes
  how much load they generate, never what they return.

  Three cases deliberately do not wait. Misses on *different* keys still run in
  parallel, which is what the fan-outs need. A ``force_refresh`` call is asking
  for a value newer than now, so inheriting a fetch that started earlier would
  quietly defeat it. And a fetcher that re-enters its own key on the same thread
  proceeds rather than waiting on itself, which would deadlock.

  A fetch that raises stores nothing, so its waiters cannot be handed a value.
  They wake and retry — one at a time, since the retry leads a new flight —
  rather than inheriting the exception or stampeding the failing vendor.
"""
from __future__ import annotations

import functools
import inspect
import threading
import time
import weakref
from collections.abc import Hashable
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# The bypass keyword, spelled once. Callers pass it; keys never see it.
_FORCE_REFRESH = "force_refresh"

# Every live cache, so a test can reset the whole process in one call. Weak, so
# a cache built inside a test doesn't outlive it.
_LIVE_CACHES: weakref.WeakSet = weakref.WeakSet()


def clear_all() -> None:
    """Empty every TTL cache in the process — a test seam, unused by the app."""
    for cached in list(_LIVE_CACHES):
        cached.cache_clear()


# A waiter's ceiling, not a fetcher's. Every fetch here already carries its own
# network timeout; this only stops a waiter hanging forever if a leader thread
# dies without running its `finally`. On expiry the waiter re-reads the store and
# leads a fresh fetch, so the cost of being wrong is one duplicate call.
_FLIGHT_TIMEOUT = 30.0


class _Flight:
    """One in-progress fetch of one key, and the gate its waiters block on.

    ``owner`` is the thread that started it, so a fetcher that re-enters its own
    cache key can tell "someone else is fetching this" from "I am", and proceed
    instead of waiting on itself.
    """

    __slots__ = ("event", "owner")

    def __init__(self, owner: int) -> None:
        self.event = threading.Event()
        self.owner = owner


def _default_key(*args: Any, **kwargs: Any) -> Hashable:
    """Key a call by its own arguments: positional values, then sorted pairs.

    Enough for the single-argument fetchers that dominate here. Anything with
    an unhashable argument, or one that shouldn't affect identity, supplies its
    own ``key``.
    """
    if not kwargs:
        return args
    return args + tuple(sorted(kwargs.items()))


def _key_arguments(
    signature: inspect.Signature, bound: inspect.BoundArguments
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Re-shape a bound call for the key function: the same call, minus the bypass.

    Defaults are already applied by the caller, so ``get_historical_prices("V")``
    and ``get_historical_prices("V", "1mo")`` reach the key function — and so
    land in the store — identically.
    """
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name == _FORCE_REFRESH or name not in bound.arguments:
            continue
        value = bound.arguments[name]
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            args.extend(value)
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            kwargs.update(value)
        elif parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            kwargs[name] = value
        else:
            args.append(value)
    return tuple(args), kwargs


def _drop_expired(store: dict[Hashable, tuple[float, Any]], clock: float) -> None:
    """Evict entries that can never be read again. The caller holds the lock.

    Without this a long-running desktop process accumulates one dead entry per
    key per TTL window — the leak each date-keyed cache used to prune by hand.
    """
    expired = [key for key, entry in store.items() if entry[0] <= clock]
    for key in expired:
        del store[key]


def ttl_cache(
    ttl: float | Callable[[], float],
    *,
    key: Callable[..., Hashable] | None = None,
    cache_when: Callable[[Any], bool] | None = None,
    copy: Callable[[T], T] | None = None,
    now: Callable[[], float] = time.monotonic,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Remember a fetcher's return value for ``ttl`` seconds, keyed by its call.

    ``ttl``         seconds, or a zero-argument callable read at store time so a
                    window can depend on the world — market-hours TTLs pass
                    ``_quote_ttl`` and get 60s while open, 900s while closed.
    ``key``         derives the entry key. Called exactly as the fetcher was,
                    with defaults applied and ``force_refresh`` removed, so
                    ``lambda ticker, period: (ticker.upper(), period)`` mirrors
                    the fetcher's own parameter names. Defaults to the argument
                    values themselves.
    ``cache_when``  decides whether a returned value is worth storing. Defaults
                    to storing everything, empty answers included; pass ``bool``
                    to keep an empty result from being pinned for the window.
    ``copy``        hands each caller its own copy (``list``, ``dict``) so a
                    caller that mutates what it got can't corrupt the entry.
                    As shallow as the callable given: ``dict`` protects the top
                    level and leaves nested values shared, which is exactly what
                    ``return dict(cached[1])`` does in these modules today —
                    pass ``copy.deepcopy`` to go deeper. Applied only to values
                    that were stored: one ``cache_when`` rejected is nobody
                    else's, so it comes back untouched and never has to be
                    copyable. Defaults to sharing the stored object, safe for
                    the read-only payloads most fetchers return.
    ``now``         the clock, injected so tests move time instead of sleeping.

    Raises ``TypeError`` at decoration time if the fetcher declares
    ``force_refresh`` positionally — it must be keyword-only, or removing it
    from the key would shift every argument after it.
    """

    def decorate(func: Callable[..., T]) -> Callable[..., T]:
        signature = inspect.signature(func)
        forwards_bypass = _FORCE_REFRESH in signature.parameters
        if forwards_bypass and (
            signature.parameters[_FORCE_REFRESH].kind
            is not inspect.Parameter.KEYWORD_ONLY
        ):
            raise TypeError(
                f"{func.__qualname__}: {_FORCE_REFRESH} must be keyword-only "
                f"(declare it after a bare '*')"
            )

        store: dict[Hashable, tuple[float, T]] = {}
        in_flight: dict[Hashable, _Flight] = {}
        lock = threading.Lock()
        derive_key = _default_key if key is None else key

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # A fetcher that declares the bypass keeps it and passes it down;
            # one that doesn't never sees it.
            forced = False if forwards_bypass else bool(kwargs.pop(_FORCE_REFRESH, False))
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            if forwards_bypass:
                forced = bool(bound.arguments.get(_FORCE_REFRESH, False))

            key_args, key_kwargs = _key_arguments(signature, bound)
            entry_key = derive_key(*key_args, **key_kwargs)
            clock = now()

            def fetch_and_store() -> T:
                # Deliberately outside the lock: the fetch is the slow part, and
                # every fan-out in this app depends on misses running in parallel.
                result = func(*args, **kwargs)

                if cache_when is not None and not cache_when(result):
                    # Nothing else holds this value, so there is nothing to
                    # protect it from — and a rejected value needn't even be
                    # copyable.
                    return result

                expiry = clock + (ttl() if callable(ttl) else ttl)
                with lock:
                    store[entry_key] = (expiry, result)
                    _drop_expired(store, clock)
                return copy(result) if copy else result

            # A forced call wants a value newer than now, so it neither waits on
            # an in-flight fetch nor leads one for anybody else.
            if forced:
                return fetch_and_store()

            me = threading.get_ident()
            while True:
                # The store read and the flight registration share one hold of
                # the lock. Split apart, a caller could miss the store, have the
                # leader store-and-finish in the gap, then find no flight to wait
                # on — and refetch a value that was already sitting there.
                with lock:
                    entry = store.get(entry_key)
                    if entry is not None and entry[0] > clock:
                        return copy(entry[1]) if copy else entry[1]
                    running = in_flight.get(entry_key)
                    if running is None:
                        leading = _Flight(me)
                        in_flight[entry_key] = leading
                        break
                    if running.owner == me:
                        leading = None  # re-entrant: waiting would deadlock
                        break
                    waiting = running
                # Outside the lock: let the leader finish, then look again. A
                # leader that raised stored nothing, so the next pass makes this
                # caller the new leader rather than a second simultaneous fetch.
                waiting.event.wait(timeout=_FLIGHT_TIMEOUT)
                clock = now()

            if leading is None:
                return fetch_and_store()  # re-entrant call, shares nothing
            try:
                return fetch_and_store()
            finally:
                # Store first, then publish: a waiter woken here re-reads the
                # store and finds the value the leader just wrote.
                with lock:
                    in_flight.pop(entry_key, None)
                leading.event.set()

        def cache_clear() -> None:
            """Drop every entry this fetcher has remembered."""
            with lock:
                store.clear()

        wrapper.cache = store
        wrapper.cache_clear = cache_clear
        _LIVE_CACHES.add(wrapper)
        return wrapper

    return decorate
