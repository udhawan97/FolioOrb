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
from app.services.stock_service import DEFAULT_HOLDINGS, get_all_quotes, get_stock_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])

CACHE_TTL = timedelta(hours=24)
PRICE_DRIFT_THRESHOLD = 0.05  # expire cache when price moves >5% from when it was generated


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
        raise HTTPException(status_code=404, detail=f"Cannot fetch data for {ticker}")

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
        "news": [
            {
                "title": n.title,
                "source": n.source,
                "url": n.url,
                "published_at": n.published_at,
            }
            for n in s.news
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
    "news": [],
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
    Returns market context, attribution type, likely drivers, and recent news.
    Not cached — prices and news change throughout the day.
    """
    ticker = ticker.upper()
    stock_data = get_stock_data(ticker)
    if stock_data.get("error"):
        raise HTTPException(status_code=404, detail=f"Cannot fetch data for {ticker}")

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
        except Exception as e:
            logger.error("Move explanation failed for %s: %s", ticker, e)
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
        raise HTTPException(status_code=404, detail=f"Cannot fetch data for {ticker}")
    intel = get_holding_intelligence(ticker, stock_data)
    return intelligence_to_dict(intel)


@router.get("/intelligence/all/batch")
async def get_all_intelligence(db: Session = Depends(get_db)):
    """
    Return holding intelligence for all portfolio holdings.
    Combines structured coverage data (sectors, countries, benchmarks) for every holding.
    """
    quotes = {q["ticker"]: q for q in get_all_quotes(_active_portfolio_tickers(db))}
    results: dict[str, dict] = {}
    for ticker, stock_data in quotes.items():
        try:
            intel = get_holding_intelligence(
                ticker, stock_data if not stock_data.get("error") else None
            )
            results[ticker] = intelligence_to_dict(intel)
        except Exception as e:
            logger.error("Intelligence fetch failed for %s: %s", ticker, e)
            results[ticker] = {
                "ticker": ticker,
                "coverage_type": "equity",
                "coverage_label": "Unknown",
                "strategy": "Data unavailable",
                "asset_class": "equities",
                "theme": None,
                "sectors": [],
                "countries": [],
                "top_holdings": [],
                "benchmark_tickers": ["SPY"],
                "benchmark_labels": {"SPY": "S&P 500"},
                "peer_tickers": [],
                "key_drivers": [],
                "concentration_level": "medium",
                "concentration_label": "",
                "expense_ratio": None,
                "expense_ratio_bps": None,
                "data_quality": "static",
                "data_sources": [],
            }
    return {"intelligence": results, "count": len(results)}


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
        except Exception as e:
            logger.error("Analyst rec failed for %s: %s", ticker, e)
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
