"""The Portfolio action plan — the whole book read at once, as buckets and moves.

``verdict_pipeline`` scores holdings one at a time.  This module turns a finished
scan into the two things the plan card can show: the fused, token-lean snapshot
Claude reads, and the plan itself — either Claude's, dressed, or the
deterministic one FolioOrb writes when Claude is unavailable, forced off, or
looking at a book that is only partly priced.

All of it was inline in the AI router, reachable only through an HTTP handler.
It takes a session and a ``ScanResult`` now, so the plan can be produced,
diffed and tested without one.

The cache namespace lives here too.  The plan is keyed by the portfolio-state
signature the scan already carries, so a book whose dominant action or
concentration has moved reads a fresh plan instead of a stale one.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.services import portfolio_exposure as exposure_service
from app.services import portfolio_valuation
from app.services.timing_signal import timing_bucket
from app.services.verdict_pipeline import VERDICT_DISCLAIMER, ScanResult

logger = logging.getLogger(__name__)

# Fresh valuation weights now own sizing; older narratives may have used
# missing or stale scan allocations, so do not serve them under the new contract.
_CACHE_TYPE = "action_plan_v4"

_GAP_TYPE_LABEL: dict[str, str] = {
    "heavy_hold":    "large position on hold",
    "large_trim":    "oversized position flagged for trim",
    "small_add":     "undersized position with buy signal",
    "uncertain_hold": "low-confidence hold",
}


def cache_type(scan: ScanResult) -> str:
    """Narrative type this book's plan is cached under.

    The scan already carries the portfolio-state signature, so the plan expires
    on state drift as well as on age.
    """
    return f"{_CACHE_TYPE}:{scan.state['summary_type']}"


def invested_tickers(scan: ScanResult) -> list[str]:
    """Tickers that represent owned positions, never research-only ideas."""
    return [
        ticker
        for ticker in scan.tickers
        if not scan.positions.get(ticker, {}).get("is_watchlist")
        and float(scan.positions.get(ticker, {}).get("shares") or 0) > 0
    ]


def has_invested_positions(scan: ScanResult) -> bool:
    """Whether this scan contains at least one owned position."""
    return bool(invested_tickers(scan))


def _complete_allocations(tickers: list[str], allocations: dict) -> bool:
    """All invested weights must be known, finite and reconcile after rounding."""
    if set(allocations) != set(tickers):
        return False
    if not tickers:
        return True
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and 0 <= value <= 100
        for value in allocations.values()
    ):
        return False
    return abs(sum(allocations.values()) - 100) <= len(tickers) * 0.05 + 1e-6


def build_snapshot(
    db: Session, scan: ScanResult, portfolio_id: int = 1
) -> dict:  # pylint: disable=too-many-locals
    """
    Build the compact snapshot sent to Claude for the action plan.
    Fuses per-ticker signal data, portfolio exposure, risk metrics, regime,
    and performance vs benchmark into a token-lean JSON.
    """
    from app.services.portfolio_analytics import (
        compute_portfolio_beta,
        compute_rolling_volatility,
        compute_sector_tilt,
        compute_conviction_gaps,
    )

    signals = scan.signals
    portfolio_exposure = scan.exposure
    regime = scan.regime
    active_tickers = invested_tickers(scan)

    # Portfolio value + per-holding total_return_pct from the valuation module.
    try:
        valuation = portfolio_valuation.evaluate(db, portfolio_id)
        holdings_rows = [
            row for row in valuation.holdings if row.get("ticker") in active_tickers
            and row.get("reporting_eligible", True)
        ]
        total_value = valuation.total_value
        valuation_quality = {
            "data_quality": valuation.data_quality,
            "missing_tickers": list(valuation.missing_tickers),
            "foreign_currency_tickers": list(valuation.foreign_currency_tickers),
            "priced_position_count": valuation.priced_position_count,
            "expected_position_count": valuation.expected_position_count,
        }
    except Exception as exc:
        logger.warning(
            "Action plan Portfolio valuation failed; exception_type=%s",
            type(exc).__name__,
        )
        holdings_rows, total_value = [], 0.0
        valuation_quality = {
            "data_quality": "unavailable",
            "missing_tickers": list(active_tickers),
            "foreign_currency_tickers": [],
            "priced_position_count": 0,
            "expected_position_count": len(active_tickers),
        }

    alloc_map = {row["ticker"]: row.get("allocation_pct") for row in holdings_rows}
    allocation_complete = (
        valuation_quality["data_quality"] == "complete"
        and valuation_quality["expected_position_count"] == len(active_tickers)
        and _complete_allocations(active_tickers, alloc_map)
    )
    if valuation_quality["data_quality"] == "complete" and not allocation_complete:
        valuation_quality["data_quality"] = "partial" if holdings_rows else "unavailable"
    # Exposure was calculated in the earlier scan. Reuse it only when its
    # weights agree with this valuation; otherwise its concentration is unknown.
    exposure_current = allocation_complete and scan.allocation_pct == alloc_map
    if not exposure_current:
        portfolio_exposure = {}

    return_map = {
        h["ticker"]: float(h.get("total_return_pct") or 0)
        for h in holdings_rows
    }

    # Per-holding compact entries
    holdings_data = []
    for ticker in active_tickers:
        sig = {k: v for k, v in (signals.get(ticker) or {}).items()
               if not k.startswith("_")}
        entry: dict = {
            "t": ticker,
            "action": sig.get("action", "needs-data"),
            "conf": sig.get("confidence", 0),
            "alloc_pct": alloc_map.get(ticker) if allocation_complete else None,
            "ret_pct": return_map.get(ticker, 0),
            "reason": (sig.get("reasons") or [""])[0][:80],
            "risk": (sig.get("risks") or [""])[0][:60],
            "flip": sig.get("flip_triggers"),
            "hold_class": sig.get("hold_class", "auto"),
            "timing": timing_bucket(sig.get("timing")),
            "events": bool(sig.get("events")),
        }
        peer = sig.get("peer_relative") or {}
        if peer:
            entry["peer"] = (peer.get("summary") or peer.get("zone") or "")[:60]
        holdings_data.append(entry)

    # Risk metrics
    beta_data: dict = {}
    vol_data: dict = {}
    sector_tilt_data: dict = {}
    conviction_data: dict = {}
    try:
        if holdings_rows:
            beta_data = compute_portfolio_beta(holdings_rows) or {}
            vol_data = compute_rolling_volatility(holdings_rows) or {}
            sector_tilt_data = compute_sector_tilt(holdings_rows) or {}
            conviction_data = compute_conviction_gaps(holdings_rows, signals) or {}
    except Exception as exc:
        logger.debug(
            "Action plan risk metrics failed; exception_type=%s",
            type(exc).__name__,
        )

    # Exposure summary — top 4 sectors + top 3 countries.
    # Keys must match build_portfolio_exposure()'s output exactly; reading
    # "sectors"/"countries" here silently shipped Claude an empty exposure block.
    sectors = (portfolio_exposure.get("sector_exposure") or [])[:4]
    countries = (portfolio_exposure.get("country_exposure") or [])[:3]
    hhi = float(portfolio_exposure.get("concentration_hhi") or 0) if exposure_current else None

    # Conviction gaps summary
    gap_items = (conviction_data.get("gaps") or [])[:3]

    snapshot: dict = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "valuation": valuation_quality,
        "allocation_complete": allocation_complete,
        "total_value": round(total_value, 0),
        "regime": {
            "label": regime.get("label", ""),
            "mood": regime.get("mood", ""),
        },
        "concentration_hhi": round(hhi, 3) if hhi is not None else None,
        "hhi_band": exposure_service.concentration_band(hhi) if hhi is not None else "unavailable",
        "holdings": holdings_data,
        "exposure": {
            "top_sectors": [
                {
                    "s": s.get("name", ""),
                    "w": round(float(s.get("weight_pct") or 0), 1),
                }
                for s in sectors
            ],
            "top_countries": [
                {
                    "c": c.get("name", ""),
                    "w": round(float(c.get("weight_pct") or 0), 1),
                }
                for c in countries
            ],
        },
        "risk": {
            "beta": beta_data.get("beta"),
            "beta_label": beta_data.get("label"),
            "vol_pct": vol_data.get("current_vol_pct"),
        },
        # compute_sector_tilt returns {"sectors": [{name, tilt_pct, ...}]}; the
        # old read of {"tilt": [{sector, overweight_pct}]} matched nothing.
        "tilt": [
            {"s": t.get("name", ""), "vs_spy": round(float(t.get("tilt_pct") or 0), 1)}
            for t in (sector_tilt_data.get("sectors") or [])[:3]
        ],
        "conviction_gaps": [
            {
                "t": g["ticker"],
                "type": _GAP_TYPE_LABEL.get(g["gap_type"], g["gap_type"].replace("_", " ")),
            }
            for g in gap_items
        ],
    }
    return snapshot


def build_plan(scan: ScanResult, parsed: dict) -> dict:
    """Dress Claude's answer as the plan card's payload."""
    return {
        "source": "claude",
        **parsed,
        "regime": scan.regime,
        "disclaimer": VERDICT_DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _local_plan(scan: ScanResult, allocations: dict) -> dict:
    """
    Deterministic fallback when Claude is unavailable or force_local=True.
    Buckets holdings purely from their existing verdict actions.
    """
    signals = scan.signals
    active_tickers = invested_tickers(scan)
    regime = scan.regime

    buckets: dict[str, list[dict]] = {"hold": [], "add": [], "trim": [], "exit": []}
    for ticker in active_tickers:
        sig = signals.get(ticker) or {}
        action = str(sig.get("action") or "hold").lower()
        reason = (sig.get("reasons") or [""])[0][:80]

        if action in ("hold", "add", "trim"):
            bucket_key = action
        else:
            bucket_key = "hold"

        buckets[bucket_key].append({"ticker": ticker, "reason": reason})

    n_hold = len(buckets["hold"])
    n_add  = len(buckets["add"])
    n_trim = len(buckets["trim"])
    n_exit = len(buckets["exit"])
    mood = (regime.get("mood") or "neutral").title()
    regime_label = regime.get("label") or mood

    # Build a plain-language headline from the dominant signal.
    if not active_tickers:
        headline = "No invested positions yet — research ideas stay out of portfolio actions"
    elif n_trim or n_exit:
        headline = (
            f"{n_trim + n_exit} position{'s' if n_trim + n_exit != 1 else ''} flagged for "
            f"trim/exit — {n_hold} anchors steady"
        )
    elif n_add:
        headline = (
            f"{n_add} add signal{'s' if n_add != 1 else ''} surfaced — "
            f"{n_hold} core position{'s' if n_hold != 1 else ''} holding"
        )
    else:
        headline = (
            f"All {n_hold} position{'s' if n_hold != 1 else ''} on hold — "
            "no urgent action from local signals"
        )

    thesis = (
        "Add shares to a research idea when it becomes a position. Until then, "
        "it does not affect P&L, allocation, or portfolio actions."
        if not active_tickers else
        (
            f"FolioOrb local signals: {n_hold} hold · {n_add} add · "
            f"{n_trim} trim · {n_exit} exit. "
            f"Market: {regime_label}. "
            "Enable Claude AI in Settings for a cross-holding, risk-adjusted plan."
        )
    )

    alloc_sorted = sorted(
        list(allocations.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    largest_ticker = alloc_sorted[0][0] if alloc_sorted else ""
    largest_alloc = alloc_sorted[0][1] if alloc_sorted else 0

    priority: list[str] = []
    if buckets["trim"]:
        first_trim = buckets["trim"][0]["ticker"]
        priority.append(
            f"Review {first_trim} — local signal suggests trimming the position."
        )
    if buckets["exit"]:
        first_exit = buckets["exit"][0]["ticker"]
        priority.append(
            f"Evaluate {first_exit} for exit — watchlist flag or deteriorating signal."
        )
    if buckets["add"]:
        first_add = buckets["add"][0]["ticker"]
        priority.append(
            f"Consider building into {first_add} — local signal rates it a buy."
        )

    return {
        "source": "local-fallback",
        "headline": headline,
        "thesis": thesis[:300],
        "buckets": buckets,
        "priority_moves": priority[:3],
        "best_return_note": (
            f"{largest_ticker} is your largest position at {largest_alloc:.0f}% — "
            "right-sizing concentration is the highest-impact lever."
            if largest_ticker else
            "Portfolio concentration is unavailable until complete finite USD allocations exist."
            if active_tickers else
            "Add shares to build an invested portfolio before reading concentration."
        ),
        "regime": regime,
        "disclaimer": VERDICT_DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_fallback(scan: ScanResult, snapshot: dict | None = None) -> dict:
    """The plan FolioOrb writes on its own.

    ``snapshot`` is the read Claude would have seen, or ``None`` when the snapshot
    itself could not be built. When it says
    the book is only partly priced, the plan says so rather than quoting
    Portfolio-level totals it cannot stand behind.
    """
    if snapshot is None:
        snapshot = {"valuation": {
            "data_quality": "unavailable" if has_invested_positions(scan) else "complete",
        }}
    valuation = snapshot.get("valuation") or {}
    allocations = {
        row["t"]: row.get("alloc_pct") for row in snapshot.get("holdings", [])
        if row.get("t") in invested_tickers(scan)
    }
    allocation_complete = (
        valuation.get("data_quality") == "complete"
        and _complete_allocations(invested_tickers(scan), allocations)
    )
    plan = _local_plan(scan, allocations if allocation_complete else {})
    plan.update({
        "allocation_complete": allocation_complete,
        "data_quality": valuation.get("data_quality", "unavailable"),
        "missing_tickers": list(valuation.get("missing_tickers") or []),
        "foreign_currency_tickers": list(valuation.get("foreign_currency_tickers") or []),
    })
    if valuation.get("data_quality") == "complete":
        return plan

    data_quality = valuation.get("data_quality", "unavailable")
    plan.update(
        {
            "source": "data-unavailable" if data_quality == "unavailable" else "partial-data",
            "data_quality": data_quality,
            "missing_tickers": list(valuation.get("missing_tickers") or []),
            "headline": f"Live Portfolio valuation is {data_quality}",
            "thesis": (
                "USD valuation coverage is incomplete. Local signal buckets remain "
                "available; portfolio sizing and concentration need complete USD prices."
            ),
            "best_return_note": (
                "Portfolio concentration is unavailable until USD prices are complete."
            ),
        }
    )
    return plan
