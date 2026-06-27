"""
app/routers/ai.py
AI-powered summary endpoints using Claude, plus move-explanation endpoints.
"""
# pylint: disable=too-many-lines
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AISummary, Holding, VerdictSnapshot
from app.services.ai_service import (
    MODEL,
    claude_api_heartbeat,
    generate_etf_profile_seed,
    generate_portfolio_briefing,
    generate_stock_summary,
    next_briefing_canned_quote,
)
from app.services.move_explainer import (
    HoldingMoveSummary,
    _day_change_pct_cached,
    compute_contribution_breakdown,
    explain_move,
    get_benchmark_data,
)
from app.services.holding_intelligence import (
    get_holding_intelligence,
    intelligence_to_dict,
)
from app.services.analyst_recommendation import (
    get_analyst_recommendation,
    rec_to_dict,
)
from app.services.stock_service import (
    DEFAULT_HOLDINGS,
    QUOTE_FETCH_ERROR,
    get_all_quotes,
    get_stock_data,
)
from app.services.investment_signal import (
    build_investment_signal,
    signal_to_dict,
)
from app.services.timing_signal import (
    build_timing_signal,
    get_batched_history_closes,
    get_cached_history_closes,
    timing_bucket,
)
from app.services.ai_service import fallback_quip, generate_verdict_ai_bundles
from app.services.verdict_scan_cache import attach_since_last_scan
from app.services.verdict_ai_enhancement import (
    apply_ai_enhancement,
    compact_signal_mix,
    decode_verdict_cache,
    encode_verdict_cache,
)
from app.services.portfolio_exposure import (
    build_portfolio_exposure,
    exposure_context_for_ticker,
)
from app.services.market_regime import get_market_regime
from app.services.peer_relative import compute_peer_relative
from app.services.event_calendar import build_event_context
from app.services.verdict_calibration import (
    calibration_footnote,
    calibration_summary,
    log_verdict_snapshot,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])

CACHE_TTL = timedelta(hours=24)
PRICE_DRIFT_THRESHOLD = 0.08  # stock summaries only; verdicts key off action + market mood
HAIKU_45_INPUT_USD_PER_MILLION = 1.00
HAIKU_45_OUTPUT_USD_PER_MILLION = 5.00
ESTIMATED_PROMPT_TOKENS_PER_SUMMARY = 210


def _is_number(value) -> bool:
    try:
        if value is None or value == "":
            return False
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _has_positive_number(data: dict, *keys: str) -> bool:
    return any(_is_number(data.get(key)) and float(data[key]) > 0 for key in keys)


def _has_number(data: dict, *keys: str) -> bool:
    return any(_is_number(data.get(key)) for key in keys)


def _market_pulse_status(intel_dict: dict) -> dict:
    """
    Report whether the metric boxes in the expanded holding UI have live values.
    The browser uses this to retry only the holdings that came back sparse.
    """
    missing: list[str] = []
    coverage_type = intel_dict.get("coverage_type") or ""

    if coverage_type == "equity":
        if not _has_positive_number(intel_dict, "market_cap", "enterprise_value"):
            missing.append("market_cap")
        if not _has_positive_number(
            intel_dict,
            "enterprise_to_revenue",
            "enterprise_to_ebitda",
            "forward_pe",
            "pe_ratio",
            "price_to_sales",
        ):
            missing.append("valuation")
        if not _has_number(
            intel_dict,
            "fcf_yield",
            "revenue_growth",
            "gross_margin",
            "operating_margin",
            "profit_margin",
            "dividend_yield",
        ):
            missing.append("quality")
    else:
        if not _has_number(intel_dict, "expense_ratio", "expense_ratio_bps"):
            missing.append("expense_ratio")
        if not _has_positive_number(intel_dict, "volume", "average_volume"):
            missing.append("volume")
        if not _has_number(intel_dict, "bid_ask_spread_pct"):
            missing.append("bid_ask_spread")

    return {"loaded": not missing, "missing": missing}


def _with_load_status(intel_dict: dict) -> dict:
    intel_dict["load_status"] = {
        "coverage": bool(intel_dict.get("strategy") and intel_dict.get("coverage_label")),
        "market_pulse": _market_pulse_status(intel_dict),
    }
    return intel_dict


def _attach_contributions_batch(intel_dicts: dict[str, dict]) -> None:
    """
    Batch-fetch day_change_pct for all unique holding tickers across ETF intel dicts,
    then attach contribution_breakdown to each dict that has top_holdings.

    Runs one concurrent ThreadPoolExecutor pass for all unique tickers to minimise
    total wall-clock time.  Falls back gracefully: individual fetch failures yield
    contribution_pp=0.0 for that holding; a complete timeout leaves the field None.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    unique: set[str] = set()
    for d in intel_dicts.values():
        if d.get("coverage_type") == "equity":
            continue
        for h in d.get("top_holdings") or []:
            unique.add(h["ticker"])

    preloaded: dict[str, float] = {}
    if unique:
        try:
            with ThreadPoolExecutor(max_workers=min(16, len(unique))) as pool:
                futures = {pool.submit(_day_change_pct_cached, t): t for t in unique}
                for future in as_completed(futures, timeout=8.0):
                    t = futures[future]
                    try:
                        preloaded[t] = future.result()
                    except Exception as exc:
                        logger.debug(
                            "Contribution preload failed; exception_type=%s",
                            type(exc).__name__,
                        )
                        preloaded[t] = 0.0
        except Exception as exc:
            logger.debug(
                "Contribution preload batch failed; exception_type=%s",
                type(exc).__name__,
            )

    for d in intel_dicts.values():
        top_holdings = d.get("top_holdings") or []
        if not top_holdings or d.get("coverage_type") == "equity":
            d["contribution_breakdown"] = None
            continue
        try:
            d["contribution_breakdown"] = compute_contribution_breakdown(
                top_holdings, preloaded_changes=preloaded
            )
        except Exception as exc:
            logger.debug(
                "Contribution breakdown failed; exception_type=%s",
                type(exc).__name__,
            )
            d["contribution_breakdown"] = None


def _estimate_text_tokens(text: str | None) -> int:
    """Approximate token count from persisted text when exact API usage is unavailable."""
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def _enrich_intelligence_dict(intel_dict: dict, stock_data: dict | None) -> dict:
    """Add live quote fields used by the dashboard's market pulse strip."""
    if not stock_data:
        return intel_dict

    expense_ratio = intel_dict.get("expense_ratio")
    if expense_ratio is None:
        expense_ratio = stock_data.get("expense_ratio")

    intel_dict.update(
        {
            "day_change_pct": stock_data.get("day_change_pct"),
            "volume": stock_data.get("volume"),
            "average_volume": stock_data.get("average_volume"),
            "expense_ratio": expense_ratio,
            "bid": stock_data.get("bid"),
            "ask": stock_data.get("ask"),
            "bid_ask_spread_pct": stock_data.get("bid_ask_spread_pct"),
            "market_cap": stock_data.get("market_cap"),
            "enterprise_value": stock_data.get("enterprise_value"),
            "total_revenue": stock_data.get("total_revenue"),
            "ebitda": stock_data.get("ebitda"),
            "free_cashflow": stock_data.get("free_cashflow"),
            "fcf_yield": stock_data.get("fcf_yield"),
            "pe_ratio": stock_data.get("pe_ratio"),
            "forward_pe": stock_data.get("forward_pe"),
            "price_to_sales": stock_data.get("price_to_sales"),
            "enterprise_to_revenue": stock_data.get("enterprise_to_revenue"),
            "enterprise_to_ebitda": stock_data.get("enterprise_to_ebitda"),
            "revenue_growth": stock_data.get("revenue_growth"),
            "gross_margin": stock_data.get("gross_margin"),
            "operating_margin": stock_data.get("operating_margin"),
            "profit_margin": stock_data.get("profit_margin"),
            "dividend_yield": stock_data.get("dividend_yield"),
            "aum": stock_data.get("aum"),
        }
    )
    return intel_dict


def _recent_add_count(db: Session, ticker: str, days: int = 30) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        db.query(VerdictSnapshot)
        .filter(
            VerdictSnapshot.ticker == ticker.upper(),
            VerdictSnapshot.action == "add",
            VerdictSnapshot.generated_at >= cutoff,
        )
        .count()
    )


def _user_context(meta: dict, quote_data: dict | None, db: Session, ticker: str) -> dict:
    quote = quote_data or {}
    return {
        "shares": meta.get("shares"),
        "avg_cost": meta.get("avg_cost"),
        "current_price": quote.get("current_price"),
        "recent_add_count": _recent_add_count(db, ticker),
    }


def _holdings_for_exposure(holding_meta: dict, alloc_map: dict) -> list[dict]:
    return [
        {
            "ticker": ticker,
            "allocation_pct": alloc_map.get(ticker, 0),
            "is_watchlist": meta.get("is_watchlist", False),
        }
        for ticker, meta in holding_meta.items()
    ]


def _active_portfolio_tickers(db: Session, portfolio_id: int = 1) -> list[str]:
    tickers = [
        row[0]
        for row in (
            db.query(Holding.ticker)
            .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
            .all()
        )
    ]
    return [str(t).upper() for t in tickers] or DEFAULT_HOLDINGS


def _cache_is_fresh(cached: AISummary, current_price: float | None = None) -> bool:
    # getattr gives pyright concrete Python types instead of SQLAlchemy ColumnElement
    generated_at: datetime = getattr(cached, "generated_at")
    cached_price: float | None = getattr(cached, "price_when_generated")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if now - generated_at > CACHE_TTL:
        return False
    if current_price is not None and cached_price is not None and cached_price > 0:
        drift = abs(current_price - cached_price) / cached_price
        if drift > PRICE_DRIFT_THRESHOLD:
            return False
    return True


@router.get("/cache/stats")
async def get_ai_cache_stats(db: Session = Depends(get_db)):
    """
    Return cached AI summary counts with an estimated Anthropic token cost.
    Local fallback/deterministic cache rows are excluded because they do not
    spend Claude tokens. AISummary rows do not persist exact token usage, so
    Claude-backed rows use a text-length estimate plus the prompt size used by
    generate_stock_summary.
    """
    summaries = db.query(AISummary).all()
    cached_count = len(summaries)
    claude_summaries = [
        summary for summary in summaries
        if (getattr(summary, "model_used", "") or "").lower() not in {"fallback", "deterministic"}
    ]
    fallback_count = cached_count - len(claude_summaries)
    estimated_output_tokens = sum(
        _estimate_text_tokens(getattr(summary, "summary_text", ""))
        for summary in claude_summaries
    )
    estimated_input_tokens = len(claude_summaries) * ESTIMATED_PROMPT_TOKENS_PER_SUMMARY
    estimated_cost_usd = (
        estimated_input_tokens / 1_000_000 * HAIKU_45_INPUT_USD_PER_MILLION
        + estimated_output_tokens / 1_000_000 * HAIKU_45_OUTPUT_USD_PER_MILLION
    )
    claude_configured = bool(settings.ANTHROPIC_API_KEY.strip())

    return {
        "model": MODEL,
        "cached_summaries": cached_count,
        "claude_cached_summaries": len(claude_summaries),
        "local_cached_summaries": fallback_count,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_total_tokens": estimated_input_tokens + estimated_output_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "pricing": {
            "input_usd_per_million_tokens": HAIKU_45_INPUT_USD_PER_MILLION,
            "output_usd_per_million_tokens": HAIKU_45_OUTPUT_USD_PER_MILLION,
        },
        "claude_configured": claude_configured,
        "billing_active": claude_configured,
        "is_estimate": True,
        "note": (
            "Claude API billing is paused; local fallback cache rows are free."
            if not claude_configured
            else (
                "Estimated from Claude-backed cached summaries; exact Anthropic "
                "token usage is not stored."
            )
        ),
    }


@router.get("/heartbeat")
async def get_claude_heartbeat():
    """Return a lightweight Claude API reachability check for the dashboard HUD."""
    return {
        **claude_api_heartbeat(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
    }


@router.get("/summary/{ticker}")
async def get_stock_summary(
    ticker: str,
    force_refresh: bool = False,
    db: Session = Depends(get_db),
):
    """
    Get AI summary for a single ticker.
    Checks the database cache first — only calls Claude if needed.
    Cache expires after 24 hours. Use force_refresh=true to bypass.
    """
    ticker = ticker.upper()

    if not force_refresh:
        cached = (
            db.query(AISummary)
            .filter(AISummary.ticker == ticker, AISummary.summary_type == "stock")
            .order_by(AISummary.generated_at.desc())
            .first()
        )
        if cached and _cache_is_fresh(cached):
            return {
                "ticker": ticker,
                "summary": cached.summary_text,
                "generated_at": cached.generated_at.isoformat(),
                "from_cache": True,
                "price_when_generated": cached.price_when_generated,
            }

    stock_data = get_stock_data(ticker)
    if stock_data.get("error"):
        raise HTTPException(status_code=404, detail=QUOTE_FETCH_ERROR)

    summary_text = generate_stock_summary(stock_data)

    summary = AISummary(
        ticker=ticker,
        summary_type="stock",
        summary_text=summary_text,
        price_when_generated=stock_data["current_price"],
        model_used=MODEL,
    )
    db.add(summary)
    db.commit()

    return {
        "ticker": ticker,
        "summary": summary_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "from_cache": False,
        "price_when_generated": stock_data["current_price"],
    }


@router.get("/summaries/all")
async def get_all_summaries(db: Session = Depends(get_db)):
    """
    Get or generate AI summaries for all active portfolio holdings.
    Returns cached summaries immediately, generates new ones for missing or stale tickers.
    This endpoint may take 30-60 seconds if generating all summaries fresh.
    """
    results = {}

    active_tickers = _active_portfolio_tickers(db)
    quotes = {q["ticker"]: q for q in get_all_quotes(active_tickers)}

    for ticker in active_tickers:
        current_price = quotes.get(ticker, {}).get("current_price")

        cached = (
            db.query(AISummary)
            .filter(AISummary.ticker == ticker, AISummary.summary_type == "stock")
            .order_by(AISummary.generated_at.desc())
            .first()
        )

        if cached and _cache_is_fresh(cached, current_price=current_price):
            results[ticker] = {"summary": cached.summary_text, "from_cache": True}
            continue

        stock_data = quotes.get(ticker, {})
        if stock_data and not stock_data.get("error"):
            summary_text = generate_stock_summary(stock_data)
            new_summary = AISummary(
                ticker=ticker,
                summary_type="stock",
                summary_text=summary_text,
                price_when_generated=stock_data.get("current_price"),
                model_used=MODEL,
            )
            db.add(new_summary)
            db.commit()
            results[ticker] = {"summary": summary_text, "from_cache": False}

    return {"summaries": results, "count": len(results)}


# ── Move explanation helpers ───────────────────────────────────────────────

def _summary_to_dict(s: HoldingMoveSummary) -> dict:
    """Serialize HoldingMoveSummary dataclass to a JSON-safe dict."""
    return {
        "ticker": s.ticker,
        "day_change_pct": s.day_change_pct,
        "day_change_dollar": s.day_change_dollar,
        "attribution_type": s.attribution_type,
        "confidence": s.confidence,
        "explanation_text": s.explanation_text,
        "is_etf": s.is_etf,
        "volume_vs_avg": s.volume_vs_avg,
        "drivers": [
            {
                "driver_type": d.driver_type,
                "description": d.description,
                "magnitude": d.magnitude,
                "icon": d.icon,
                "evidence_url": d.evidence_url,
            }
            for d in s.drivers
        ],
        "filings": [
            {
                "filing_type": f.filing_type,
                "title": f.title,
                "url": f.url,
                "filed_at": f.filed_at,
            }
            for f in s.filings
        ],
        "macro_context": (
            {
                "spy_change_pct": s.macro_context.spy_change_pct,
                "qqq_change_pct": s.macro_context.qqq_change_pct,
                "sector_etf": s.macro_context.sector_etf,
                "sector_etf_change_pct": s.macro_context.sector_etf_change_pct,
                "primary_benchmark": s.macro_context.primary_benchmark,
                "primary_benchmark_label": s.macro_context.primary_benchmark_label,
                "primary_benchmark_chg": s.macro_context.primary_benchmark_chg,
                "suppress_spy": s.macro_context.suppress_spy,
                "suppress_qqq": s.macro_context.suppress_qqq,
            }
            if s.macro_context
            else None
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


_UNCLEAR_RESULT = {
    "attribution_type": "unclear",
    "confidence": "Low",
    "explanation_text": "Move explanation temporarily unavailable.",
    "drivers": [],
    "filings": [],
    "macro_context": None,
    "volume_vs_avg": None,
    "is_etf": False,
}


# ── Move explanation endpoints ─────────────────────────────────────────────

@router.get("/move-explanation/{ticker}")
async def get_move_explanation(ticker: str):
    """
    Explain why a ticker moved today.
    Returns market context, attribution type, and likely drivers.
    Not cached — prices and benchmark context change throughout the day.
    """
    ticker = ticker.upper()
    stock_data = get_stock_data(ticker)
    if stock_data.get("error"):
        raise HTTPException(status_code=404, detail=QUOTE_FETCH_ERROR)

    summary = explain_move(stock_data)
    return _summary_to_dict(summary)


@router.get("/move-explanations/all")
async def get_all_move_explanations(db: Session = Depends(get_db)):
    """
    Explain today's move for all portfolio holdings.
    Fetches SPY/QQQ benchmark data once, then processes each holding in turn.
    Per-holding primary benchmarks (BTC, EEM, XAR…) are fetched lazily and
    cached in a shared dict to avoid duplicate API calls.
    """
    benchmarks = get_benchmark_data()
    benchmark_cache: dict = {}  # shared cache for per-holding primary benchmarks
    quotes = {q["ticker"]: q for q in get_all_quotes(_active_portfolio_tickers(db))}
    results: dict[str, dict] = {}

    for ticker, stock_data in quotes.items():
        if stock_data.get("error"):
            results[ticker] = {**_UNCLEAR_RESULT, "ticker": ticker}
            continue
        try:
            summary = explain_move(
                stock_data,
                shared_benchmarks=benchmarks,
                _benchmark_cache=benchmark_cache,
            )
            results[ticker] = _summary_to_dict(summary)
        except Exception as exc:
            logger.error(
                "Move explanation failed; exception_type=%s",
                type(exc).__name__,
            )
            results[ticker] = {**_UNCLEAR_RESULT, "ticker": ticker}

    return {"explanations": results, "count": len(results)}


# ── Holding Intelligence endpoints ────────────────────────────────────────────

@router.get("/intelligence/{ticker}")
async def get_holding_intelligence_single(ticker: str, ai_holdings_fallback: bool = False):
    """
    Return structured intelligence for a single holding:
    what it covers (sectors, countries, top holdings, strategy, benchmarks).
    """
    ticker = ticker.upper()
    stock_data = get_stock_data(ticker)
    if stock_data.get("error"):
        raise HTTPException(status_code=404, detail=QUOTE_FETCH_ERROR)
    intel = get_holding_intelligence(ticker, stock_data)
    intel_dict = _enrich_intelligence_dict(intelligence_to_dict(intel), stock_data)
    if (
        ai_holdings_fallback
        and intel_dict.get("coverage_type") != "equity"
        and (not intel_dict.get("top_holdings") or not intel_dict.get("aum"))
    ):
        ai_profile = generate_etf_profile_seed(ticker, stock_data.get("name"))
        ai_holdings = ai_profile.get("holdings") or []
        ai_aum = ai_profile.get("aum")
        if ai_holdings:
            intel_dict["top_holdings"] = ai_holdings
            intel_dict["data_quality"] = "partial"
            intel_dict["holdings_estimated"] = True
        if ai_aum and not intel_dict.get("aum"):
            intel_dict["aum"] = ai_aum
            intel_dict["aum_estimated"] = True
        if ai_holdings or ai_aum:
            sources = list(intel_dict.get("data_sources") or [])
            if "claude_estimate" not in sources:
                sources.append("claude_estimate")
            intel_dict["data_sources"] = sources

    top_holdings = intel_dict.get("top_holdings") or []
    if top_holdings and intel_dict.get("coverage_type") != "equity":
        try:
            intel_dict["contribution_breakdown"] = compute_contribution_breakdown(top_holdings)
        except Exception as exc:
            logger.debug(
                "Contribution breakdown failed; exception_type=%s",
                type(exc).__name__,
            )
            intel_dict["contribution_breakdown"] = None
    else:
        intel_dict["contribution_breakdown"] = None
    return _with_load_status(intel_dict)


_FALLBACK_INTEL_BASE = {
    "coverage_type": "equity", "coverage_label": "Unknown",
    "strategy": "Data unavailable", "asset_class": "equities", "theme": None,
    "sectors": [], "countries": [], "top_holdings": [],
    "benchmark_tickers": ["SPY"], "benchmark_labels": {"SPY": "S&P 500"},
    "peer_tickers": [], "key_drivers": [], "concentration_level": "medium",
    "concentration_label": "", "expense_ratio": None, "expense_ratio_bps": None,
    "day_change_pct": None, "volume": None, "average_volume": None,
    "bid": None, "ask": None, "bid_ask_spread_pct": None,
    "market_cap": None, "enterprise_value": None, "total_revenue": None,
    "ebitda": None, "free_cashflow": None, "fcf_yield": None,
    "pe_ratio": None, "forward_pe": None, "price_to_sales": None,
    "enterprise_to_revenue": None, "enterprise_to_ebitda": None,
    "revenue_growth": None, "gross_margin": None, "operating_margin": None,
    "profit_margin": None, "dividend_yield": None, "aum": None,
    "data_quality": "static", "data_sources": [],
}


@router.get("/intelligence/all/batch")
async def get_all_intelligence(db: Session = Depends(get_db)):
    """
    Return holding intelligence for all portfolio holdings.
    Combines structured coverage data (sectors, countries, benchmarks) for every holding.
    """
    active_tickers = _active_portfolio_tickers(db)
    quotes = {q["ticker"]: q for q in get_all_quotes(active_tickers)}

    # Phase 1: build all intel dicts (existing behaviour)
    intel_dicts: dict[str, dict] = {}
    for ticker in active_tickers:
        stock_data = quotes.get(ticker) or {"ticker": ticker, "error": "Missing quote"}
        try:
            intel = get_holding_intelligence(
                ticker, stock_data if not stock_data.get("error") else None
            )
            intel_dicts[ticker] = _enrich_intelligence_dict(
                intelligence_to_dict(intel),
                stock_data if not stock_data.get("error") else None,
            )
        except Exception as exc:
            logger.error(
                "Intelligence fetch failed; exception_type=%s",
                type(exc).__name__,
            )
            intel_dicts[ticker] = {"ticker": ticker, **_FALLBACK_INTEL_BASE}

    # Phase 2: batch-fetch holding prices and attach contribution breakdowns
    try:
        _attach_contributions_batch(intel_dicts)
    except Exception as exc:
        logger.warning(
            "Contribution batch failed, skipping; exception_type=%s",
            type(exc).__name__,
        )
        for d in intel_dicts.values():
            d.setdefault("contribution_breakdown", None)

    results = {ticker: _with_load_status(d) for ticker, d in intel_dicts.items()}

    incomplete_tickers = [
        ticker for ticker in active_tickers
        if not results.get(ticker, {}).get("load_status", {}).get("market_pulse", {}).get("loaded")
    ]
    return {
        "intelligence": results,
        "count": len(results),
        "expected_count": len(active_tickers),
        "complete": not incomplete_tickers and len(results) == len(active_tickers),
        "incomplete_tickers": incomplete_tickers,
    }


# ── Analyst Recommendation endpoints ─────────────────────────────────────────

VERDICT_BRAND_KICKER = "FolioSense \u00d7 Claude"
VERDICT_BRAND_KICKER_LOCAL = "FolioSense Intelligence"
VERDICT_FEELS_PREFIX = "FolioSense feels"
_VERDICT_DISCLAIMER = (
    "FolioSense Intelligence \u2014 a signal read, not "
    "financial advice. Verify before you trade."
)
_AI_VERDICT_DISCLAIMER = _VERDICT_DISCLAIMER
_PORTFOLIO_CACHE_TICKER = "BOOK"
_ACTION_CACHE_CODE = {"add": "a", "hold": "h", "trim": "t", "needs-data": "n"}
_MOOD_CACHE_CODE = {
    "hot": "hot", "warm": "warm", "neutral": "neut", "cooling": "cool", "cold": "cold"
}
_HOLD_CLASS_CACHE_CODE = {"auto": "auto", "anchor": "anch", "trade": "trd", "core": "core"}

VERDICT_BRAND_COPY = {
    "kicker": VERDICT_BRAND_KICKER,
    "feels_prefix": VERDICT_FEELS_PREFIX,
}

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


def _holding_meta(db: Session, portfolio_id: int = 1) -> dict[str, dict]:
    """Return ticker → holding context for active holdings."""
    rows = (
        db.query(
            Holding.ticker,
            Holding.shares,
            Holding.avg_cost,
            Holding.is_watchlist,
            Holding.hold_class,
        )
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .all()
    )
    return {
        str(r[0]).upper(): {
            "shares": float(r[1] or 0),
            "avg_cost": float(r[2] or 0),
            "is_watchlist": bool(r[3]),
            "hold_class": str(r[4] or "auto"),
        }
        for r in rows
    }


def _compute_allocation_pcts(holding_meta: dict, quotes: dict) -> dict[str, float]:
    """Compute allocation_pct for every non-watchlist holding."""
    total_value = sum(
        meta["shares"] * (quotes.get(ticker, {}).get("current_price") or 0)
        for ticker, meta in holding_meta.items()
        if not meta["is_watchlist"]
    )
    if total_value <= 0:
        return {}
    result: dict[str, float] = {}
    for ticker, meta in holding_meta.items():
        if meta["is_watchlist"]:
            continue
        price = (quotes.get(ticker, {}).get("current_price") or 0)
        value = meta["shares"] * price
        result[ticker] = round(value / total_value * 100, 1)
    return result


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


def _portfolio_state_signature(signals: dict[str, dict], alloc_map: dict[str, float]) -> dict:
    """Coarse portfolio-state cache key: dominant action mix + concentration band."""
    counts = {"add": 0, "hold": 0, "trim": 0, "needs-data": 0}
    for sig in signals.values():
        action = sig.get("action", "needs-data")
        counts[action if action in counts else "needs-data"] += 1

    dominant_action = max(
        counts,
        key=lambda action: (
            counts[action],
            {"hold": 3, "add": 2, "trim": 1, "needs-data": 0}[action],
        ),
    )
    max_alloc = max(alloc_map.values(), default=0)
    if max_alloc >= 25:
        concentration_band = "high"
    elif max_alloc >= 12:
        concentration_band = "medium"
    else:
        concentration_band = "low"

    return {
        "dominant_action": dominant_action,
        "concentration_band": concentration_band,
        "summary_type": (
            f"vp:{_ACTION_CACHE_CODE.get(dominant_action, 'n')}:{concentration_band}"
        ),
        "reason": (
            f"Action mix add={counts['add']}, hold={counts['hold']}, "
            f"trim={counts['trim']}; concentration {concentration_band}"
        ),
    }


def _portfolio_fallback_quip(dominant_action: str, concentration_band: str) -> str:
    if concentration_band == "high":
        return (
            "Claude sees the book leaning concentrated; "
            "FolioSense is politely raising one eyebrow."
        )
    if dominant_action == "add":
        return (
            "FolioSense sees more green lights than red flags, "
            "with Claude keeping the caveats close."
        )
    if dominant_action == "trim":
        return (
            "Claude thinks the portfolio has had a run; "
            "FolioSense is checking the exits calmly."
        )
    if dominant_action == "needs-data":
        return (
            "FolioSense wants more receipts before turning this portfolio read into a headline."
        )
    return (
        "Claude calls the portfolio balanced enough to be interesting, "
        "not boring enough to ignore."
    )


def _brand_payload(*, ai_mode: bool = False) -> dict:
    return {
        "kicker": VERDICT_BRAND_KICKER if ai_mode else VERDICT_BRAND_KICKER_LOCAL,
        "feels_prefix": VERDICT_FEELS_PREFIX,
        "disclaimer": _AI_VERDICT_DISCLAIMER if ai_mode else _VERDICT_DISCLAIMER,
    }


def _hydrate_cached_verdict(sig_dict: dict, cached_text: str | None) -> bool:
    """Apply cached quip + AI bundle to sig_dict. Returns True when AI layer present."""
    decoded = decode_verdict_cache(cached_text)
    quip = decoded.get("quip") or ""
    if quip:
        sig_dict["quip"] = quip
    ai_raw = decoded.get("ai")
    if ai_raw and sig_dict.get("action") != "needs-data":
        apply_ai_enhancement(sig_dict, ai_raw)
        return True
    return False


@router.get("/investment-signal/{ticker}")
async def get_investment_signal_single(ticker: str, db: Session = Depends(get_db)):
    """
    Return deterministic investment signal + quip for a single ticker.
    """
    ticker = ticker.upper()
    meta = _holding_meta(db)
    holding = meta.get(ticker, {})
    is_watchlist = holding.get("is_watchlist", False)
    hold_class = holding.get("hold_class", "auto")

    # Allocation pct needs portfolio total — fetch quote for this ticker only
    allocation_pct: float | None = None
    quote_data = get_stock_data(ticker)
    if not quote_data.get("error"):
        all_tickers = list(meta.keys())
        quotes = {q["ticker"]: q for q in get_all_quotes(all_tickers)}
        alloc_map = _compute_allocation_pcts(meta, quotes)
        allocation_pct = alloc_map.get(ticker)

    closes = get_cached_history_closes(ticker)
    timing = _timing_for_quote(
        quote_data if not quote_data.get("error") else None,
        closes,
    )
    rec = get_analyst_recommendation(ticker, closes=closes)
    regime = get_market_regime()
    peer = compute_peer_relative(
        ticker,
        stock_data=quote_data if not quote_data.get("error") else None,
        closes=closes,
    )
    event_ctx = build_event_context(
        ticker,
        security_type=rec.security_type,
    )
    sig = build_investment_signal(
        rec,
        allocation_pct=allocation_pct,
        is_watchlist=is_watchlist,
        stock_data=quote_data if not quote_data.get("error") else None,
        hold_class=hold_class,
        timing=timing,
        regime=regime,
        peer_relative=peer,
        event_context=event_ctx,
        user_context=_user_context(holding, quote_data, db, ticker),
    )
    sig_dict = signal_to_dict(sig)
    scan_snapshot_changed = attach_since_last_scan(db, ticker, sig_dict)

    quip = fallback_quip(sig.action)
    sig_dict["quip"] = quip
    sig_dict["disclaimer"] = _VERDICT_DISCLAIMER
    sig_dict["brand"] = _brand_payload()
    if scan_snapshot_changed:
        db.commit()
    return sig_dict


@router.get("/investment-signals/all")
async def get_all_investment_signals(  # pylint: disable=too-many-statements,too-many-branches
    db: Session = Depends(get_db),
    force_local: bool = False,
):
    """
    Return investment signals for all active portfolio holdings.
    Deterministic signals are computed fresh; quips are cached 24h in AISummary
    (summary_type='verdict') with price-drift invalidation.
    Pass force_local=true to skip Claude quip generation and use deterministic fallbacks.
    """
    active_tickers = _active_portfolio_tickers(db)
    holding_meta = _holding_meta(db)
    quotes = {q["ticker"]: q for q in get_all_quotes(active_tickers)}
    history_map = get_batched_history_closes(active_tickers)
    alloc_map = _compute_allocation_pcts(holding_meta, quotes)

    portfolio_exposure = build_portfolio_exposure(
        _holdings_for_exposure(holding_meta, alloc_map),
        quotes=quotes,
    )
    regime = get_market_regime()

    signals: dict[str, dict] = {}
    missing_quip_tickers: list[str] = []
    scan_snapshot_changed = False

    for ticker in active_tickers:
        try:
            meta = holding_meta.get(ticker, {})
            is_watchlist = meta.get("is_watchlist", False)
            hold_class = meta.get("hold_class", "auto")
            allocation_pct = alloc_map.get(ticker)

            quote_data = quotes.get(ticker) or {}
            closes = history_map.get(ticker, [])
            timing = _timing_for_quote(
                quote_data if not quote_data.get("error") else None,
                closes,
            )
            rec = get_analyst_recommendation(ticker, closes=closes)
            peer = compute_peer_relative(
                ticker,
                own_percentile=(rec.price_signal or {}).get("percentile"),
                zone=(rec.price_signal or {}).get("priceZoneLabel"),
                stock_data=quote_data if not quote_data.get("error") else None,
                closes=closes,
            )
            event_ctx = build_event_context(
                ticker,
                security_type=rec.security_type,
            )
            exp_ctx = exposure_context_for_ticker(portfolio_exposure, ticker)
            sig = build_investment_signal(
                rec,
                allocation_pct=allocation_pct,
                is_watchlist=is_watchlist,
                stock_data=quote_data if not quote_data.get("error") else None,
                hold_class=hold_class,
                timing=timing,
                regime=regime,
                peer_relative=peer,
                exposure_context=exp_ctx,
                event_context=event_ctx,
                user_context=_user_context(meta, quote_data, db, ticker),
            )
            sig_dict = signal_to_dict(sig)
            footnote = calibration_footnote(
                db, action=sig.action, confidence=sig.confidence,
            )
            if footnote:
                sig_dict["calibration_footnote"] = footnote
            log_verdict_snapshot(
                db,
                ticker=ticker,
                action=sig.action,
                confidence=sig.confidence,
                local_score=sig.confidence,
                ai_score=None,
                price_at_scan=quote_data.get("current_price"),
                hold_class=hold_class,
            )
            scan_snapshot_changed = (
                attach_since_last_scan(db, ticker, sig_dict) or scan_snapshot_changed
            )
            sig_dict["disclaimer"] = _VERDICT_DISCLAIMER
            sig_dict["brand"] = _brand_payload()

            # Check cache for quip + AI bundle
            summary_type = _verdict_summary_type(
                sig_dict.get("action", "needs-data"),
                sig_dict.get("market_mood", "neutral"),
                sig_dict.get("hold_class", "auto"),
                timing_bucket(sig_dict.get("timing")),
            )
            cached = (
                db.query(AISummary)
                .filter(AISummary.ticker == ticker, AISummary.summary_type == summary_type)
                .order_by(AISummary.generated_at.desc())
                .first()
            )
            if cached and _cache_is_fresh(cached):
                sig_dict["ai_enhanced"] = _hydrate_cached_verdict(
                    sig_dict,
                    getattr(cached, "summary_text", ""),
                )
            else:
                sig_dict["quip"] = None  # will be filled by batch call
                missing_quip_tickers.append(ticker)

            signals[ticker] = sig_dict

        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "Investment signal failed for %s; exception_type=%s",
                ticker, type(exc).__name__,
            )
            signals[ticker] = {
                **_NEEDS_DATA_SIGNAL,
                "ticker": ticker,
                "quip": fallback_quip("needs-data"),
                "disclaimer": _VERDICT_DISCLAIMER,
                "brand": _brand_payload(),
                "generated_at": "",
            }

    portfolio_state = _portfolio_state_signature(signals, alloc_map)
    portfolio_cached = (
        db.query(AISummary)
        .filter(
            AISummary.ticker == _PORTFOLIO_CACHE_TICKER,
            AISummary.summary_type == portfolio_state["summary_type"],
        )
        .order_by(AISummary.generated_at.desc())
        .first()
    )
    portfolio_quip: str | None = None
    include_portfolio_quip = False
    if portfolio_cached and _cache_is_fresh(portfolio_cached):
        portfolio_quip = getattr(portfolio_cached, "summary_text", "")
    else:
        include_portfolio_quip = True

    # Batch-generate quips for stale/missing tickers
    if force_local:
        for ticker in missing_quip_tickers:
            signals[ticker]["quip"] = fallback_quip(signals[ticker].get("action", "needs-data"))
            signals[ticker]["ai_enhanced"] = False
        if include_portfolio_quip:
            portfolio_quip = _portfolio_fallback_quip(
                portfolio_state["dominant_action"],
                portfolio_state["concentration_band"],
            )
        missing_quip_tickers = []
        include_portfolio_quip = False

    claude_live: bool | None = None
    if missing_quip_tickers or include_portfolio_quip:
        quip_inputs = [
            {
                "ticker": t,
                "action": signals[t].get("action", "needs-data"),
                "confidence": signals[t].get("confidence", 0),
                "market_mood": signals[t].get("market_mood", "neutral"),
                "reason": (signals[t].get("reasons") or [""])[0],
                "mix": compact_signal_mix(signals[t].get("signal_mix")),
            }
            for t in missing_quip_tickers
        ]
        if include_portfolio_quip:
            quip_inputs.append(
                {
                    "ticker": _PORTFOLIO_CACHE_TICKER,
                    "action": portfolio_state["dominant_action"],
                    "confidence": 60,
                    "market_mood": "neutral",
                    "reason": portfolio_state["reason"],
                    "mix": "",
                }
            )
        new_bundles = generate_verdict_ai_bundles(quip_inputs)
        claude_live = bool(new_bundles)

        for ticker in missing_quip_tickers:
            fallback_action = signals[ticker].get("action", "needs-data")
            bundle = new_bundles.get(ticker) or {}
            quip = bundle.get("quip") or fallback_quip(fallback_action)
            signals[ticker]["quip"] = quip
            ai_raw = bundle.get("ai")
            if ai_raw and claude_live:
                apply_ai_enhancement(signals[ticker], ai_raw)
                signals[ticker]["ai_enhanced"] = True
            else:
                signals[ticker]["ai_enhanced"] = False

            # Persist to cache
            current_price = (quotes.get(ticker) or {}).get("current_price")
            summary_type = _verdict_summary_type(
                signals[ticker].get("action", "needs-data"),
                signals[ticker].get("market_mood", "neutral"),
                signals[ticker].get("hold_class", "auto"),
                timing_bucket(signals[ticker].get("timing")),
            )
            try:
                db.add(AISummary(
                    ticker=ticker,
                    summary_type=summary_type,
                    summary_text=encode_verdict_cache(quip, ai_raw if claude_live else None),
                    price_when_generated=current_price,
                    model_used=MODEL if bundle.get("quip") and claude_live else "fallback",
                ))
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug(
                    "Failed to cache quip for %s; exception_type=%s",
                    ticker, type(exc).__name__,
                )
        if include_portfolio_quip:
            book_bundle = new_bundles.get(_PORTFOLIO_CACHE_TICKER) or {}
            portfolio_quip = book_bundle.get("quip") or _portfolio_fallback_quip(
                portfolio_state["dominant_action"],
                portfolio_state["concentration_band"],
            )
            try:
                db.add(AISummary(
                    ticker=_PORTFOLIO_CACHE_TICKER,
                    summary_type=portfolio_state["summary_type"],
                    summary_text=encode_verdict_cache(portfolio_quip, None),
                    price_when_generated=None,
                    model_used=MODEL if book_bundle.get("quip") and claude_live else "fallback",
                ))
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug(
                    "Failed to cache portfolio quip; exception_type=%s",
                    type(exc).__name__,
                )
        db.commit()
    elif scan_snapshot_changed:
        db.commit()

    if force_local:
        local_brand = _brand_payload(ai_mode=False)
        for sig in signals.values():
            sig["brand"] = local_brand
            sig["disclaimer"] = _VERDICT_DISCLAIMER
    elif claude_live:
        ai_brand = _brand_payload(ai_mode=True)
        for sig in signals.values():
            sig["brand"] = ai_brand
            sig["disclaimer"] = _AI_VERDICT_DISCLAIMER
    else:
        any_ai = any(sig.get("ai_enhanced") for sig in signals.values())
        if any_ai:
            ai_brand = _brand_payload(ai_mode=True)
            for sig in signals.values():
                if sig.get("ai_enhanced"):
                    sig["brand"] = ai_brand
                    sig["disclaimer"] = _AI_VERDICT_DISCLAIMER

    portfolio_health = {
        "quip": portfolio_quip or _portfolio_fallback_quip(
            portfolio_state["dominant_action"],
            portfolio_state["concentration_band"],
        ),
        "dominant_action": portfolio_state["dominant_action"],
        "concentration_band": portfolio_state["concentration_band"],
        "signature": portfolio_state["summary_type"],
        "brand": _brand_payload(ai_mode=bool(claude_live) and not force_local),
        "disclaimer": (
            _VERDICT_DISCLAIMER
            if force_local
            else (_AI_VERDICT_DISCLAIMER if claude_live else _VERDICT_DISCLAIMER)
        ),
    }

    return {
        "signals": signals,
        "count": len(signals),
        "portfolio_exposure": portfolio_exposure,
        "portfolio_health": portfolio_health,
        "calibration_summary": calibration_summary(db),
        "regime": regime,
        "claude_live": claude_live,
    }


@router.get("/portfolio-exposure")
async def get_portfolio_exposure(db: Session = Depends(get_db)):
    """Look-through sector, country, and theme exposure for the active portfolio."""
    holding_meta = _holding_meta(db)
    tickers = list(holding_meta.keys())
    quotes = {q["ticker"]: q for q in get_all_quotes(tickers)}
    alloc_map = _compute_allocation_pcts(holding_meta, quotes)
    exposure = build_portfolio_exposure(
        _holdings_for_exposure(holding_meta, alloc_map),
        quotes=quotes,
    )
    return exposure


@router.get("/verdict-calibration")
async def get_verdict_calibration(db: Session = Depends(get_db)):
    """Lightweight calibration buckets from logged verdict snapshots."""
    return calibration_summary(db)


@router.get("/intelligence/{ticker}/deep")
async def get_holding_intelligence_deep(ticker: str):
    """
    Tier-2 intelligence fetch — richer data for expanded holding panel.
    Does not block initial verdict render; called async on expand.
    """
    ticker = ticker.upper()
    stock_data = get_stock_data(ticker)
    if stock_data.get("error"):
        raise HTTPException(status_code=404, detail=QUOTE_FETCH_ERROR)

    intel = get_holding_intelligence(ticker, stock_data)
    intel_dict = _enrich_intelligence_dict(intelligence_to_dict(intel), stock_data)

    closes = get_cached_history_closes(ticker)
    peer = compute_peer_relative(
        ticker,
        stock_data=stock_data,
        closes=closes,
    )

    deep: dict = {
        "ticker": ticker,
        "peer_relative": peer,
        "revenue_growth": stock_data.get("revenue_growth"),
        "earnings_growth": stock_data.get("earnings_growth"),
        "eps_trailing": stock_data.get("eps_trailing"),
        "eps_forward": stock_data.get("eps_forward"),
    }

    if intel_dict.get("coverage_type") != "equity":
        from app.services.holding_intelligence import _try_yfinance_enrichment
        live_s, live_c, live_h = _try_yfinance_enrichment(ticker)
        if live_h:
            deep["top_holdings_fresh"] = [
                {"ticker": h.ticker, "name": h.name, "weight": h.weight}
                for h in live_h[:15]
            ]
        if live_s:
            deep["sectors_fresh"] = [{"name": s.name, "weight": s.weight} for s in live_s[:8]]

    event_ctx = build_event_context(
        ticker,
        security_type="ETF" if intel.coverage_type.startswith("etf") else "STOCK",
    )
    if event_ctx:
        deep["events"] = event_ctx

    return {"deep": deep, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/analyst-recommendation/{ticker}")
async def get_analyst_recommendation_single(ticker: str):
    """
    Return analyst consensus for a single ticker.
    ETFs return ETF quality instead of a stock analyst rating.
    """
    ticker = ticker.upper()
    rec = get_analyst_recommendation(ticker)
    return rec_to_dict(rec)


@router.get("/analyst-recommendations/all")
async def get_all_analyst_recommendations(db: Session = Depends(get_db)):
    """
    Return analyst consensus for all portfolio holdings.
    Iterates active portfolio holdings; ETFs resolve to ETF quality.
    """
    results: dict[str, dict] = {}
    for ticker in _active_portfolio_tickers(db):
        try:
            rec = get_analyst_recommendation(ticker)
            results[ticker] = rec_to_dict(rec)
        except Exception as exc:
            logger.error(
                "Analyst rec failed; exception_type=%s",
                type(exc).__name__,
            )
            results[ticker] = {
                "ticker": ticker,
                "action": "unavailable",
                "label": "Unavailable",
                "analyst_count": None,
                "recommendation_mean": None,
                "target_price": None,
                "target_upside_pct": None,
                "fcf_yield": None,
                "subtext": "Analyst rating unavailable",
                "source": "yfinance",
                "security_type": "UNKNOWN",
                "rating_type": "analyst",
                "etf_quality": None,
                "price_signal": None,
            }
    return {"recommendations": results, "count": len(results)}


# ── Portfolio Briefing endpoint ───────────────────────────────────────────────

_BRIEFING_CACHE_TYPE = "briefing"


def _briefing_snapshot(db: Session) -> tuple[dict, list[dict]]:
    """
    Build the compact portfolio snapshot fed to Haiku (and used for the local
    briefing lead line).  Returns (snapshot_dict, non_watchlist_holdings).
    """
    from app.routers.portfolio import _compute_portfolio, _cumulative_realized  # lazy — no circular dep

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    holdings_rows, total_value, total_daily_change, total_cost_basis = _compute_portfolio(1, db)
    non_watchlist = [h for h in holdings_rows if not h.get("is_watchlist")]

    total_unrealized = sum(float(h.get("unrealized_gain") or 0) for h in non_watchlist)
    realized = _cumulative_realized(1, db)
    total_return_dollar = round(total_unrealized + realized, 2)
    total_return_pct = (
        round(total_return_dollar / total_cost_basis * 100, 2) if total_cost_basis > 0 else 0.0
    )
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


def _briefing_local(db: Session) -> dict:
    """Compute local briefing using move_explainer. Never calls Claude."""
    snapshot, non_watchlist = _briefing_snapshot(db)
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
            explanation = (summary.explanation_text or "")[:140]
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
    elif fell == total and total > 0:
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


def _briefing_fallback(snapshot: dict) -> dict:
    """Deterministic AI-mode response when Claude is unavailable."""
    pl = snapshot.get("today_pl") or {}
    tr = snapshot.get("total_return") or {}
    best = snapshot.get("best_today") or {}
    worst = snapshot.get("worst_today") or {}

    direction = "up" if float(pl.get("dollar") or 0) >= 0 else "down"
    pct = abs(float(pl.get("pct") or 0))
    ret_pct = float(tr.get("pct") or 0)
    health = (
        f"Your portfolio is {direction} {pct:.2f}% today. "
        f"Total return stands at {ret_pct:+.2f}% overall."
    )
    drivers: list[str] = []
    if best.get("ticker"):
        drivers.append(
            f"{best['ticker']} was your best mover today "
            f"({float(best.get('day_change_pct') or 0):+.1f}%)."
        )
    if worst.get("ticker") and worst.get("ticker") != best.get("ticker"):
        drivers.append(
            f"{worst['ticker']} pulled back "
            f"({float(worst.get('day_change_pct') or 0):+.1f}%)."
        )
    if not drivers:
        drivers = ["No standout movers today."]

    return {
        "mode": "ai",
        "source": "local-fallback",
        "health": health,
        "drivers": drivers,
        "adjustments": ["No changes needed — the book looks balanced."],
        "quote": next_briefing_canned_quote(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/portfolio-summary")
async def get_portfolio_summary(
    mode: str = "ai",
    force_refresh: bool = False,
    db: Session = Depends(get_db),
):
    """
    Portfolio briefing card.
    mode=local — deterministic move digest, no Claude, always free.
    mode=ai    — Haiku narrative, cached 24 h in AISummary (ticker=BOOK,
                 summary_type='briefing'); falls back deterministically.
    """
    if mode not in ("ai", "local"):
        mode = "ai"

    if mode == "local":
        try:
            return _briefing_local(db)
        except Exception as exc:
            logger.error("Local briefing failed; exception_type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="Briefing temporarily unavailable.")

    # AI mode — check 24 h cache first
    if not force_refresh:
        cached = (
            db.query(AISummary)
            .filter(
                AISummary.ticker == _PORTFOLIO_CACHE_TICKER,
                AISummary.summary_type == _BRIEFING_CACHE_TYPE,
            )
            .order_by(AISummary.generated_at.desc())
            .first()
        )
        if cached and _cache_is_fresh(cached):
            try:
                stored = json.loads(getattr(cached, "summary_text", None) or "{}")
                stored["from_cache"] = True
                return stored
            except Exception:
                pass  # cache corrupted — regenerate below

    # Build snapshot; surface 500 so the card can show a clear error
    try:
        snapshot, _ = _briefing_snapshot(db)
    except Exception as exc:
        logger.error("Briefing snapshot failed; exception_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Briefing temporarily unavailable.")

    # Call Haiku; fall back deterministically on any failure
    try:
        parsed = generate_portfolio_briefing(snapshot)
        payload: dict = {
            "mode": "ai",
            "source": "claude",
            **parsed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            db.add(AISummary(
                ticker=_PORTFOLIO_CACHE_TICKER,
                summary_type=_BRIEFING_CACHE_TYPE,
                summary_text=json.dumps(payload),
                price_when_generated=None,
                model_used=MODEL,
            ))
            db.commit()
        except Exception as exc:
            logger.debug("Failed to cache briefing; exception_type=%s", type(exc).__name__)
        return payload

    except Exception as exc:
        logger.warning("AI briefing failed; exception_type=%s", type(exc).__name__)
        return _briefing_fallback(snapshot)
