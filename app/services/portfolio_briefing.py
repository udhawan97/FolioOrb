"""The Portfolio briefing card — what the book did, over the range the reader picked.

The card has four faces: the local move digest, the compact snapshot Claude
reads, Claude's answer dressed for the card, and the deterministic answer written
when Claude is not there.  All four were inline in the AI router, so the only way
to produce a briefing was to serve an HTTP request.  They live here instead,
behind names that take a session and a range key and hand back a payload.

Depth sits behind that range key.  ``day`` reads live quotes and per-holding move
explanations; every longer range reads daily closes and snapshot history, drops
the day-scoped fields, swaps in period ones, and caches under its own narrative
type so no range can serve another's text.  Callers never branch on it, and an
unknown range is normalised rather than rejected.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.services import portfolio_valuation
from app.services.ai_service import next_briefing_canned_quote
from app.services.market_regime import get_market_regime
from app.services.move_explainer import explain_move, get_benchmark_data
from app.services.stock_service import get_all_quotes

logger = logging.getLogger(__name__)

_CACHE_TYPE = "briefing"

# Dashboard time ranges the briefing can narrate. "day" keeps the legacy
# live-quote path and the legacy "briefing" cache type; longer ranges compute
# from daily closes and cache under "briefing_<range>" so each range gets its
# own 24 h entry.
_RANGES: dict[str, dict] = {
    "day":        {"phrase": "today",                  "calendar_days": None},
    "week":       {"phrase": "over the past week",     "calendar_days": 7},
    "month":      {"phrase": "over the past month",    "calendar_days": 30},
    "threeMonth": {"phrase": "over the past 3 months", "calendar_days": 90},
    "sixMonth":   {"phrase": "over the past 6 months", "calendar_days": 180},
    "year":       {"phrase": "over the past year",     "calendar_days": 365},
}


def _normalize(range_key: str | None) -> str:
    return range_key if range_key in _RANGES else "day"


def cache_type(range_key: str | None = "day") -> str:
    """Narrative type this range's briefing is cached under."""
    key = _normalize(range_key)
    if key == "day":
        return _CACHE_TYPE
    return f"{_CACHE_TYPE}_{key}"


def _period_portfolio_pl(
    db: Session, total_value: float, calendar_days: int, portfolio_id: int = 1
) -> dict | None:
    """
    Portfolio P&L over the range, from daily snapshot history — the same
    semantics the hero P&L card uses (closest snapshot at/after the cutoff,
    else the earliest available).
    """
    rows = [
        r for r in portfolio_valuation.snapshot_history(db, portfolio_id)
        if r.get("date") and r.get("total_value") is not None
    ]
    if not rows:
        return None
    last = datetime.strptime(rows[-1]["date"], "%Y-%m-%d")
    cutoff = last - timedelta(days=calendar_days)
    start_row = next(
        (r for r in rows if datetime.strptime(r["date"], "%Y-%m-%d") >= cutoff),
        rows[0],
    )
    start_value = float(start_row["total_value"] or 0)
    if start_value <= 0:
        return None
    change = total_value - start_value
    return {"dollar": round(change, 2), "pct": round(change / start_value * 100, 2)}


def _day_snapshot(db: Session, portfolio_id: int = 1) -> tuple[dict, list[dict]]:
    """
    Build the compact portfolio snapshot fed to Haiku (and used for the local
    briefing lead line).  Returns (snapshot_dict, non_watchlist_holdings).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    holdings_rows = valuation.holdings
    total_value = valuation.total_value
    total_daily_change = valuation.total_daily_change
    non_watchlist = [
        holding
        for holding in holdings_rows
        if not holding.get("is_watchlist") and float(holding.get("shares") or 0) > 0
    ]

    total_unrealized = valuation.total_unrealized_gain
    realized = valuation.realized_gain
    total_return_dollar = valuation.total_return
    total_return_pct = valuation.total_return_pct
    prev_value = total_value - total_daily_change
    today_pnl_pct = round(total_daily_change / prev_value * 100, 2) if abs(prev_value) > 0 else 0.0

    sorted_by_day = sorted(
        [h for h in non_watchlist if h.get("day_change_pct") is not None],
        key=lambda h: float(h.get("day_change_pct") or 0),
    )
    best = sorted_by_day[-1] if sorted_by_day else {}
    worst = sorted_by_day[0] if sorted_by_day else {}

    top_by_alloc = sorted(
        [h for h in non_watchlist if h.get("allocation_pct")],
        key=lambda h: float(h.get("allocation_pct") or 0),
        reverse=True,
    )[:6]

    top_contributors = sorted(
        non_watchlist,
        key=lambda h: abs(float(h.get("daily_value_change") or 0)),
        reverse=True,
    )[:4]

    regime = get_market_regime()

    snapshot = {
        "as_of": today,
        "invested_position_count": valuation.expected_position_count,
        "research_idea_count": sum(
            1 for holding in holdings_rows if holding.get("is_watchlist")
        ),
        "valuation": {
            "data_quality": valuation.data_quality,
            "missing_tickers": list(valuation.missing_tickers),
            "priced_position_count": valuation.priced_position_count,
            "expected_position_count": valuation.expected_position_count,
        },
        "total_value": round(total_value, 2),
        "today_pl": {
            "dollar": round(total_daily_change, 2),
            "pct": today_pnl_pct,
        },
        "total_return": {
            "dollar": total_return_dollar,
            "pct": total_return_pct,
            "unrealized": round(total_unrealized, 2),
            "realized": round(realized, 2),
        },
        "best_today": {
            "ticker": best.get("ticker", ""),
            "day_change_pct": float(best.get("day_change_pct") or 0),
        },
        "worst_today": {
            "ticker": worst.get("ticker", ""),
            "day_change_pct": float(worst.get("day_change_pct") or 0),
        },
        "top_holdings": [
            {
                "ticker": h["ticker"],
                "allocation_pct": float(h.get("allocation_pct") or 0),
                "day_change_pct": float(h.get("day_change_pct") or 0),
                "total_return_pct": float(h.get("total_return_pct") or 0),
            }
            for h in top_by_alloc
        ],
        "today_contributors": [
            {
                "ticker": h["ticker"],
                "contribution_dollar": round(float(h.get("daily_value_change") or 0), 2),
            }
            for h in top_contributors
        ],
        "market_regime": {
            "label": regime.get("label", ""),
            "mood": regime.get("mood", ""),
        },
    }
    return snapshot, non_watchlist


def _period_snapshot(
    db: Session, range_key: str, portfolio_id: int = 1
) -> tuple[dict, list[dict]]:
    """
    Range-aware snapshot variant: swaps the day-scoped fields for period ones
    (daily-close lookbacks for movers, snapshot history for portfolio P&L) so
    Haiku narrates the selected window instead of today's tape.
    """
    from app.services.portfolio_analytics import compute_range_rows

    snapshot, non_watchlist = _day_snapshot(db, portfolio_id)
    cfg = _RANGES[range_key]
    period = compute_range_rows(non_watchlist, range_key)
    rows = period.get("holdings") or {}

    ranked = sorted(rows.items(), key=lambda kv: kv[1]["change_pct"])
    best = ranked[-1] if ranked else None
    worst = ranked[0] if ranked else None
    contributors = sorted(
        rows.items(), key=lambda kv: abs(kv[1]["value_change"]), reverse=True
    )[:4]

    snapshot["period_label"] = cfg["phrase"]
    snapshot["period_pl"] = (
        _period_portfolio_pl(
            db, snapshot["total_value"], cfg["calendar_days"], portfolio_id
        )
        or {"dollar": period.get("net_change"), "pct": period.get("net_change_pct")}
    )
    snapshot["best_period"] = (
        {"ticker": best[0], "change_pct": best[1]["change_pct"]} if best else {}
    )
    snapshot["worst_period"] = (
        {"ticker": worst[0], "change_pct": worst[1]["change_pct"]} if worst else {}
    )
    snapshot["period_contributors"] = [
        {"ticker": ticker, "contribution_dollar": vals["value_change"]}
        for ticker, vals in contributors
    ]
    for h in snapshot["top_holdings"]:
        row = rows.get(h["ticker"])
        h["period_change_pct"] = row["change_pct"] if row else None
        h.pop("day_change_pct", None)
    for key in ("today_pl", "best_today", "worst_today", "today_contributors"):
        snapshot.pop(key, None)
    return snapshot, non_watchlist


def build_snapshot(db: Session, range_key: str | None = "day", portfolio_id: int = 1) -> dict:
    """Compact Portfolio read for the range, shaped for Claude's token budget."""
    key = _normalize(range_key)
    if key == "day":
        return _day_snapshot(db, portfolio_id)[0]
    return _period_snapshot(db, key, portfolio_id)[0]


def has_invested_positions(snapshot: dict) -> bool:
    """Whether a briefing snapshot contains owned positions."""
    return int(snapshot.get("invested_position_count") or 0) > 0


def empty_position_response(snapshot: dict, *, mode: str) -> dict:
    """Research-only/empty portfolio copy shared by local and AI modes."""
    research_count = int(snapshot.get("research_idea_count") or 0)
    research = (
        f"{research_count} research idea{'s' if research_count != 1 else ''} "
        f"{'remains' if research_count == 1 else 'remain'} outside portfolio P&L."
        if research_count else
        "Research ideas remain outside portfolio P&L."
    )
    base = {
        "mode": mode,
        "source": "no-invested-positions",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if mode == "ai":
        return {
            **base,
            "health": f"No invested positions yet — {research}",
            "drivers": [],
            "adjustments": [
                "Add shares to an idea when it becomes an invested position."
            ],
            "quote": next_briefing_canned_quote(),
        }
    return {
        **base,
        "lead": f"No invested positions yet — {research}",
        "movers": [],
    }


def _local_quality_response(
    snapshot: dict,
    *,
    period_label: str | None = None,
) -> dict:
    """Return an honest local briefing when live valuation is incomplete."""
    quality = snapshot.get("valuation") or {}
    data_quality = quality.get("data_quality", "unavailable")
    missing = list(quality.get("missing_tickers") or [])
    scope = f" {period_label}" if period_label else ""
    return {
        "mode": "local",
        "source": "data-unavailable" if data_quality == "unavailable" else "partial-data",
        "lead": (
            f"Live valuation is {data_quality}{scope}; "
            "unpriced positions are not being narrated as a complete Portfolio."
        ),
        "movers": [],
        "data_quality": data_quality,
        "missing_tickers": missing,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _local_period(db: Session, range_key: str, portfolio_id: int = 1) -> dict:
    """
    Local briefing over a non-day range: deterministic period digest from daily
    closes. Move explainers are day-scoped, so period movers carry no
    explanation text.
    """
    from app.services.portfolio_analytics import compute_range_rows

    cfg = _RANGES[range_key]
    phrase = cfg["phrase"]
    snapshot, non_watchlist = _day_snapshot(db, portfolio_id)
    if not has_invested_positions(snapshot):
        response = empty_position_response(snapshot, mode="local")
        response["period_label"] = phrase
        return response
    quality = snapshot.get("valuation") or {}
    if quality.get("data_quality") != "complete":
        return _local_quality_response(snapshot, period_label=phrase)
    period = compute_range_rows(non_watchlist, range_key)
    rows = period.get("holdings") or {}

    movers: list[dict] = []
    for h in non_watchlist:
        row = rows.get(h["ticker"])
        if not row:
            continue
        movers.append({
            "ticker": h["ticker"],
            # Field names match the day payload so the card renderer is shared.
            "day_change_pct": row["change_pct"],
            "day_change_dollar": row["value_change"],
            "icon": "bi-graph-up-arrow" if row["change_pct"] >= 0 else "bi-graph-down-arrow",
            "explanation": "",
        })
    movers.sort(key=lambda m: abs(m["day_change_dollar"]), reverse=True)
    movers = movers[:6]

    rose = sum(1 for r in rows.values() if r["change_pct"] > 0)
    fell = sum(1 for r in rows.values() if r["change_pct"] < 0)
    total = len(rows)

    if not total:
        lead = f"Not enough price history yet to read your portfolio {phrase}."
    elif rose > 0:
        best_ticker, best_vals = max(rows.items(), key=lambda kv: kv[1]["change_pct"])
        lead = (
            f"{rose} of {total} holdings rose {phrase}, "
            f"led by {best_ticker} ({best_vals['change_pct']:+.1f}%)."
        )
    elif fell == total:
        worst_ticker, worst_vals = min(rows.items(), key=lambda kv: kv[1]["change_pct"])
        lead = (
            f"All {total} holdings fell {phrase}; "
            f"{worst_ticker} pulled back the most ({worst_vals['change_pct']:+.1f}%)."
        )
    else:
        lead = f"Holdings were flat {phrase} — no clear directional trend."

    return {
        "mode": "local",
        "lead": lead,
        "movers": movers,
        "period_label": phrase,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _local_day(db: Session, portfolio_id: int = 1) -> dict:
    """Compute local briefing using move_explainer. Never calls Claude."""
    snapshot, non_watchlist = _day_snapshot(db, portfolio_id)
    if not has_invested_positions(snapshot):
        return empty_position_response(snapshot, mode="local")
    if (snapshot.get("valuation") or {}).get("data_quality") != "complete":
        return _local_quality_response(snapshot)
    active_tickers = [h["ticker"] for h in non_watchlist]
    quotes = {q["ticker"]: q for q in get_all_quotes(active_tickers)}
    benchmarks = get_benchmark_data()
    benchmark_cache: dict = {}

    movers: list[dict] = []
    rose = fell = 0
    for h in non_watchlist:
        ticker = h["ticker"]
        stock_data = quotes.get(ticker) or {}
        if stock_data.get("error") or not stock_data:
            shares = float(h.get("shares") or 1)
            stock_data = {
                "ticker": ticker,
                "day_change_pct": h.get("day_change_pct", 0),
                "day_change": round(float(h.get("daily_value_change") or 0) / shares, 4),
            }

        day_chg = float(h.get("day_change_pct") or 0)
        if day_chg > 0:
            rose += 1
        elif day_chg < 0:
            fell += 1

        try:
            summary = explain_move(
                stock_data,
                shared_benchmarks=benchmarks,
                _benchmark_cache=benchmark_cache,
            )
            icon = summary.drivers[0].icon if summary.drivers else "bi-question-circle"
            explanation = (summary.explanation_text or "")[:240]
        except Exception as exc:
            logger.debug("Briefing explain_move failed; exception_type=%s", type(exc).__name__)
            icon = "bi-question-circle"
            explanation = ""

        movers.append({
            "ticker": ticker,
            "day_change_pct": day_chg,
            "day_change_dollar": round(float(h.get("daily_value_change") or 0), 2),
            "icon": icon,
            "explanation": explanation,
        })

    movers.sort(key=lambda m: abs(m["day_change_dollar"]), reverse=True)
    movers = movers[:6]

    total = rose + fell
    best = snapshot.get("best_today") or {}
    best_t = best.get("ticker", "")
    best_pct = float(best.get("day_change_pct") or 0)
    worst_snap = snapshot.get("worst_today") or {}

    if rose > 0 and best_t and total > 0:
        lead = f"{rose} of {total} holdings rose today, led by {best_t} ({best_pct:+.1f}%)."
    elif fell == total > 0:
        w_t = worst_snap.get("ticker", "")
        w_pct = float(worst_snap.get("day_change_pct") or 0)
        lead = (
            f"All {total} holdings fell today; "
            f"{w_t} pulled back the most ({w_pct:+.1f}%)." if w_t
            else f"All {total} holdings fell today."
        )
    else:
        lead = "Holdings were mixed today — no clear directional trend."

    return {
        "mode": "local",
        "lead": lead,
        "movers": movers,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_local(db: Session, range_key: str | None = "day", portfolio_id: int = 1) -> dict:
    """Deterministic move digest for the range.  Never calls Claude, always free."""
    key = _normalize(range_key)
    if key == "day":
        return _local_day(db, portfolio_id)
    return _local_period(db, key, portfolio_id)


def build_briefing(parsed: dict) -> dict:
    """Dress Claude's answer as the card's AI-mode payload."""
    return {
        "mode": "ai",
        "source": "claude",
        **parsed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_fallback(snapshot: dict) -> dict:
    """Deterministic AI-mode response when Claude is unavailable."""
    if not has_invested_positions(snapshot):
        return empty_position_response(snapshot, mode="ai")
    quality = snapshot.get("valuation") or {}
    data_quality = quality.get("data_quality", "complete")
    missing = list(quality.get("missing_tickers") or [])
    if data_quality != "complete":
        missing_text = ", ".join(missing) if missing else "current positions"
        return {
            "mode": "ai",
            "source": "data-unavailable" if data_quality == "unavailable" else "partial-data",
            "health": (
                "Live valuation is unavailable; no return narrative was generated."
                if data_quality == "unavailable"
                else "Live valuation is partial; return figures omit unpriced positions."
            ),
            "drivers": [f"Missing current prices for: {missing_text}."],
            "adjustments": ["Retry when market data is available before acting on this read."],
            "quote": next_briefing_canned_quote(),
            "data_quality": data_quality,
            "missing_tickers": missing,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    phrase = snapshot.get("period_label") or "today"
    pl = snapshot.get("today_pl") or snapshot.get("period_pl") or {}
    tr = snapshot.get("total_return") or {}
    best = snapshot.get("best_today") or snapshot.get("best_period") or {}
    worst = snapshot.get("worst_today") or snapshot.get("worst_period") or {}

    def _mover_pct(entry: dict) -> float:
        value = entry.get("day_change_pct")
        if value is None:
            value = entry.get("change_pct")
        return float(value or 0)

    direction = "up" if float(pl.get("dollar") or 0) >= 0 else "down"
    pct = abs(float(pl.get("pct") or 0))
    ret_pct = float(tr.get("pct") or 0)
    health = (
        f"Your portfolio is {direction} {pct:.2f}% {phrase}. "
        f"Total return stands at {ret_pct:+.2f}% overall."
    )
    drivers: list[str] = []
    if best.get("ticker"):
        drivers.append(
            f"{best['ticker']} was your best mover {phrase} "
            f"({_mover_pct(best):+.1f}%)."
        )
    if worst.get("ticker") and worst.get("ticker") != best.get("ticker"):
        drivers.append(
            f"{worst['ticker']} pulled back "
            f"({_mover_pct(worst):+.1f}%)."
        )
    if not drivers:
        drivers = [f"No standout movers {phrase}."]

    return {
        "mode": "ai",
        "source": "local-fallback",
        "health": health,
        "drivers": drivers,
        "adjustments": ["No changes needed — the book looks balanced."],
        "quote": next_briefing_canned_quote(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
