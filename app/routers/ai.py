"""
app/routers/ai.py
AI-powered summary endpoints using Claude, plus move-explanation endpoints.
"""
# pylint: disable=too-many-lines
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AISummary, VerdictSnapshot
from app.services.ai_service import (
    MODEL,
    ACTION_PLAN_MODEL,
    get_cached_claude_heartbeat,
    get_accumulated_usage,
    generate_etf_profile_seed,
    generate_portfolio_briefing,
    generate_analytics_insights,
    generate_action_plan,
    generate_stock_summary,
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
    QUOTE_FETCH_ERROR,
    get_all_quotes,
    get_stock_data,
    ticker_shape_is_safe,
)
from app.services.insider_activity import get_insider_activity
from app.services.fundamentals import get_fundamentals
from app.services.timing_signal import (
    get_batched_history_closes,
    get_cached_history_closes,
)
from app.services.peer_relative import compute_peer_relative
from app.services.event_calendar import build_event_context
from app.services.verdict_calibration import calibration_summary
from app.services.verdict_report import build_verdict_report
from app.services import (
    action_plan,
    ai_narrative,
    api_key_store,
    holdings_repository,
    narrative_cache,
    portfolio_briefing,
    verdict_pipeline,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])

CACHE_TTL = timedelta(hours=24)
PRICE_DRIFT_THRESHOLD = 0.08  # stock summaries only; verdicts key off action + market mood
HAIKU_45_INPUT_USD_PER_MILLION = 1.00
HAIKU_45_OUTPUT_USD_PER_MILLION = 5.00
ESTIMATED_PROMPT_TOKENS_PER_SUMMARY = 120

# Predicted tokens for one full dashboard cycle at ~10 holdings
# summaries + verdicts + briefing + news + analytics + ETF seeds + action plan
_PREDICTED_IN_PER_RUN = 2600
_PREDICTED_OUT_PER_RUN = 3000


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


@router.get("/cache/stats")
def get_ai_cache_stats(db: Session = Depends(get_db)):
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

    actual = get_accumulated_usage()
    actual_cost_usd = (
        actual["total_in"] / 1_000_000 * HAIKU_45_INPUT_USD_PER_MILLION
        + actual["total_out"] / 1_000_000 * HAIKU_45_OUTPUT_USD_PER_MILLION
    )
    predicted_cost_usd = (
        _PREDICTED_IN_PER_RUN / 1_000_000 * HAIKU_45_INPUT_USD_PER_MILLION
        + _PREDICTED_OUT_PER_RUN / 1_000_000 * HAIKU_45_OUTPUT_USD_PER_MILLION
    )

    return {
        "model": MODEL,
        "cached_summaries": cached_count,
        "claude_cached_summaries": len(claude_summaries),
        "local_cached_summaries": fallback_count,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_total_tokens": estimated_input_tokens + estimated_output_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "actual_input_tokens": actual["total_in"],
        "actual_output_tokens": actual["total_out"],
        "actual_cost_usd": round(actual_cost_usd, 6),
        "predicted_per_run": {
            "input_tokens": _PREDICTED_IN_PER_RUN,
            "output_tokens": _PREDICTED_OUT_PER_RUN,
            "cost_usd": round(predicted_cost_usd, 6),
        },
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
def get_claude_heartbeat():
    """Return a lightweight Claude API reachability check for the dashboard HUD."""
    return {
        **get_cached_claude_heartbeat(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
    }


class _ApiKeyBody(BaseModel):
    api_key: str


@router.post("/configure-key")
def configure_api_key(body: _ApiKeyBody):
    """
    Validate, persist, and hot-reload a new Anthropic API key.
    The key is written to the local .env file only — never returned or logged.
    """
    try:
        connected = api_key_store.save(body.api_key)
    except api_key_store.InvalidKeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "That doesn't look like a valid Anthropic API key. "
                "Keys start with sk-ant- and are fairly long. "
                "Double-check you copied the whole thing."
            ),
        ) from exc
    except api_key_store.KeyStorageError as exc:
        raise HTTPException(status_code=500, detail="Could not save key to disk.") from exc

    if connected:
        return {
            "success": True,
            "connected": True,
            "message": "API key saved and connected. AI features are now live.",
        }
    return {
        "success": True,
        "connected": False,
        "message": (
            "Key saved, but I couldn't reach Anthropic with it — double-check the "
            "key is correct and still active. Local Intelligence keeps running in "
            "the meantime."
        ),
    }


@router.delete("/configure-key")
def remove_api_key():
    """Remove the stored Anthropic key and fall back to Local Intelligence only."""
    try:
        api_key_store.clear()
    except api_key_store.KeyStorageError as exc:
        raise HTTPException(status_code=500, detail="Could not update key on disk.") from exc
    return {
        "success": True,
        "message": "Claude disconnected. Local Intelligence is still running.",
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
    stock_data = get_stock_data(ticker)
    cache = narrative_cache.NarrativeCache(
        db,
        ttl=CACHE_TTL,
        price_drift_threshold=PRICE_DRIFT_THRESHOLD,
    )

    if not force_refresh:
        current_price = (
            stock_data.get("current_price") if not stock_data.get("error") else None
        )
        cached = cache.fresh(ticker, "stock", current_price=current_price)
        if cached is not None:
            return {
                "ticker": ticker,
                "summary": cached.summary_text,
                "generated_at": cached.generated_at.isoformat(),
                "from_cache": True,
                "price_when_generated": cached.price_when_generated,
            }

    if stock_data.get("error"):
        raise HTTPException(status_code=404, detail=QUOTE_FETCH_ERROR)

    summary_text = generate_stock_summary(stock_data)

    cache.store_text(
        ticker,
        "stock",
        summary_text,
        MODEL,
        price_when_generated=stock_data["current_price"],
    )

    return {
        "ticker": ticker,
        "summary": summary_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "from_cache": False,
        "price_when_generated": stock_data["current_price"],
    }


@router.get("/summaries/all")
async def get_all_summaries(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Get or generate AI summaries for all active portfolio holdings.
    Returns cached summaries immediately, generates new ones for missing or stale tickers.
    This endpoint may take 30-60 seconds if generating all summaries fresh.
    """
    results = {}

    active_tickers = holdings_repository.active_tickers_or_default(db, portfolio_id)
    quotes = {q["ticker"]: q for q in get_all_quotes(active_tickers)}
    cache = narrative_cache.NarrativeCache(
        db,
        ttl=CACHE_TTL,
        price_drift_threshold=PRICE_DRIFT_THRESHOLD,
    )
    latest_summary = cache.fresh_many(
        active_tickers,
        "stock",
        current_prices={
            ticker: quotes.get(ticker, {}).get("current_price")
            for ticker in active_tickers
        },
    )

    for ticker in active_tickers:
        cached = latest_summary.get(ticker)

        if cached is not None:
            results[ticker] = {"summary": cached.summary_text, "from_cache": True}
            continue

        stock_data = quotes.get(ticker, {})
        if stock_data and not stock_data.get("error"):
            summary_text = generate_stock_summary(stock_data)
            cache.store_text(
                ticker,
                "stock",
                summary_text,
                MODEL,
                price_when_generated=stock_data.get("current_price"),
            )
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

    # One holding, user-initiated: worth an EDGAR round trip for the filings
    # that might explain the move. The /all loop below deliberately skips them.
    summary = explain_move(stock_data, include_filings=True)
    return _summary_to_dict(summary)


@router.get("/insider-activity/{ticker}")
async def get_insider_activity_endpoint(ticker: str):
    """Recent open-market insider trades (SEC Form 4) for one holding.

    Per-ticker and user-initiated, so it may spend the EDGAR round trips the
    batch paths avoid. Stocks with no insider filings — and funds, which have
    no insiders at all — return an honest empty-but-live result rather than an
    error, so the caller can render "nothing to show" without special-casing.
    """
    symbol = (ticker or "").strip().upper()
    if not ticker_shape_is_safe(symbol):
        raise HTTPException(status_code=422, detail="Invalid ticker.")
    return get_insider_activity(symbol)


@router.get("/fundamentals/{ticker}")
async def get_fundamentals_endpoint(ticker: str):
    """Annual revenue, net income, and diluted EPS from SEC XBRL filings.

    Per-ticker and user-initiated. Funds and non-filers have no financials and
    return an honest empty-but-live payload rather than an error.
    """
    symbol = (ticker or "").strip().upper()
    if not ticker_shape_is_safe(symbol):
        raise HTTPException(status_code=422, detail="Invalid ticker.")
    return get_fundamentals(symbol)


@router.get("/move-explanations/all")
def get_all_move_explanations(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Explain today's move for all portfolio holdings.
    Fetches SPY/QQQ benchmark data once, then processes each holding in turn.
    Per-holding primary benchmarks (BTC, EEM, XAR…) are fetched lazily and
    cached in a shared dict to avoid duplicate API calls.
    """
    benchmarks = get_benchmark_data()
    benchmark_cache: dict = {}  # shared cache for per-holding primary benchmarks
    active_tickers = holdings_repository.active_tickers_or_default(db, portfolio_id)
    quotes = {q["ticker"]: q for q in get_all_quotes(active_tickers)}
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
def get_all_intelligence(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Return holding intelligence for all portfolio holdings.
    Combines structured coverage data (sectors, countries, benchmarks) for every holding.
    """
    active_tickers = holdings_repository.active_tickers_or_default(db, portfolio_id)
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


def _portfolio_cache_ticker(portfolio_id: int = 1) -> str:
    """
    AISummary.ticker sentinel for portfolio-LEVEL AI caches (briefing, action
    plan, analytics insights, portfolio-state signature).

    AISummary has no portfolio_id column, so the portfolio id is folded into the
    sentinel ticker (``BOOK:<id>``) to keep each portfolio's book-level narrative
    isolated — portfolio 2 must never read portfolio 1's cached BOOK entry.
    Per-ticker summaries use real ticker strings and stay shared across
    portfolios, so they are left untouched.
    """
    return narrative_cache.portfolio_scope(portfolio_id)


@router.get("/investment-signal/{ticker}")
async def get_investment_signal_single(
    ticker: str,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Return deterministic investment signal + quip for a single ticker.
    """
    return verdict_pipeline.scan_ticker(db, ticker, portfolio_id)


@router.get("/investment-signals/all")
def get_all_investment_signals(
    db: Session = Depends(get_db),
    force_local: bool = False,
    portfolio_id: int = 1,
):
    """
    Return investment signals for all active portfolio holdings.
    Deterministic signals are computed fresh; quips are cached 24h in AISummary
    (summary_type='verdict') with price-drift invalidation.
    Pass force_local=true to skip Claude quip generation and use deterministic fallbacks.
    """
    scan = verdict_pipeline.scan_portfolio(db, portfolio_id, force_local=force_local)
    return {
        "signals": scan.signals,
        "count": scan.count,
        "portfolio_exposure": scan.exposure,
        "portfolio_health": scan.health,
        "calibration_summary": scan.calibration,
        "regime": scan.regime,
        "claude_live": scan.claude_live,
    }


@router.get("/portfolio-exposure")
async def get_portfolio_exposure(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """Look-through sector, country, and theme exposure for the active portfolio."""
    return verdict_pipeline.book_exposure(db, portfolio_id)


@router.get("/verdict-calibration")
async def get_verdict_calibration(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Lightweight calibration buckets from this portfolio's verdict snapshots."""
    return calibration_summary(db, portfolio_id)


@router.get("/verdict-report")
async def get_verdict_report(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Scorecard of how this portfolio's past verdicts have aged vs. current price.

    Reads the most recent logged verdict snapshots for the portfolio and grades
    each Add / Trim / Hold call by the holding's return *since* the call.
    """
    snapshots = (
        db.query(VerdictSnapshot)
        .filter(VerdictSnapshot.portfolio_id == portfolio_id)
        .order_by(VerdictSnapshot.generated_at.desc())
        .limit(500)
        .all()
    )
    return build_verdict_report(snapshots)


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
        live_s, _, live_h = _try_yfinance_enrichment(ticker)
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
def get_all_analyst_recommendations(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Return analyst consensus for all portfolio holdings.
    Iterates active portfolio holdings; ETFs resolve to ETF quality.
    """
    active_tickers = holdings_repository.active_tickers_or_default(db, portfolio_id)
    # Pre-fetch history in one batched/parallel call so per-ticker ETF price-signal
    # lookups (below) reuse it instead of each issuing its own yfinance history call.
    history_map = get_batched_history_closes(active_tickers)
    results: dict[str, dict] = {}
    for ticker in active_tickers:
        try:
            rec = get_analyst_recommendation(ticker, closes=history_map.get(ticker))
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


@router.get("/portfolio-summary")
def get_portfolio_summary(
    mode: str = "ai",
    time_range: str = Query("day", alias="range"),
    force_refresh: bool = False,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Portfolio briefing card.
    mode=local — deterministic move digest, no Claude, always free.
    mode=ai    — Haiku narrative, cached 24 h in AISummary (ticker=BOOK,
                 summary_type='briefing' / 'briefing_<range>');
                 falls back deterministically.
    range      — dashboard time range (day|week|month|threeMonth|sixMonth|year);
                 unknown values fall back to day.
    """
    if mode not in ("ai", "local"):
        mode = "ai"

    if mode == "local":
        try:
            return portfolio_briefing.build_local(db, time_range, portfolio_id)
        except Exception as exc:
            logger.error("Local briefing failed; exception_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=500, detail="Briefing temporarily unavailable."
            ) from exc

    def _fallback(snapshot: dict | None) -> dict:
        # Without a snapshot the card has nothing honest to show, so it errors
        # rather than narrating a book it could not read.
        if snapshot is None:
            raise HTTPException(
                status_code=500, detail="Briefing temporarily unavailable."
            )
        return portfolio_briefing.build_fallback(snapshot)

    return ai_narrative.narrative(
        db,
        _portfolio_cache_ticker(portfolio_id),
        portfolio_briefing.cache_type(time_range),
        build_snapshot=lambda: portfolio_briefing.build_snapshot(
            db, time_range, portfolio_id
        ),
        generate=lambda snapshot: portfolio_briefing.build_briefing(
            generate_portfolio_briefing(snapshot)
        ),
        fallback=_fallback,
        model=MODEL,
        label="AI briefing",
        force_refresh=force_refresh,
        ttl=CACHE_TTL,
    )


# This narrative's AISummary namespace belongs beside its snapshot and fallback
# builders in app/services/analytics_insights.py, which is outside this change's
# scope; the briefing and action-plan namespaces already moved to theirs.
_ANALYTICS_INSIGHTS_CACHE_TYPE = "analytics_insights"
_ANALYTICS_WIDGET_INSIGHTS_VERSION = 2


def _analytics_cache_needs_regeneration(stored: dict) -> bool:
    from app.services.analytics_insights import KEY_TIP_WIDGETS

    wids = stored.get("widget_insights") or {}
    cache_has_tips = any(isinstance(wids.get(k), dict) for k in KEY_TIP_WIDGETS)
    cache_version = stored.get("widget_insights_version", 1)
    if wids and not cache_has_tips:
        logger.info("Analytics insights cache is pre-tip-card format — regenerating.")
        return True
    if cache_version < _ANALYTICS_WIDGET_INSIGHTS_VERSION:
        logger.info(
            "Analytics insights cache predates AI-only widget tips — regenerating."
        )
        return True
    return False


def _merge_ai_widget_insights(local_widgets: dict, ai_widgets: dict) -> dict:
    merged: dict = {}
    for key, ai_val in ai_widgets.items():
        if ai_val is None:
            continue
        local_val = local_widgets.get(key)
        if isinstance(ai_val, dict) and ai_val.get("insight"):
            merged[key] = ai_val
        elif isinstance(ai_val, str) and ai_val.strip():
            if isinstance(local_val, dict):
                merged[key] = {
                    "headline": local_val.get("headline", ""),
                    "insight": ai_val,
                }
            else:
                merged[key] = ai_val.strip()
    return merged


@router.get("/analytics-insights")
async def get_analytics_insights(
    mode: str = "ai",
    force_refresh: bool = False,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Per-tab analytics insight bar.
    mode=local — static digest of what each tab means + deterministic one-liners.
    mode=ai    — Claude sentence per tab, cached 24 h (ticker=BOOK).
    """
    from app.services.analytics_insights import (
        build_analytics_fallback,
        build_analytics_snapshot,
        build_local_analytics_insights,
        build_local_widget_insights,
    )

    if mode not in ("ai", "local"):
        mode = "ai"

    if mode == "local":
        try:
            snapshot = build_analytics_snapshot(db, portfolio_id)
            return build_local_analytics_insights(snapshot)
        except Exception as exc:
            logger.error(
                "Local analytics insights failed; exception_type=%s",
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=500,
                detail="Analytics insights temporarily unavailable.",
            ) from exc

    def _generate(snapshot: dict) -> dict:
        parsed = generate_analytics_insights(snapshot)
        local_widgets = build_local_widget_insights(snapshot)
        merged_widgets = _merge_ai_widget_insights(
            local_widgets,
            parsed.get("widget_insights") or {},
        )
        return {
            "mode": "ai",
            "source": "claude",
            "insights": parsed.get("insights") or {},
            "widget_insights": merged_widgets,
            "widget_insights_version": _ANALYTICS_WIDGET_INSIGHTS_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _fallback(snapshot: dict | None) -> dict:
        # Without a snapshot the bar has nothing honest to show, so it errors
        # rather than narrating tabs it could not read.
        if snapshot is None:
            raise HTTPException(
                status_code=500,
                detail="Analytics insights temporarily unavailable.",
            )
        return build_analytics_fallback(snapshot)

    return ai_narrative.narrative(
        db,
        _portfolio_cache_ticker(portfolio_id),
        _ANALYTICS_INSIGHTS_CACHE_TYPE,
        build_snapshot=lambda: build_analytics_snapshot(db, portfolio_id),
        generate=_generate,
        fallback=_fallback,
        model=MODEL,
        label="AI analytics insights",
        force_refresh=force_refresh,
        validator=lambda payload: not _analytics_cache_needs_regeneration(payload),
        ttl=CACHE_TTL,
    )


# ── Portfolio Action Plan endpoint ────────────────────────────────────────────


@router.get("/action-plan")
def get_action_plan(
    force_refresh: bool = False,
    force_local: bool = False,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Portfolio Action Plan — Claude reads the full book and returns a prioritised
    bucket plan (Hold / Add / Trim / Exit) with a thesis and top moves.

    Cached 24 h in AISummary (ticker=BOOK, summary_type='action_plan').
    Invalidated on portfolio-state drift (dominant action + concentration shift).
    Falls back deterministically when Claude is unavailable or force_local=True.
    """
    # Verdicts as raw material: the plan reads them, it does not serve them, so
    # it skips narration (quips, cache traffic, scan history, Claude).
    scan = verdict_pipeline.scan_portfolio(db, portfolio_id, narrate=False)

    # Local-only path: skip Claude entirely — return deterministic buckets instantly
    if force_local:
        return action_plan.build_fallback(scan)

    return ai_narrative.narrative(
        db,
        _portfolio_cache_ticker(portfolio_id),
        action_plan.cache_type(scan),
        build_snapshot=lambda: action_plan.build_snapshot(db, scan, portfolio_id),
        generate=lambda snapshot: action_plan.build_plan(
            scan, generate_action_plan(snapshot)
        ),
        fallback=lambda snapshot: action_plan.build_fallback(scan, snapshot),
        model=ACTION_PLAN_MODEL,
        label="Action plan",
        force_refresh=force_refresh,
        ttl=CACHE_TTL,
    )
