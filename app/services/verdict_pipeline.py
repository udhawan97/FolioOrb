"""One verdict scan of a Portfolio — deterministic signals, then the narrated read.

Seven modules already answer one question each about a holding: analyst rating,
timing, peer standing, events, exposure, market regime, investment signal.  Their
COMPOSITION had no home.  The wiring lived inline in the AI router and was written
out three times, so the only way to produce a verdict was to call an HTTP handler.
This module owns the composition instead, behind two entry points:

    scan_portfolio(db, portfolio_id) -> ScanResult   # the whole book
    scan_ticker(db, ticker, portfolio_id) -> dict    # one holding

Depth is what sits behind those two names: per-ticker stage wiring, calibration
footnotes, verdict-snapshot history, the quip cache (key schema, freshness and
price-drift rules), the batched Claude call with its persistence and fallbacks,
brand and disclaimer copy, and the portfolio-health synthesis.  A caller hands
over a session and a portfolio id; no stage leaks back out.

The verdict cache schema lives here too — the key format and the action, mood and
hold-class codes it is built from — so one module decides what a cached verdict
means and when it goes stale.  The action codes are imported from portfolio_state,
which already owned them for the book-level key; a second copy here would let the
two key families drift apart.

``scan_portfolio(narrate=False)`` stops after the deterministic stage.  That is the
seam the action plan needs: it wants the verdicts as raw material and must not pay
for quips, cache traffic, scan history or a Claude call to get them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import VerdictSnapshot
from app.services import holdings_repository, narrative_cache
from app.services.ai_service import MODEL, fallback_quip, generate_verdict_ai_bundles
from app.services.analyst_recommendation import get_analyst_recommendation
from app.services.event_calendar import build_event_context
from app.services.investment_signal import build_investment_signal, signal_to_dict
from app.services.market_regime import get_market_regime
from app.services.peer_relative import compute_peer_relative
from app.services.portfolio_exposure import (
    build_portfolio_exposure,
    exposure_context_for_ticker,
)
from app.services.portfolio_state import _ACTION_CACHE_CODE, portfolio_state_signature
from app.services.stock_service import (
    DEFAULT_HOLDINGS,
    get_all_quotes,
    get_stock_data,
    usable_price,
)
from app.services.timing_signal import (
    build_timing_signal,
    get_batched_history_closes,
    get_cached_history_closes,
    timing_bucket,
)
from app.services.verdict_ai_enhancement import apply_ai_enhancement, compact_signal_mix
from app.services.verdict_calibration import (
    calibration_footnote,
    calibration_summary,
    compute_calibration_buckets,
    log_verdict_snapshot,
)
from app.services.verdict_scan_cache import attach_since_last_scan

logger = logging.getLogger(__name__)

# ── Reader-facing copy ────────────────────────────────────────────────────────

VERDICT_BRAND_KICKER = "FolioOrb × Claude"
VERDICT_BRAND_KICKER_LOCAL = "FolioOrb Intelligence"
VERDICT_FEELS_PREFIX = "FolioOrb feels"
VERDICT_DISCLAIMER = (
    "FolioOrb Intelligence — a signal read, not "
    "financial advice. Verify before you trade."
)
AI_VERDICT_DISCLAIMER = VERDICT_DISCLAIMER

# ── Verdict cache schema ──────────────────────────────────────────────────────
# One owner for what a cached quip is keyed on.  Adding a dimension here is the
# whole change: every read and write below goes through _verdict_summary_type.

_MOOD_CACHE_CODE = {
    "hot": "hot", "warm": "warm", "neutral": "neut", "cooling": "cool", "cold": "cold"
}
_HOLD_CLASS_CACHE_CODE = {"auto": "auto", "anchor": "anch", "trade": "trd", "core": "core"}

# Verdict quips age out after a day.  Deliberately this module's own number: the
# router caches other narratives on the same rhythm today, but nothing says a
# quip and a portfolio briefing must expire together.
_VERDICT_CACHE_TTL = timedelta(hours=24)

_NEEDS_DATA_SIGNAL = {
    "action": "needs-data",
    "label": "Needs Data",
    "confidence": 0,
    "market_mood": "neutral",
    "reasons": [],
    "risks": ["Insufficient data to form a view"],
    "data_quality": "low",
    "source_fields": [],
    "flip_triggers": None,
    "signal_mix": [],
    "freshness": None,
    "since_last_scan": None,
    "hold_class": "auto",
    "instrument_role": "tactical",
    "timing": None,
}


@dataclass
class ScanResult:  # pylint: disable=too-many-instance-attributes
    """One traceable verdict scan for callers and tests.

    ``signals`` is the payload readers want; the rest is the context the scan was
    computed against, kept alongside so a caller that needs to reason about the
    book (the action plan does) never re-queries or re-derives it.

    ``health``, ``calibration`` and ``claude_live`` stay ``None`` on an
    un-narrated scan — nothing produced them, and an empty dict would read as
    "computed, found nothing".
    """

    portfolio_id: int
    tickers: list[str]
    signals: dict[str, dict]
    allocation_pct: dict[str, float]
    positions: dict[str, dict]
    exposure: dict
    regime: dict
    state: dict = field(default_factory=dict)
    health: dict | None = None
    calibration: dict | None = None
    claude_live: bool | None = None

    @property
    def count(self) -> int:
        """How many tickers carry a verdict in this scan."""
        return len(self.signals)


# ── Position reads ────────────────────────────────────────────────────────────
# What "an active holding" means is holdings_repository's to decide, so the three
# reads below ask it for ``meta_map`` rather than each re-writing the filter.


def _allocation_pcts(positions: dict, quotes: dict) -> dict[str, float]:
    """Compute allocation_pct for every non-watchlist holding.

    Prices go through `usable_price` so this agrees with the valuation seam on
    what counts as priced — notably rejecting NaN, which the older
    ``current_price or 0`` read let through and which then turned every weight
    in the book into NaN.  An unpriced holding contributes nothing and lands at
    0.0 rather than disappearing, so the exposure rows keep their ticker.
    """
    values = {
        ticker: meta["shares"] * (usable_price(quotes.get(ticker, {})) or 0.0)
        for ticker, meta in positions.items()
        if not meta["is_watchlist"]
    }
    total_value = sum(values.values())
    if total_value <= 0:
        return {}
    return {
        ticker: round(value / total_value * 100, 1)
        for ticker, value in values.items()
    }


def _exposure_rows(positions: dict, alloc_map: dict) -> list[dict]:
    """Shape positions the way the look-through exposure builder reads them."""
    return [
        {
            "ticker": ticker,
            "allocation_pct": alloc_map.get(ticker, 0),
            "is_watchlist": meta.get("is_watchlist", False),
        }
        for ticker, meta in positions.items()
    ]


def _recent_add_count(db: Session, ticker: str, days: int = 30, portfolio_id: int = 1) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        db.query(VerdictSnapshot)
        .filter(
            VerdictSnapshot.portfolio_id == portfolio_id,
            VerdictSnapshot.ticker == ticker.upper(),
            VerdictSnapshot.action == "add",
            VerdictSnapshot.generated_at >= cutoff,
        )
        .count()
    )


def _user_context(
    meta: dict, quote_data: dict | None, db: Session, ticker: str, portfolio_id: int = 1
) -> dict:
    quote = quote_data or {}
    return {
        "shares": meta.get("shares"),
        "avg_cost": meta.get("avg_cost"),
        "current_price": quote.get("current_price"),
        "recent_add_count": _recent_add_count(db, ticker, portfolio_id=portfolio_id),
    }


def _timing_for_quote(quote_data: dict | None, closes: list[float]) -> dict:
    quote = quote_data or {}
    return build_timing_signal(
        closes,
        current_price=quote.get("current_price"),
        high_52w=quote.get("fifty_two_week_high"),
        low_52w=quote.get("fifty_two_week_low"),
        fallback_ma50=quote.get("fifty_day_average"),
        fallback_ma200=quote.get("two_hundred_day_average"),
    )


# ── Deterministic stage ───────────────────────────────────────────────────────


def _verdict_for(
    db: Session,
    ticker: str,
    *,
    position: dict,
    quote: dict,
    closes: list[float],
    allocation_pct: float | None,
    regime: dict,
    exposure_context: dict | None = None,
    seed_peer_from_rec: bool = False,
    portfolio_id: int = 1,
) -> dict:
    """Wire the per-holding stages into one deterministic verdict dict.

    A quote carrying ``error`` is withheld from the scorers rather than passed
    through as partial data — but an absent quote (``{}``) is not an error, and
    the scorers handle it, so it is passed as-is.

    ``seed_peer_from_rec`` hands the peer comparison the ETF price-signal
    percentile the analyst stage already fetched.  The book scan does this; the
    single-ticker read does not and lets the peer module derive its own from
    closes.  The two paths have always differed here, and unifying them would
    change what a single ETF verdict says.
    """
    usable_quote = quote if not quote.get("error") else None
    timing = _timing_for_quote(usable_quote, closes)
    rec = get_analyst_recommendation(ticker, closes=closes)
    price_signal = (rec.price_signal or {}) if seed_peer_from_rec else {}
    peer = compute_peer_relative(
        ticker,
        own_percentile=price_signal.get("percentile"),
        zone=price_signal.get("priceZoneLabel"),
        stock_data=usable_quote,
        closes=closes,
    )
    event_ctx = build_event_context(ticker, security_type=rec.security_type)
    sig = build_investment_signal(
        rec,
        allocation_pct=allocation_pct,
        is_watchlist=position.get("is_watchlist", False),
        stock_data=usable_quote,
        hold_class=position.get("hold_class", "auto"),
        timing=timing,
        regime=regime,
        peer_relative=peer,
        exposure_context=exposure_context,
        event_context=event_ctx,
        user_context=_user_context(position, quote, db, ticker, portfolio_id),
    )
    return signal_to_dict(sig)


def _collect(db: Session, portfolio_id: int) -> tuple[ScanResult, dict[str, dict]]:
    """Score every active holding, sharing one quote/history/exposure fetch.

    Returns the scan alongside the quote map, which the narration stage needs for
    price-drift checks and snapshot prices but which no caller should see.

    A ticker whose scoring raises carries ``_signal_error`` so the narration stage
    can tell a build failure from a legitimate needs-data verdict.
    """
    positions = holdings_repository.meta_map(db, portfolio_id)
    # Ticker order follows the holdings query; an empty book still gets a read.
    tickers = list(positions) or list(DEFAULT_HOLDINGS)
    quotes = {q["ticker"]: q for q in get_all_quotes(tickers)}
    history_map = get_batched_history_closes(tickers)
    alloc_map = _allocation_pcts(positions, quotes)
    exposure = build_portfolio_exposure(_exposure_rows(positions, alloc_map), quotes=quotes)
    regime = get_market_regime()

    signals: dict[str, dict] = {}
    for ticker in tickers:
        try:
            signals[ticker] = _verdict_for(
                db,
                ticker,
                position=positions.get(ticker, {}),
                quote=quotes.get(ticker) or {},
                closes=history_map.get(ticker, []),
                allocation_pct=alloc_map.get(ticker),
                regime=regime,
                exposure_context=exposure_context_for_ticker(exposure, ticker),
                seed_peer_from_rec=True,
                portfolio_id=portfolio_id,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "Signal build failed for %s; exception_type=%s",
                ticker, type(exc).__name__,
            )
            signals[ticker] = {**_NEEDS_DATA_SIGNAL, "ticker": ticker, "_signal_error": True}

    result = ScanResult(
        portfolio_id=portfolio_id,
        tickers=tickers,
        signals=signals,
        allocation_pct=alloc_map,
        positions=positions,
        exposure=exposure,
        regime=regime,
    )
    return result, quotes


# ── Narration stage ───────────────────────────────────────────────────────────


def _verdict_summary_type(
    action: str,
    market_mood: str,
    hold_class: str = "auto",
    timing_key: str = "none",
) -> str:
    """Compact cache namespace for ticker verdict quips."""
    action_code = _ACTION_CACHE_CODE.get(action, "n")
    mood_code = _MOOD_CACHE_CODE.get(market_mood, "neut")
    hold_code = _HOLD_CLASS_CACHE_CODE.get(hold_class, "auto")
    return f"v:{action_code}:{mood_code}:{hold_code}:{timing_key}"


def _cache_key_for(sig_dict: dict) -> str:
    """Cache namespace for the verdict a signal dict currently states."""
    return _verdict_summary_type(
        sig_dict.get("action", "needs-data"),
        sig_dict.get("market_mood", "neutral"),
        sig_dict.get("hold_class", "auto"),
        timing_bucket(sig_dict.get("timing")),
    )


def _brand_payload(*, ai_mode: bool = False) -> dict:
    return {
        "kicker": VERDICT_BRAND_KICKER if ai_mode else VERDICT_BRAND_KICKER_LOCAL,
        "feels_prefix": VERDICT_FEELS_PREFIX,
        "disclaimer": AI_VERDICT_DISCLAIMER if ai_mode else VERDICT_DISCLAIMER,
    }


def _hydrate_cached_verdict(sig_dict: dict, decoded: dict) -> bool:
    """Apply cached quip + AI bundle to sig_dict. Returns True when AI layer present."""
    quip = decoded.get("quip") or ""
    if quip:
        sig_dict["quip"] = quip
    ai_raw = decoded.get("ai")
    if ai_raw and sig_dict.get("action") != "needs-data":
        apply_ai_enhancement(sig_dict, ai_raw)
        return True
    return False


def _portfolio_fallback_quip(dominant_action: str, concentration_band: str) -> str:
    if concentration_band == "high":
        return (
            "Claude sees the book leaning concentrated; "
            "FolioOrb is politely raising one eyebrow."
        )
    if dominant_action == "add":
        return (
            "FolioOrb sees more green lights than red flags, "
            "with Claude keeping the caveats close."
        )
    if dominant_action == "trim":
        return (
            "Claude thinks the portfolio has had a run; "
            "FolioOrb is checking the exits calmly."
        )
    if dominant_action == "needs-data":
        return (
            "FolioOrb wants more receipts before turning this portfolio read into a headline."
        )
    return (
        "Claude calls the portfolio balanced enough to be interesting, "
        "not boring enough to ignore."
    )


def _failed_verdict(ticker: str) -> dict:
    """The verdict served when narrating a ticker raised."""
    return {
        **_NEEDS_DATA_SIGNAL,
        "ticker": ticker,
        "quip": fallback_quip("needs-data"),
        "disclaimer": VERDICT_DISCLAIMER,
        "brand": _brand_payload(),
        "generated_at": "",
    }


def _unscored_verdict(sig_dict: dict) -> dict:
    """Finish a ticker whose deterministic scoring already failed.

    It skips calibration, scan history and the quip cache exactly as it always
    has: an exception upstream meant the whole AI path was never reached.
    """
    sig_dict["quip"] = fallback_quip("needs-data")
    sig_dict["ai_enhanced"] = False
    sig_dict["disclaimer"] = VERDICT_DISCLAIMER
    sig_dict["brand"] = _brand_payload()
    sig_dict.setdefault("generated_at", "")
    return sig_dict


def _narrate_ticker(
    db: Session,
    sig_dict: dict,
    *,
    ticker: str,
    quote: dict,
    hold_class: str,
    cache: narrative_cache.NarrativeCache,
    buckets: dict,
    portfolio_id: int,
) -> tuple[bool, bool]:
    """Attach calibration, scan history, brand and any cached quip to one verdict.

    Returns ``(needs_quip, scan_history_changed)``.
    """
    action = sig_dict.get("action", "needs-data")
    confidence = sig_dict.get("confidence", 0)

    footnote = calibration_footnote(
        db, action=action, confidence=confidence,
        buckets=buckets, portfolio_id=portfolio_id,
    )
    if footnote:
        sig_dict["calibration_footnote"] = footnote
    log_verdict_snapshot(
        db,
        ticker=ticker,
        action=action,
        confidence=confidence,
        local_score=confidence,
        ai_score=None,
        price_at_scan=quote.get("current_price"),
        hold_class=hold_class,
        portfolio_id=portfolio_id,
    )
    scan_changed = attach_since_last_scan(db, ticker, sig_dict)
    sig_dict["disclaimer"] = VERDICT_DISCLAIMER
    sig_dict["brand"] = _brand_payload()

    cached = cache.get_verdict(
        ticker,
        _cache_key_for(sig_dict),
        current_price=quote.get("current_price"),
    )
    if cached is not None:
        sig_dict["ai_enhanced"] = _hydrate_cached_verdict(sig_dict, cached)
        return False, scan_changed

    sig_dict["quip"] = None  # filled by the batch call
    return True, scan_changed


def _store_quip(
    cache: narrative_cache.NarrativeCache,
    scope: str,
    summary_type: str,
    quip: str,
    ai_raw: dict | None,
    *,
    model_used: str,
    price: float | None = None,
) -> None:
    """Persist one generated quip; a cache write must never fail a scan."""
    try:
        cache.store_verdict(
            scope,
            summary_type,
            quip,
            ai_raw,
            model_used,
            price_when_generated=price,
            commit=False,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug(
            "Failed to cache quip for %s; exception_type=%s",
            scope, type(exc).__name__,
        )


def _generate_quips(
    result: ScanResult,
    quotes: dict,
    cache: narrative_cache.NarrativeCache,
    *,
    missing: list[str],
    book_scope: str | None,
) -> tuple[bool, str | None]:
    """Run one batched Claude call for every verdict still missing a quip.

    ``book_scope`` is the portfolio-level cache scope when the book quip is also
    stale, otherwise ``None``.  Returns ``(claude_live, book_quip)``.
    """
    signals = result.signals
    quip_inputs = [
        {
            "ticker": t,
            "action": signals[t].get("action", "needs-data"),
            "confidence": signals[t].get("confidence", 0),
            "market_mood": signals[t].get("market_mood", "neutral"),
            "reason": (signals[t].get("reasons") or [""])[0],
            "mix": compact_signal_mix(signals[t].get("signal_mix")),
        }
        for t in missing
    ]
    if book_scope:
        quip_inputs.append(
            {
                "ticker": book_scope,
                "action": result.state["dominant_action"],
                "confidence": 60,
                "market_mood": "neutral",
                "reason": result.state["reason"],
                "mix": "",
            }
        )
    new_bundles = generate_verdict_ai_bundles(quip_inputs)
    claude_live = bool(new_bundles)

    for ticker in missing:
        sig_dict = signals[ticker]
        bundle = new_bundles.get(ticker) or {}
        quip = bundle.get("quip") or fallback_quip(sig_dict.get("action", "needs-data"))
        sig_dict["quip"] = quip
        ai_raw = bundle.get("ai")
        if ai_raw and claude_live:
            apply_ai_enhancement(sig_dict, ai_raw)
            sig_dict["ai_enhanced"] = True
        else:
            sig_dict["ai_enhanced"] = False
        _store_quip(
            cache,
            ticker,
            _cache_key_for(sig_dict),
            quip,
            ai_raw if claude_live else None,
            model_used=MODEL if bundle.get("quip") and claude_live else "fallback",
            price=(quotes.get(ticker) or {}).get("current_price"),
        )

    book_quip: str | None = None
    if book_scope:
        book_bundle = new_bundles.get(book_scope) or {}
        book_quip = book_bundle.get("quip") or _portfolio_fallback_quip(
            result.state["dominant_action"],
            result.state["concentration_band"],
        )
        _store_quip(
            cache,
            book_scope,
            result.state["summary_type"],
            book_quip,
            None,
            model_used=MODEL if book_bundle.get("quip") and claude_live else "fallback",
        )
    return claude_live, book_quip


def _apply_brand(result: ScanResult, *, force_local: bool) -> None:
    """Stamp every verdict with the brand that matches how it was produced."""
    if force_local:
        local_brand = _brand_payload(ai_mode=False)
        for sig in result.signals.values():
            sig["brand"] = local_brand
            sig["disclaimer"] = VERDICT_DISCLAIMER
        return
    if result.claude_live:
        ai_brand = _brand_payload(ai_mode=True)
        for sig in result.signals.values():
            sig["brand"] = ai_brand
            sig["disclaimer"] = AI_VERDICT_DISCLAIMER
        return
    # No live call this scan: only verdicts carrying a cached AI layer earned it.
    if any(sig.get("ai_enhanced") for sig in result.signals.values()):
        ai_brand = _brand_payload(ai_mode=True)
        for sig in result.signals.values():
            if sig.get("ai_enhanced"):
                sig["brand"] = ai_brand
                sig["disclaimer"] = AI_VERDICT_DISCLAIMER


def _narrate(db: Session, result: ScanResult, quotes: dict, *, force_local: bool) -> None:
    """Turn deterministic verdicts into the scan a reader sees, in place."""
    cache = narrative_cache.NarrativeCache(db, ttl=_VERDICT_CACHE_TTL)
    # Calibration buckets are portfolio-wide (not ticker-specific), so compute them
    # once here instead of re-querying/re-aggregating on every loop iteration below.
    buckets = compute_calibration_buckets(db, window="1m", portfolio_id=result.portfolio_id)

    narrated: dict[str, dict] = {}
    missing: list[str] = []
    scan_changed = False
    for ticker in result.tickers:
        try:
            sig_dict = dict(result.signals.get(ticker) or {})
            if sig_dict.pop("_signal_error", False):
                narrated[ticker] = _unscored_verdict(sig_dict)
                continue
            needs_quip, changed = _narrate_ticker(
                db,
                sig_dict,
                ticker=ticker,
                quote=quotes.get(ticker) or {},
                hold_class=result.positions.get(ticker, {}).get("hold_class", "auto"),
                cache=cache,
                buckets=buckets,
                portfolio_id=result.portfolio_id,
            )
            scan_changed = changed or scan_changed
            if needs_quip:
                missing.append(ticker)
            narrated[ticker] = sig_dict
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "Investment signal failed for %s; exception_type=%s",
                ticker, type(exc).__name__,
            )
            narrated[ticker] = _failed_verdict(ticker)

    result.signals = narrated
    result.state = portfolio_state_signature(narrated, result.allocation_pct)

    book_scope = narrative_cache.portfolio_scope(result.portfolio_id)
    book_cached = cache.get_verdict(book_scope, result.state["summary_type"])
    book_stale = book_cached is None
    book_quip: str | None = None if book_stale else (book_cached.get("quip") or None)

    if force_local:
        for ticker in missing:
            sig_dict = narrated[ticker]
            sig_dict["quip"] = fallback_quip(sig_dict.get("action", "needs-data"))
            sig_dict["ai_enhanced"] = False
        if book_stale:
            book_quip = _portfolio_fallback_quip(
                result.state["dominant_action"],
                result.state["concentration_band"],
            )
        missing, book_stale = [], False

    if missing or book_stale:
        result.claude_live, generated = _generate_quips(
            result, quotes, cache,
            missing=missing,
            book_scope=book_scope if book_stale else None,
        )
        book_quip = generated if book_stale else book_quip
        db.commit()
    elif scan_changed:
        db.commit()

    _apply_brand(result, force_local=force_local)

    ai_mode = bool(result.claude_live) and not force_local
    result.health = {
        "quip": book_quip or _portfolio_fallback_quip(
            result.state["dominant_action"],
            result.state["concentration_band"],
        ),
        "dominant_action": result.state["dominant_action"],
        "concentration_band": result.state["concentration_band"],
        "signature": result.state["summary_type"],
        "brand": _brand_payload(ai_mode=ai_mode),
        "disclaimer": (
            VERDICT_DISCLAIMER
            if force_local
            else (AI_VERDICT_DISCLAIMER if result.claude_live else VERDICT_DISCLAIMER)
        ),
    }
    result.calibration = calibration_summary(db, result.portfolio_id)


# ── Interface ─────────────────────────────────────────────────────────────────


def scan_portfolio(
    db: Session,
    portfolio_id: int = 1,
    *,
    force_local: bool = False,
    narrate: bool = True,
) -> ScanResult:
    """Score every active holding and return one scan of the book.

    ``narrate=True`` (the default) also records the scan and dresses it for a
    reader: calibration footnotes, verdict-snapshot history, cached or freshly
    generated quips with their AI layer, brand and disclaimer, and the
    portfolio-health synthesis.  ``force_local=True`` keeps that path but skips
    Claude, so every quip is the deterministic fallback.

    ``narrate=False`` stops after the deterministic verdicts — no cache traffic,
    no scan history, no Claude, no brand.  Callers that read the verdicts as raw
    material rather than serving them want this.
    """
    result, quotes = _collect(db, portfolio_id)
    if narrate:
        _narrate(db, result, quotes, force_local=force_local)
    else:
        result.state = portfolio_state_signature(result.signals, result.allocation_pct)
    return result


def scan_ticker(db: Session, ticker: str, portfolio_id: int = 1) -> dict:
    """Score one holding on its own and return its verdict.

    This is the cheap read: it fetches only what a single ticker needs and never
    calls Claude, so the quip is always the deterministic fallback.  Allocation
    is still portfolio-relative, so a quote failure leaves it unknown rather than
    guessed.  Scan history is recorded, matching the book scan.
    """
    ticker = ticker.upper()
    positions = holdings_repository.meta_map(db, portfolio_id)
    position = positions.get(ticker, {})

    allocation_pct: float | None = None
    quote = get_stock_data(ticker)
    if not quote.get("error"):
        quotes = {q["ticker"]: q for q in get_all_quotes(list(positions))}
        allocation_pct = _allocation_pcts(positions, quotes).get(ticker)

    sig_dict = _verdict_for(
        db,
        ticker,
        position=position,
        quote=quote,
        closes=get_cached_history_closes(ticker),
        allocation_pct=allocation_pct,
        regime=get_market_regime(),
        portfolio_id=portfolio_id,
    )
    scan_changed = attach_since_last_scan(db, ticker, sig_dict)

    sig_dict["quip"] = fallback_quip(sig_dict.get("action", "needs-data"))
    sig_dict["disclaimer"] = VERDICT_DISCLAIMER
    sig_dict["brand"] = _brand_payload()
    if scan_changed:
        db.commit()
    return sig_dict


def book_exposure(db: Session, portfolio_id: int = 1) -> dict:
    """Look-through sector, country and theme exposure for the book.

    The same stage ``scan_portfolio`` feeds to the per-ticker scorers, exposed on
    its own for readers that want the exposure without paying for the verdicts.
    """
    positions = holdings_repository.meta_map(db, portfolio_id)
    quotes = {q["ticker"]: q for q in get_all_quotes(list(positions))}
    alloc_map = _allocation_pcts(positions, quotes)
    return build_portfolio_exposure(_exposure_rows(positions, alloc_map), quotes=quotes)
