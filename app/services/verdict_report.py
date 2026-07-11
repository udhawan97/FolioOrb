"""
Verdict report card — grade FolioOrb's past Hold / Add / Trim calls by how the
holding has actually done *since* the call (current price vs the price logged
when the verdict was made).

The calibration store (``verdict_calibration``) logs a ``VerdictSnapshot`` per
scan but cannot compute forward-window hit rates without historical price
backfill. "Since the call" sidesteps that entirely: it's computable from the
same cached quote the dashboard already loads, so the card is honest, useful on
a young install, and cannot hang on per-snapshot history lookups.

Deterministic and offline-testable: prices are injected in tests; production
fetches them through the shared cached quote layer with a bounded fan-out.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from app.services.log_safety import sanitize_for_log
from app.services.stock_service import (
    get_fast_quote,
    normalize_ticker,
    ticker_shape_is_safe,
)

logger = logging.getLogger(__name__)

_MAX_WORKERS = 8
_FETCH_TIMEOUT = 8.0           # hard wall-clock cap for the whole quote fan-out
_MIN_AGE_DAYS = 3             # a call younger than this hasn't had time to be judged
_HOLD_BAND_PCT = 10.0        # a "hold" ages well if the price stayed within ±this
_MAX_TICKERS = 40            # bound the quote fan-out so the endpoint can't stall
_LEDGER_LIMIT = 12          # most-recent graded calls surfaced to the UI

_SCORED_ACTIONS = ("add", "trim", "hold")


def _as_utc(value):
    """Coerce a stored ``generated_at`` to aware UTC.

    Snapshots written by ``log_verdict_snapshot`` are tz-aware UTC, but the
    column's DB-side default (``func.now()``) is naive — treat naive as UTC so
    subtracting from ``now`` never raises on mixed awareness.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hit(action: str, return_since_pct: float):
    """Did the call age well? ``None`` for actions we don't score."""
    if action == "add":
        return return_since_pct > 0.0
    if action == "trim":
        return return_since_pct < 0.0
    if action == "hold":
        return abs(return_since_pct) <= _HOLD_BAND_PCT
    return None


def _safe_price(ticker: str) -> float:
    try:
        return float(get_fast_quote(ticker).get("current_price") or 0.0)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("verdict-report quote failed for %s: %s",
                     sanitize_for_log(ticker), type(exc).__name__)
        return 0.0


def _fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """ticker -> current price via the cached quote layer, latency-bounded.

    Returns within ~``_FETCH_TIMEOUT`` regardless of stragglers: on timeout the
    pool is torn down with ``wait=False`` so a slow/hanging yfinance call can't
    hold the request open (a plain ``with`` block would block on exit until every
    worker finished). Whatever hasn't landed is simply absent and the caller
    marks those tickers pending_price; in-flight calls still finish in the
    background and warm the shared quote cache for the next refresh.
    """
    prices: dict[str, float] = {}
    if not tickers:
        return prices
    pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    try:
        futures = {pool.submit(_safe_price, t): t for t in tickers}
        try:
            for future in as_completed(futures, timeout=_FETCH_TIMEOUT):
                price = future.result()
                if price > 0:
                    prices[futures[future]] = price
        except TimeoutError:
            logger.debug("verdict-report price fan-out hit %.0fs cap: %d/%d priced",
                         _FETCH_TIMEOUT, len(prices), len(tickers))
    finally:
        # Don't block the response on stragglers — cancel what hasn't started;
        # anything already in-flight finishes and caches in the background.
        pool.shutdown(wait=False, cancel_futures=True)
    return prices


def build_verdict_report(snapshots, now=None, price_map=None) -> dict:
    """Score verdict snapshots against current price.

    ``snapshots``: objects with ``ticker``, ``action``, ``price_at_scan`` and
    ``generated_at``. ``price_map`` (ticker -> current price) is injected by
    tests; production leaves it ``None`` and prices are fetched here.
    """
    # Coerce a caller-supplied `now` too (not just generated_at) so a naive
    # `now` can never TypeError against the aware stored timestamps.
    now = _as_utc(now) or datetime.now(timezone.utc)

    # Distinct, shape-safe tickers, capped — this is the fan-out set.
    tickers: list[str] = []
    seen: set[str] = set()
    for snap in snapshots:
        symbol = normalize_ticker(snap.ticker or "")
        if symbol and symbol not in seen and ticker_shape_is_safe(symbol):
            seen.add(symbol)
            tickers.append(symbol)
        if len(tickers) >= _MAX_TICKERS:
            break
    prices = price_map if price_map is not None else _fetch_current_prices(tickers)

    graded: list[dict] = []
    pending_young = 0   # too recent to judge
    pending_price = 0   # couldn't be priced (delisted, capped out, quote failed)
    for snap in snapshots:
        symbol = normalize_ticker(snap.ticker or "")
        action = (snap.action or "").lower()
        scan_price = snap.price_at_scan
        generated = _as_utc(getattr(snap, "generated_at", None))
        if not scan_price or scan_price <= 0 or generated is None or action not in _SCORED_ACTIONS:
            continue
        age_days = (now - generated).days
        if age_days < _MIN_AGE_DAYS:
            pending_young += 1
            continue
        current = prices.get(symbol)
        if not current:
            pending_price += 1
            continue
        return_since = (current - scan_price) / scan_price * 100.0
        graded.append({
            "ticker": symbol,
            "action": action,
            "days_ago": age_days,
            "return_since_pct": round(return_since, 2),
            "hit": _hit(action, return_since),
        })

    graded.sort(key=lambda item: item["days_ago"])  # most recent first

    by_action: dict[str, dict] = {}
    for item in graded:
        bucket = by_action.setdefault(
            item["action"], {"action": item["action"], "hits": 0, "total": 0}
        )
        bucket["total"] += 1
        bucket["hits"] += 1 if item["hit"] else 0
    for bucket in by_action.values():
        bucket["hit_rate"] = (
            round(bucket["hits"] / bucket["total"] * 100, 1) if bucket["total"] else None
        )

    total = len(graded)
    hits = sum(1 for item in graded if item["hit"])
    return {
        "graded_count": total,
        "hit_count": hits,
        "hit_rate": round(hits / total * 100, 1) if total else None,
        "avg_return_since_pct": (
            round(sum(i["return_since_pct"] for i in graded) / total, 2) if total else None
        ),
        "by_action": [by_action[a] for a in _SCORED_ACTIONS if a in by_action],
        "pending_young": pending_young,
        "pending_price": pending_price,
        "ledger": graded[:_LEDGER_LIMIT],
        "min_age_days": _MIN_AGE_DAYS,
        "hold_band_pct": _HOLD_BAND_PCT,
    }
