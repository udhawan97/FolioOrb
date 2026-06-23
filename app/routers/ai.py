"""
app/routers/ai.py
AI-powered summary endpoints using Claude, plus move-explanation endpoints.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AISummary, Holding
from app.services.ai_service import MODEL, generate_stock_summary
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])

CACHE_TTL = timedelta(hours=24)
PRICE_DRIFT_THRESHOLD = 0.05  # expire cache when price moves >5% from when it was generated
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
    AISummary rows do not persist exact token usage, so this uses a text-length
    estimate plus the prompt size used by generate_stock_summary.
    """
    summaries = db.query(AISummary).all()
    cached_count = len(summaries)
    estimated_output_tokens = sum(
        _estimate_text_tokens(getattr(summary, "summary_text", ""))
        for summary in summaries
    )
    estimated_input_tokens = cached_count * ESTIMATED_PROMPT_TOKENS_PER_SUMMARY
    estimated_cost_usd = (
        estimated_input_tokens / 1_000_000 * HAIKU_45_INPUT_USD_PER_MILLION
        + estimated_output_tokens / 1_000_000 * HAIKU_45_OUTPUT_USD_PER_MILLION
    )

    return {
        "model": MODEL,
        "cached_summaries": cached_count,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_total_tokens": estimated_input_tokens + estimated_output_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "pricing": {
            "input_usd_per_million_tokens": HAIKU_45_INPUT_USD_PER_MILLION,
            "output_usd_per_million_tokens": HAIKU_45_OUTPUT_USD_PER_MILLION,
        },
        "is_estimate": True,
        "note": "Estimated from cached summaries; exact Anthropic token usage is not stored.",
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
    Get or generate summaries for all default holdings.
    Returns cached summaries immediately, generates new ones for missing or stale tickers.
    This endpoint may take 30-60 seconds if generating all summaries fresh.
    """
    results = {}

    quotes = {q["ticker"]: q for q in get_all_quotes()}

    for ticker in DEFAULT_HOLDINGS:
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
async def get_holding_intelligence_single(ticker: str):
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
