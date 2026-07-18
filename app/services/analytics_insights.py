"""
Analytics tab insights — compact snapshot + local one-liners per sub-tab.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# Widgets that render the full AI tip card (headline + personalized insight).
# All other widgets keep the plain-string one-liner format.
KEY_TIP_WIDGETS: frozenset[str] = frozenset({
    "beta-dial", "drawdown", "correlation", "risk-reward",
    "concentration", "benchmark-tracker", "rolling-vol",
    "conviction-gap", "sector-treemap", "contribution",
})

WIDGET_TIP_HEADLINES: dict[str, str] = {
    "beta-dial": "Beta measures your market sensitivity",
    "drawdown": "Drawdown tracks your peak-to-trough loss",
    "correlation": "Correlation reveals how holdings move together",
    "risk-reward": "Risk vs. return shows if your bets are fairly priced",
    "concentration": "Concentration measures how spread your bets are",
    "benchmark-tracker": "Benchmark shows if you're ahead of the market",
    "rolling-vol": "Volatility tracks how bumpy your ride has been",
    "conviction-gap": "Conviction gaps flag position-sizing mismatches",
    "sector-treemap": "Sector exposure reveals your industry bets",
    "contribution": "Attribution shows what's really driving your P&L",
}


def _make_tip(key: str, insight: str) -> "dict[str, str] | str":
    """Wrap key-widget insights as structured tip objects; others stay as strings."""
    if key in KEY_TIP_WIDGETS and insight:
        return {"headline": WIDGET_TIP_HEADLINES.get(key, ""), "insight": insight}
    return insight


MODULE_DIGEST: dict[str, str] = {
    "performance": (
        "Your return story — total P&L, performance history, growth scenarios, "
        "benchmark comparison, monthly calendar, and realized trades."
    ),
    "risk": (
        "How bumpy and concentrated your book is: reward vs volatility, correlation, "
        "drawdowns, beta, rolling volatility, and diversification."
    ),
    "exposure": (
        "What you truly own after looking inside ETFs — sector and country weights, "
        "benchmark tilt, and your allocation table."
    ),
    "signals": (
        "FolioOrb verdicts on each holding, P&L attribution, conviction gaps, "
        "confidence spectrum, and your overall book tone."
    ),
    "markets": (
        "Live world indices, sensitivity estimates, macro alignment, and how closely "
        "each market moves with your portfolio."
    ),
}

# Widget data Claude needs for KEY_TIP_WIDGETS only (plain widgets use local one-liners).
_AI_WIDGET_KEYS: frozenset[str] = frozenset({
    "benchmark", "risk_reward", "beta", "rolling_vol",
    "sector_tilt", "conviction_gaps", "confidence_spectrum",
})

WIDGET_KEYS: tuple[str, ...] = (
    "total-return", "pnl-history", "projection",
    "benchmark-tracker", "return-calendar",
    "risk-reward", "correlation", "concentration", "drawdown", "beta-dial", "rolling-vol",
    "sector-treemap", "geo-exposure", "allocation-table", "sector-tilt",
    "contribution", "signal-board", "verdict-mix", "conviction-gap", "confidence-spectrum",
    "markets-tape", "markets-grid", "macro-alignment",
)


def _concentration_word(hhi: float) -> str:
    if hhi < 0.25:
        return "well spread"
    if hhi < 0.5:
        return "moderately concentrated"
    if hhi < 0.75:
        return "concentrated"
    return "very concentrated"


def _performance_insight(perf: dict, valuation: dict) -> str:
    """Describe returns without presenting an incomplete valuation as whole."""
    if valuation.get("data_quality") not in (None, "complete"):
        missing = ", ".join(valuation.get("missing_tickers") or []) or "current positions"
        return (
            f"Live valuation is {valuation.get('data_quality')}; "
            f"return figures omit {missing}."
        )
    if perf.get("has_holdings"):
        hist_note = (
            f" with {perf.get('history_days', 0)} days of history tracked"
            if perf.get("history_days")
            else ""
        )
        return (
            f"You're {perf.get('total_return_pct', 0):+.1f}% all-in"
            f"{hist_note}; today is {perf.get('today_pnl_pct', 0):+.1f}%."
        )
    return "Set share counts to start tracking total return and building your performance chart."


def build_local_analytics_insights(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Deterministic one-liner per analytics sub-tab + static digests."""
    perf = snapshot.get("performance") or {}
    risk = snapshot.get("risk") or {}
    exposure = snapshot.get("exposure") or {}
    signals = snapshot.get("signals") or {}
    markets = snapshot.get("markets") or {}
    valuation = snapshot.get("valuation") or {}

    insights: dict[str, str] = {
        "performance": _performance_insight(perf, valuation),
    }

    if risk.get("has_data"):
        top = risk.get("top_sector")
        vol = risk.get("portfolio_vol_pct")
        vol_bit = f" ~{vol:.0f}% annual volatility." if vol else ""
        sector_bit = f" Top sector: {top}." if top else ""
        insights["risk"] = (
            f"Concentration looks {_concentration_word(float(risk.get('concentration_hhi') or 0))}."
            f"{vol_bit}{sector_bit}"
        ).strip()
    else:
        insights["risk"] = "Add holdings to see volatility, correlation, and drawdown readings."

    if exposure.get("has_data"):
        sectors = exposure.get("top_sectors") or []
        countries = exposure.get("top_countries") or []
        s0 = sectors[0]["name"] if sectors else "mixed sectors"
        c0 = countries[0]["name"] if countries else "multiple regions"
        if sectors:
            insights["exposure"] = (
                f"Largest look-through slice is {s0} ({sectors[0]['weight_pct']:.0f}%); "
                f"geography leans {c0}."
            )
        else:
            insights["exposure"] = f"Largest look-through slice is {s0}; geography leans {c0}."
    else:
        insights["exposure"] = "Exposure maps appear once holdings have look-through data."

    if signals.get("has_data"):
        dom = (signals.get("dominant_action") or "hold").upper()
        insights["signals"] = (
            f"Overall tone is {dom} with "
            f"~{signals.get('hold_weight_pct', 0):.0f}% of the book on hold"
            f" and average confidence {signals.get('avg_confidence', 0):.0f}%."
        )
    else:
        insights["signals"] = "Signals summarize FolioOrb's read once holdings are set up."

    if markets.get("has_data"):
        name = markets.get("best_match_name") or "global equities"
        corr = float(markets.get("best_correlation") or 0)
        insights["markets"] = (
            f"Most in sync with {name} ({corr * 100:.0f}% correlated)"
            + (
                f"; ~{markets.get('us_exposure_pct', 0):.0f}% US look-through exposure."
                if markets.get("us_exposure_pct", 0) >= 30
                else "."
            )
        )
    else:
        insights["markets"] = (
            "Markets context links global indices to your book once holdings exist."
        )

    return {
        "mode": "local",
        "source": "local",
        "data_quality": valuation.get("data_quality", "complete"),
        "missing_tickers": list(valuation.get("missing_tickers") or []),
        "insights": insights,
        "digest": dict(MODULE_DIGEST),
        "widget_insights": build_local_widget_insights(snapshot),
    }


def _beta_layman_short(beta: float) -> str:
    if beta < 0.85:
        return f"Sensitivity {beta:.2f}× — tends to move quieter than the S&P 500."
    if beta < 1.15:
        return f"Sensitivity {beta:.2f}× — tends to move in step with the S&P 500."
    extra = round((beta - 1) * 100)
    return (
        f"Sensitivity {beta:.2f}× — about {extra}% more swing "
        f"than the S&P 500 on typical market days."
    )


def _widget_perf_insights(perf: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if perf.get("has_holdings"):
        out["total-return"] = (
            f"All-in return is {perf.get('total_return_pct', 0):+.1f}%"
            f" with {perf.get('today_pnl_pct', 0):+.1f}% today."
        )
    else:
        out["total-return"] = "Set share counts to unlock total return tracking."

    hist_days = perf.get("history_days") or 0
    if hist_days >= 2:
        out["pnl-history"] = (
            f"{hist_days} days of performance history charted against the S&P 500."
        )
    else:
        out["pnl-history"] = "Visit daily to build your performance history chart."

    out["projection"] = (
        "Scenarios use 3-year historical return and volatility — not a forecast."
    )
    return out


def _widget_benchmark_calendar_insights(widgets: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    bench = widgets.get("benchmark") or {}
    if bench.get("has_data"):
        alpha = (bench.get("ranges") or {}).get("1y", {}).get("alpha_pct")
        if alpha is not None:
            word = "ahead of" if alpha >= 0 else "behind"
            bench_insight = (
                f"Over the past year you're {abs(alpha):.1f}pp {word} the S&P 500."
            )
        else:
            bench_insight = "Your cumulative return path vs the S&P 500 is being tracked."
        out["benchmark-tracker"] = _make_tip("benchmark-tracker", bench_insight)
    else:
        out["benchmark-tracker"] = _make_tip(
            "benchmark-tracker",
            "Benchmark comparison requires holdings and at least one snapshot day.",
        )

    cal = widgets.get("return_calendar") or {}
    if cal.get("has_data"):
        months = cal.get("months") or []
        pos = sum(1 for m in months if m.get("return_pct", 0) > 0)
        out["return-calendar"] = f"{pos} of {len(months)} recent months finished positive."
    else:
        out["return-calendar"] = "Monthly tiles appear after a few weeks of history."
    return out


def _widget_risk_insights(risk: dict, widgets: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if not risk.get("has_data"):
        for key in ("risk-reward", "correlation", "concentration", "drawdown"):
            out[key] = _make_tip(key, "Add holdings to populate this risk reading.")
        beta = widgets.get("beta") or {}
        if beta.get("has_data"):
            out["beta-dial"] = _make_tip(
                "beta-dial",
                _beta_layman_short(float(beta.get("beta") or 1)),
            )
        else:
            out["beta-dial"] = _make_tip(
                "beta-dial",
                "Your portfolio's sensitivity to the S&P 500 will appear here "
                "once holdings are set up.",
            )
        roll = widgets.get("rolling_vol") or {}
        if roll.get("has_data"):
            vol = roll.get("current_vol_pct", 0)
            lvl = "calm" if vol < 14 else "typical" if vol < 22 else "choppy"
            roll_insight = (
                f"Your trailing 30-day bumpiness reads {lvl} at ~{vol:.0f}% annualised —"
                f" higher means bigger day-to-day swings."
            )
            out["rolling-vol"] = _make_tip("rolling-vol", roll_insight)
        else:
            out["rolling-vol"] = _make_tip(
                "rolling-vol",
                "Tracks how choppy your portfolio has been over the last month.",
            )
        return out

    port = (widgets.get("risk_reward") or {}).get("portfolio") or {}
    rr_insight = (
        f"Your portfolio sits at ~{port.get('annual_return_pct', 0):+.0f}% annual return"
        f" and ~{port.get('annual_vol_pct', 0):.0f}% volatility — "
        f"check where it lands vs peers."
    )
    out["risk-reward"] = _make_tip("risk-reward", rr_insight)
    out["correlation"] = _make_tip(
        "correlation",
        "Warmer tiles mean those holdings tend to rise and fall together, "
        "reducing diversification.",
    )

    hhi = float(risk.get("concentration_hhi") or 0)
    conc_word = _concentration_word(hhi)
    spread_note = (
        "spread your bets further to reduce single-name risk"
        if hhi >= 0.5
        else "diversification looks healthy"
    )
    conc_insight = (
        f"Your book reads {conc_word} (HHI {(hhi * 100):.0f}) — {spread_note}."
    )
    out["concentration"] = _make_tip("concentration", conc_insight)

    dd = risk.get("max_drawdown_pct")
    if dd:
        dd_insight = (
            f"Your worst peak-to-trough dip has been {dd:.1f}% — "
            f"the shaded area shows how long you stayed underwater."
        )
        out["drawdown"] = _make_tip("drawdown", dd_insight)
    else:
        out["drawdown"] = _make_tip(
            "drawdown",
            "The shaded area shows how far below your high-water mark "
            "the portfolio has fallen.",
        )

    beta = widgets.get("beta") or {}
    if beta.get("has_data"):
        out["beta-dial"] = _make_tip(
            "beta-dial", _beta_layman_short(float(beta.get("beta") or 1))
        )
    else:
        out["beta-dial"] = _make_tip(
            "beta-dial",
            "Your portfolio's sensitivity to the S&P 500 will appear here "
            "once holdings are set up.",
        )

    roll = widgets.get("rolling_vol") or {}
    if roll.get("has_data"):
        vol = roll.get("current_vol_pct", 0)
        lvl = "calm" if vol < 14 else "typical" if vol < 22 else "choppy"
        roll_insight = (
            f"Your trailing 30-day bumpiness reads {lvl} at ~{vol:.0f}% annualised —"
            f" higher means bigger day-to-day swings."
        )
        out["rolling-vol"] = _make_tip("rolling-vol", roll_insight)
    else:
        out["rolling-vol"] = _make_tip(
            "rolling-vol",
            "Tracks how choppy your portfolio has been over the last month.",
        )
    return out


def _widget_exposure_insights(exposure: dict, widgets: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if not exposure.get("has_data"):
        out["sector-treemap"] = _make_tip(
            "sector-treemap",
            "Sector exposure tiles appear once holdings have look-through data.",
        )
        for key in ("geo-exposure", "allocation-table", "sector-tilt"):
            out[key] = "Exposure maps appear once holdings have look-through data."
        return out

    sectors = exposure.get("top_sectors") or []
    s0 = sectors[0]["name"] if sectors else "your largest sector"
    s0_pct = sectors[0].get("weight_pct", 0) if sectors else 0
    treemap_insight = (
        f"{s0} is your largest look-through sector at {s0_pct:.0f}% —"
        f" tap any tile to see the exact weight."
        if sectors
        else "Tap any tile to explore your sector weights after ETF look-through."
    )
    out["sector-treemap"] = _make_tip("sector-treemap", treemap_insight)
    countries = exposure.get("top_countries") or []
    c0 = countries[0]["name"] if countries else "multiple regions"
    out["geo-exposure"] = f"Geography leans {c0} after fund look-through."
    out["allocation-table"] = "Sorted by weight — tap headers to re-order."
    tilt = widgets.get("sector_tilt") or {}
    tilts = tilt.get("sectors") or []
    if tilts:
        top = max(tilts, key=lambda s: abs(s.get("tilt_pct") or 0))
        direction = "overweight" if top.get("tilt_pct", 0) > 0 else "underweight"
        out["sector-tilt"] = (
            f"Largest tilt vs S&P 500: {top.get('name')} "
            f"({direction} {abs(top.get('tilt_pct', 0)):.0f}pp)."
        )
    else:
        out["sector-tilt"] = "Sector tilt compares your look-through mix to the S&P 500."
    return out


def _conviction_gap_insight(gaps: dict) -> str:
    gap_rows = gaps.get("gaps") or []
    summary = gaps.get("summary") or {}
    if not gap_rows:
        return (
            "All positions broadly match their signals — "
            "no major sizing mismatches right now."
        )
    g0 = gap_rows[0]
    gap_type = g0.get("gap_type", "")
    ticker = g0.get("ticker", "")
    alloc = g0.get("allocation_pct", 0)
    action = (g0.get("action") or "hold").lower()
    flagged = summary.get("flagged", len(gap_rows))
    total_h = summary.get("total", 0)
    flagged_alloc = summary.get("flagged_alloc_pct", 0)
    count_note = (
        f"{flagged} of {total_h} holdings flagged ({flagged_alloc:.0f}% of portfolio). "
        if total_h
        else ""
    )
    templates = {
        "large_trim": (
            f"{count_note}Biggest: {ticker} at {alloc:.0f}% but a {action} signal "
            f"— may be oversized."
        ),
        "small_add": (
            f"{count_note}Biggest opportunity: {ticker} has a buy signal but only "
            f"{alloc:.0f}% allocated."
        ),
        "heavy_hold": (
            f"{count_note}Biggest: {ticker} at {alloc:.0f}% with just a hold signal "
            f"— large bet, limited upside case."
        ),
        "uncertain_hold": (
            f"{count_note}Biggest uncertainty: {ticker} at {alloc:.0f}% — "
            f"AI confidence is low on this signal."
        ),
    }
    return templates.get(
        gap_type,
        f"{count_note}{ticker}: {action} signal on {alloc:.0f}% of the book — worth reviewing.",
    )


def _confidence_spectrum_insight(spec: dict) -> str:
    if not spec.get("has_data"):
        return (
            "Confidence spectrum shows how much of your portfolio has "
            "strong vs weak AI signals."
        )
    avg_conf = spec.get("avg_confidence") or 0
    dominant = spec.get("dominant_band") or "unknown"
    if avg_conf >= 75:
        return (
            f"Most weight is in the {dominant} band — signals are generally "
            f"strong across your portfolio."
        )
    if avg_conf >= 60:
        return (
            f"Most weight is in the {dominant} band — signals are mixed; "
            f"some positions have less certainty behind them."
        )
    return (
        f"Most weight is in the {dominant} band — average confidence is low "
        f"({avg_conf}%), signals are uncertain."
    )


def _widget_signals_insights(signals: dict, widgets: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if not signals.get("has_data"):
        out["contribution"] = _make_tip(
            "contribution",
            "Signals and attribution appear once holdings are set up.",
        )
        out["conviction-gap"] = _make_tip(
            "conviction-gap",
            "Conviction gap analysis requires holdings with active FolioOrb signals.",
        )
        for key in ("signal-board", "verdict-mix", "confidence-spectrum"):
            out[key] = "Signals summarize FolioOrb's read once holdings are set up."
        return out

    out["contribution"] = _make_tip(
        "contribution",
        "The bars show dollar P&L per holding — the tallest bar is your biggest "
        "driver this period.",
    )
    out["signal-board"] = "Greener tiles lean add/buy; redder tiles lean trim/sell."
    dom = (signals.get("dominant_action") or "hold").upper()
    out["verdict-mix"] = f"Book tone skews {dom} by allocation weight."
    gaps = widgets.get("conviction_gaps") or {}
    out["conviction-gap"] = _make_tip(
        "conviction-gap",
        _conviction_gap_insight(gaps),
    )
    spec = widgets.get("confidence_spectrum") or {}
    out["confidence-spectrum"] = _confidence_spectrum_insight(spec)
    return out


def _widget_markets_insights(markets: dict, widgets: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if not markets.get("has_data"):
        for key in ("markets-tape", "markets-grid", "macro-alignment"):
            out[key] = "Markets context links global indices to your book once holdings exist."
        return out

    out["markets-tape"] = "Scrolling live quotes — hover to pause."
    name = markets.get("best_match_name") or "global equities"
    corr = float(markets.get("best_correlation") or 0)
    sens = widgets.get("market_sensitivity") or {}
    top_idx = (sens.get("indices") or [{}])[0]
    if top_idx.get("name") and top_idx.get("impact_per_1pct") is not None:
        out["markets-grid"] = (
            f"Closest daily link: {name} ({corr * 100:.0f}% correlated). "
            f"A 1% {top_idx['name']} move may shift your book "
            f"~{top_idx.get('impact_per_1pct', 0):+.2f}%."
        )
    else:
        out["markets-grid"] = f"Closest daily link: {name} ({corr * 100:.0f}% correlated)."

    macro = widgets.get("macro_alignment") or {}
    pts = macro.get("points") or []
    if pts:
        hot = max(
            pts,
            key=lambda p: (p.get("correlation") or 0) * (p.get("geo_weight_pct") or 0),
        )
        out["macro-alignment"] = (
            f"{hot.get('name')} pairs {hot.get('correlation', 0) * 100:.0f}% correlation"
            f" with ~{hot.get('geo_weight_pct', 0):.0f}% geo exposure."
        )
    else:
        out["macro-alignment"] = "Plots correlation vs geographic exposure per index."
    return out


def build_local_widget_insights(snapshot: dict[str, Any]) -> dict[str, str]:
    """Deterministic one-liner per analytics widget card."""
    perf = snapshot.get("performance") or {}
    risk = snapshot.get("risk") or {}
    exposure = snapshot.get("exposure") or {}
    signals = snapshot.get("signals") or {}
    markets = snapshot.get("markets") or {}
    widgets = snapshot.get("widgets") or {}

    out: dict[str, str] = {}
    out.update(_widget_perf_insights(perf))
    out.update(_widget_benchmark_calendar_insights(widgets))
    out.update(_widget_risk_insights(risk, widgets))
    out.update(_widget_exposure_insights(exposure, widgets))
    out.update(_widget_signals_insights(signals, widgets))
    out.update(_widget_markets_insights(markets, widgets))
    return {k: out.get(k, "") for k in WIDGET_KEYS if out.get(k)}


def build_ai_analytics_prompt_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Slim snapshot for Claude — tab fields + data for KEY tip widgets only."""
    widgets = snapshot.get("widgets") or {}
    markets = snapshot.get("markets") or {}
    return {
        "as_of": snapshot.get("as_of"),
        "valuation": snapshot.get("valuation"),
        "performance": snapshot.get("performance"),
        "risk": snapshot.get("risk"),
        "exposure": snapshot.get("exposure"),
        "signals": snapshot.get("signals"),
        "markets": {
            k: markets[k]
            for k in ("has_data", "best_match_name", "best_correlation", "us_exposure_pct")
            if k in markets
        },
        "widgets": {k: widgets[k] for k in _AI_WIDGET_KEYS if k in widgets},
    }


def build_analytics_fallback(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Use local lines when Claude is unavailable."""
    payload = build_local_analytics_insights(snapshot)
    payload["source"] = "local-fallback"
    return payload


def fetch_world_markets_sync() -> list[dict]:
    """Sync world-index quotes (same list and payload as the stocks router)."""
    from app.services.world_markets import WORLD_MARKETS, fetch_world_market

    return [fetch_world_market(market) for market in WORLD_MARKETS]


def _cached_verdict_signals(db, non_watchlist: list[dict]) -> dict[str, dict | None]:
    """Fetch the latest cached verdict per ticker (single query/decode pass).

    Returns a dict of ticker -> {"action", "confidence"} for tickers with a
    decodable cached verdict, or ticker -> None for tickers with no cache
    (or an undecodable one). Callers apply their own default for the None case.
    """
    from app.services.narrative_cache import NarrativeCache

    raw: dict[str, dict | None] = {}
    cache = NarrativeCache(db)
    action_by_code = {"a": "add", "h": "hold", "t": "trim", "n": "needs-data"}
    for h in non_watchlist:
        ticker = h["ticker"]
        cached = cache.latest_verdict(ticker)
        if cached:
            try:
                parts = str(cached.get("narrative_type") or "").split(":")
                raw[ticker] = {
                    "action": action_by_code.get(parts[1] if len(parts) > 1 else "", "hold"),
                    "confidence": 50,
                }
            except Exception:
                raw[ticker] = {"action": "hold", "confidence": 50}
        else:
            raw[ticker] = None
    return raw


def _signals_snapshot(
    db, non_watchlist: list[dict], cached_signals: dict[str, dict | None] | None = None
) -> dict[str, Any]:
    from app.services.portfolio_state import portfolio_state_signature

    if cached_signals is None:
        cached_signals = _cached_verdict_signals(db, non_watchlist)

    signals_dict: dict[str, dict] = {
        ticker: (sig if sig is not None else {"action": "needs-data", "confidence": 50})
        for ticker, sig in cached_signals.items()
    }

    alloc_map = {h["ticker"]: float(h.get("allocation_pct") or 0) for h in non_watchlist}
    state = portfolio_state_signature(signals_dict, alloc_map)

    buckets = {"add": 0.0, "hold": 0.0, "trim": 0.0}
    conf_weighted = 0.0
    weight_total = 0.0
    for ticker, sig in signals_dict.items():
        w = alloc_map.get(ticker, 0)
        if w <= 0:
            continue
        action = str(sig.get("action") or "hold").lower()
        if action in ("buy", "add"):
            bucket = "add"
        elif action in ("sell", "trim"):
            bucket = "trim"
        else:
            bucket = "hold"
        buckets[bucket] += w
        conf_weighted += float(sig.get("confidence") or 50) * w
        weight_total += w

    return {
        "has_data": weight_total > 0,
        "dominant_action": state.get("dominant_action", "hold"),
        "hold_weight_pct": round(buckets["hold"], 1),
        "add_weight_pct": round(buckets["add"], 1),
        "trim_weight_pct": round(buckets["trim"], 1),
        "avg_confidence": round(conf_weighted / weight_total) if weight_total else 0,
    }


def build_analytics_snapshot(db, portfolio_id: int = 1) -> dict[str, Any]:
    """Compact cross-tab snapshot for analytics insights."""
    from app.services import portfolio_valuation
    from app.services.portfolio_analytics import (
        compute_benchmark_comparison,
        compute_confidence_spectrum,
        compute_conviction_gaps,
        compute_drawdown,
        compute_macro_alignment,
        compute_market_context,
        compute_market_sensitivity,
        compute_portfolio_beta,
        compute_return_calendar,
        compute_risk_metrics,
        compute_rolling_volatility,
        compute_sector_tilt,
    )
    from app.services.portfolio_exposure import build_portfolio_exposure
    from app.services.stock_service import get_all_quotes

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    holdings_rows = valuation.holdings
    total_value = valuation.total_value
    total_daily_change = valuation.total_daily_change
    non_watchlist = [h for h in holdings_rows if not h.get("is_watchlist")]

    total_return_pct = valuation.total_return_pct
    prev_value = total_value - total_daily_change
    today_pnl_pct = (
        round(total_daily_change / prev_value * 100, 2) if abs(prev_value) > 0 else 0.0
    )

    history = portfolio_valuation.snapshot_history(db, portfolio_id)
    drawdown = compute_drawdown(history)
    risk = compute_risk_metrics(holdings_rows, total_value)
    quotes = get_all_quotes([h["ticker"] for h in non_watchlist])
    exposure = build_portfolio_exposure(
        [
            {
                "ticker": h["ticker"],
                "allocation_pct": h.get("allocation_pct"),
                "is_watchlist": h.get("is_watchlist"),
            }
            for h in non_watchlist
        ],
        quotes={q["ticker"]: q for q in quotes},
    )
    world = fetch_world_markets_sync()
    market_ctx = compute_market_context(holdings_rows, world)
    cached_signals = _cached_verdict_signals(db, non_watchlist)
    signals = _signals_snapshot(db, non_watchlist, cached_signals=cached_signals)

    signals_dict = {
        ticker: (sig if sig is not None else {"action": "hold", "confidence": 50})
        for ticker, sig in cached_signals.items()
    }

    benchmark = compute_benchmark_comparison(holdings_rows, history)
    return_cal = compute_return_calendar(history)
    beta = compute_portfolio_beta(holdings_rows)
    rolling_vol = compute_rolling_volatility(holdings_rows)
    sector_tilt = compute_sector_tilt(holdings_rows)
    conviction_gaps = compute_conviction_gaps(holdings_rows, signals_dict)
    confidence_spectrum = compute_confidence_spectrum(holdings_rows, signals_dict)
    market_sensitivity = compute_market_sensitivity(holdings_rows, world)
    macro_alignment = compute_macro_alignment(holdings_rows, world)

    sectors = exposure.get("sector_exposure") or []
    countries = exposure.get("country_exposure") or []
    best = market_ctx.get("best_match") or {}

    return {
        "as_of": today,
        "valuation": {
            "data_quality": valuation.data_quality,
            "missing_tickers": list(valuation.missing_tickers),
            "priced_position_count": valuation.priced_position_count,
            "expected_position_count": valuation.expected_position_count,
        },
        "performance": {
            "has_holdings": bool(non_watchlist) and total_value > 0,
            "total_return_pct": total_return_pct,
            "today_pnl_pct": today_pnl_pct,
            "history_days": len(history),
            "max_drawdown_pct": drawdown.get("max_drawdown_pct"),
        },
        "risk": {
            "has_data": risk.get("has_data"),
            "concentration_hhi": exposure.get("concentration_hhi"),
            "portfolio_vol_pct": (risk.get("portfolio") or {}).get("annual_vol_pct"),
            "max_drawdown_pct": drawdown.get("max_drawdown_pct"),
            "top_sector": sectors[0]["name"] if sectors else None,
        },
        "exposure": {
            "has_data": bool(sectors or countries),
            "top_sectors": sectors[:3],
            "top_countries": countries[:3],
        },
        "signals": signals,
        "markets": {
            "has_data": market_ctx.get("has_data"),
            "best_match_name": best.get("name"),
            "best_correlation": best.get("correlation"),
            "us_exposure_pct": market_ctx.get("us_exposure_pct"),
            "summary": market_ctx.get("summary"),
        },
        "widgets": {
            "benchmark": {
                "has_data": benchmark.get("has_data"),
                "ranges": benchmark.get("ranges"),
            },
            "return_calendar": {
                "has_data": return_cal.get("has_data"),
                "months": return_cal.get("months", [])[-6:],
            },
            "risk_reward": {
                "portfolio": risk.get("portfolio"),
                "benchmark": risk.get("benchmark"),
            },
            "beta": beta,
            "rolling_vol": {
                "has_data": rolling_vol.get("has_data"),
                "current_vol_pct": rolling_vol.get("current_vol_pct"),
            },
            "sector_tilt": {
                "has_data": sector_tilt.get("has_data"),
                "sectors": (sector_tilt.get("sectors") or [])[:4],
            },
            "conviction_gaps": {
                "has_data": conviction_gaps.get("has_data"),
                "gaps": (conviction_gaps.get("gaps") or [])[:3],
            },
            "confidence_spectrum": {
                "has_data": confidence_spectrum.get("has_data"),
                "dominant_band": confidence_spectrum.get("dominant_band"),
                "avg_confidence": confidence_spectrum.get("avg_confidence"),
            },
            "market_sensitivity": {
                "has_data": market_sensitivity.get("has_data"),
                "indices": (market_sensitivity.get("indices") or [])[:3],
                "portfolio_vol_pct": market_sensitivity.get("portfolio_vol_pct"),
            },
            "macro_alignment": {
                "has_data": macro_alignment.get("has_data"),
                "points": (macro_alignment.get("points") or [])[:5],
            },
        },
    }
