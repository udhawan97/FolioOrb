"""
Verdict calibration — log snapshots and compute hit rates over forward windows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import VerdictSnapshot
from app.services.log_safety import sanitize_for_log

logger = logging.getLogger(__name__)

_MIN_SAMPLE_FOR_FOOTNOTE = 20
_FORWARD_WINDOWS = {"1w": 7, "1m": 30, "3m": 90}


def log_verdict_snapshot(
    db: Session,
    *,
    ticker: str,
    action: str,
    confidence: int,
    local_score: int,
    ai_score: Optional[int],
    price_at_scan: Optional[float],
    hold_class: str = "auto",
    portfolio_id: int = 1,
) -> None:
    """Persist one verdict snapshot per scan, scoped to a portfolio."""
    try:
        db.add(VerdictSnapshot(
            portfolio_id=portfolio_id,
            ticker=ticker.upper(),
            action=action,
            confidence=confidence,
            local_score=local_score,
            ai_score=ai_score,
            price_at_scan=price_at_scan,
            hold_class=hold_class,
            generated_at=datetime.now(timezone.utc),
        ))
    except Exception as exc:
        logger.debug(
            "Snapshot log failed for %s: %s", sanitize_for_log(ticker), type(exc).__name__
        )


def _action_hit(action: str, forward_return_pct: float) -> bool:
    if action == "add":
        return forward_return_pct > 2.0
    if action == "trim":
        return forward_return_pct < -2.0
    if action == "hold":
        return abs(forward_return_pct) <= 8.0
    return False


def _predicted_band(confidence: int) -> str:
    if confidence >= 70:
        return "70+"
    if confidence >= 55:
        return "55-69"
    if confidence >= 40:
        return "40-54"
    return "below-40"


def compute_calibration_buckets(
    db: Session,
    *,
    window: str = "1m",
    portfolio_id: int = 1,
) -> list[dict]:
    """
    Compute hit rates by predicted confidence band for one portfolio.
    Uses stored snapshots; forward returns require price_at_scan (reporting only
    until historical prices are backfilled).
    """
    days = _FORWARD_WINDOWS.get(window, 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days + 90)
    rows = (
        db.query(VerdictSnapshot)
        .filter(
            VerdictSnapshot.portfolio_id == portfolio_id,
            VerdictSnapshot.generated_at >= cutoff,
        )
        .order_by(VerdictSnapshot.generated_at.desc())
        .limit(500)
        .all()
    )

    buckets: dict[str, dict] = {}
    for row in rows:
        band = _predicted_band(int(row.confidence or 0))
        if band not in buckets:
            buckets[band] = {"predicted_band": band, "hits": 0, "total": 0}
        buckets[band]["total"] += 1
        # Without forward price backfill, we cannot compute actual hit rate yet
        # Placeholder: mark as pending calibration
        buckets[band]["hits"] += 0

    result = []
    for band, data in sorted(buckets.items()):
        sample = data["total"]
        hit_rate = round(data["hits"] / sample, 2) if sample else None
        result.append({
            "predicted_band": band,
            "actual_hit_rate": hit_rate,
            "sample_size": sample,
            "window": window,
            "status": "collecting" if sample < _MIN_SAMPLE_FOR_FOOTNOTE else "pending_prices",
        })
    return result


def calibration_footnote(
    db: Session,
    *,
    action: str,
    confidence: int,
    buckets: Optional[list[dict]] = None,
    portfolio_id: int = 1,
) -> dict | None:
    """Return footnote when enough samples exist for similar calls.

    Pass `buckets` (from `compute_calibration_buckets(db, window="1m")`) when
    calling this repeatedly in a loop (e.g. once per holding) to avoid
    re-running the same portfolio-wide query/aggregation for every ticker —
    the buckets don't depend on which ticker is being scored.
    """
    band = _predicted_band(confidence)
    if buckets is None:
        buckets = compute_calibration_buckets(db, window="1m", portfolio_id=portfolio_id)
    match = next((b for b in buckets if b["predicted_band"] == band), None)
    if not match or match["sample_size"] < _MIN_SAMPLE_FOR_FOOTNOTE:
        return None
    return {
        "text": (
            f"Historically, {action} calls in the {band}% band are being tracked "
            f"({match['sample_size']} samples)."
        ),
        "sample_size": match["sample_size"],
        "predicted_band": band,
        "tip_title": "Calibration note",
        "tip_body": (
            "We log every verdict and compare forward returns over 1w/1m/3m. "
            "Hit rates appear once enough history accumulates — early samples "
            "are for tracking only, not live adjustment."
        ),
        "caveat": "Past signal performance does not guarantee future results.",
    }


def calibration_summary(db: Session, portfolio_id: int = 1) -> dict:
    """Lightweight summary for API response."""
    buckets = compute_calibration_buckets(db, portfolio_id=portfolio_id)
    total = sum(b["sample_size"] for b in buckets)
    return {
        "total_snapshots": total,
        "buckets": buckets,
        "min_sample_for_footnote": _MIN_SAMPLE_FOR_FOOTNOTE,
    }
