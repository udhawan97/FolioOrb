"""
app/routers/ai.py
AI-powered summary endpoints using Claude, plus move-explanation endpoints.
"""
# pylint: disable=too-many-lines
import logging
import os
import re
import stat
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AISummary, Holding, VerdictSnapshot
from app.paths import data_dir
from app.services.ai_service import (
    MODEL,
    ACTION_PLAN_MODEL,
    claude_api_heartbeat,
    get_cached_claude_heartbeat,
    get_accumulated_usage,
    generate_etf_profile_seed,
    generate_portfolio_briefing,
    generate_analytics_insights,
    generate_action_plan,
    generate_stock_summary,
    next_briefing_canned_quote,
    reinitialize_client,
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
    ticker_shape_is_safe,
)
from app.services.insider_activity import get_insider_activity
from app.services.fundamentals import get_fundamentals
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
)
from app.services.portfolio_exposure import (
    build_portfolio_exposure,
    exposure_context_for_ticker,
)
from app.services.market_regime import get_market_regime
from app.services.peer_relative import compute_peer_relative
from app.services.event_calendar import build_event_context
from app.services.portfolio_state import portfolio_state_signature
from app.services.verdict_calibration import (
    calibration_footnote,
    calibration_summary,
    compute_calibration_buckets,
    log_verdict_snapshot,
)
from app.services.verdict_report import build_verdict_report
from app.services import narrative_cache, portfolio_valuation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])


def _log_claude_call_result(label: str, exc: Exception) -> None:
    """Warn on a genuine Claude-call failure; debug-log the common no-key case.

    An unconfigured API key surfaces as a client-side TypeError from the
    Anthropic SDK before any request is made — the default, key-optional
    state, not a failure. Warning about it on every load would cry wolf.
    """
    if settings.ANTHROPIC_API_KEY.strip():
        logger.warning("%s failed; exception_type=%s", label, type(exc).__name__)
    else:
        logger.debug("%s skipped; no Claude API key configured", label)

# Only accept the canonical Anthropic key format: sk-ant-<variant>-<chars>
# This guards against prompt injection via the key field and nonsense values.
_API_KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,300}$")

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


def _update_env_file(key: str, value: str) -> None:
    """Write or overwrite a single KEY=value line in the local .env file.

    The file holds secrets (e.g. ANTHROPIC_API_KEY), so it's restricted to
    owner-only read/write (0600) on every write, including first creation —
    other local accounts on the machine can't read it even though it's
    plaintext, which is the standard mitigation for local secret files (same
    approach used by ~/.netrc, ~/.aws/credentials, etc). This is intentional,
    local-only storage: FolioOrb is a single-user, local-first app with no
    server-side secrets store, so the key never leaves the user's machine.
    """
    env_path = data_dir() / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []

    new_line = f"{key}={value}\n"
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replaced = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            replaced = True
            break

    if not replaced:
        # A hand-edited .env may not end in a newline. splitlines() can't tell us
        # that, so without this the appended line is concatenated onto the last
        # entry and both are destroyed.
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)

    env_path.write_text("".join(lines), encoding="utf-8")
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)


@router.post("/configure-key")
def configure_api_key(body: _ApiKeyBody):
    """
    Validate, persist, and hot-reload a new Anthropic API key.
    The key is written to the local .env file only — never returned or logged.
    """
    raw = body.api_key.strip()

    # Reject anything that doesn't look like a real Anthropic key
    if not _API_KEY_RE.match(raw):
        raise HTTPException(
            status_code=422,
            detail=(
                "That doesn't look like a valid Anthropic API key. "
                "Keys start with sk-ant- and are fairly long. "
                "Double-check you copied the whole thing."
            ),
        )

    try:
        _update_env_file("ANTHROPIC_API_KEY", raw)
    except OSError as exc:
        logger.error("Failed to write API key to .env: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not save key to disk.") from exc

    # Swap the live client so AI endpoints work immediately (no restart needed)
    reinitialize_client(raw)

    logger.info("Anthropic API key updated via dashboard (key not logged)")

    # A well-formed key can still be revoked, mistyped, or unreachable. Verify it
    # actually reaches Anthropic before claiming "connected" — otherwise the user
    # is told AI is live while every panel silently serves local fallbacks.
    heartbeat = claude_api_heartbeat()
    if heartbeat.get("live"):
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
        _update_env_file("ANTHROPIC_API_KEY", "")
    except OSError as exc:
        logger.error("Failed to clear API key in .env: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not update key on disk.") from exc

    reinitialize_client("")
    logger.info("Anthropic API key removed via dashboard")
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

    active_tickers = _active_portfolio_tickers(db, portfolio_id)
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
async def get_all_move_explanations(
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
    quotes = {
        q["ticker"]: q
        for q in get_all_quotes(_active_portfolio_tickers(db, portfolio_id))
    }
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
async def get_all_intelligence(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Return holding intelligence for all portfolio holdings.
    Combines structured coverage data (sectors, countries, benchmarks) for every holding.
    """
    active_tickers = _active_portfolio_tickers(db, portfolio_id)
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

VERDICT_BRAND_KICKER = "FolioOrb \u00d7 Claude"
VERDICT_BRAND_KICKER_LOCAL = "FolioOrb Intelligence"
VERDICT_FEELS_PREFIX = "FolioOrb feels"
_VERDICT_DISCLAIMER = (
    "FolioOrb Intelligence \u2014 a signal read, not "
    "financial advice. Verify before you trade."
)
_AI_VERDICT_DISCLAIMER = _VERDICT_DISCLAIMER
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
    """Backward-compatible alias for portfolio_state_signature."""
    return portfolio_state_signature(signals, alloc_map)


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


def _brand_payload(*, ai_mode: bool = False) -> dict:
    return {
        "kicker": VERDICT_BRAND_KICKER if ai_mode else VERDICT_BRAND_KICKER_LOCAL,
        "feels_prefix": VERDICT_FEELS_PREFIX,
        "disclaimer": _AI_VERDICT_DISCLAIMER if ai_mode else _VERDICT_DISCLAIMER,
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


@router.get("/investment-signal/{ticker}")
async def get_investment_signal_single(
    ticker: str,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Return deterministic investment signal + quip for a single ticker.
    """
    ticker = ticker.upper()
    meta = _holding_meta(db, portfolio_id)
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
        user_context=_user_context(holding, quote_data, db, ticker, portfolio_id),
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


def _collect_portfolio_signals_core(
    db: Session, portfolio_id: int = 1
) -> dict:  # pylint: disable=too-many-locals
    """
    Shared signal pipeline: active tickers → per-ticker deterministic signal dicts.

    Runs the full verdict pipeline (analyst rec, timing, peer, events, exposure,
    investment-signal build → signal_to_dict) for every active holding.
    Returns raw sig_dicts plus the shared portfolio metadata so that both
    ``get_all_investment_signals`` and ``get_action_plan`` can consume it without
    duplicating the loop.

    Error tickers carry ``{"_signal_error": True, **_NEEDS_DATA_SIGNAL}`` so the
    callers can distinguish build failures from legitimate needs-data verdicts.
    """
    active_tickers = _active_portfolio_tickers(db, portfolio_id)
    holding_meta = _holding_meta(db, portfolio_id)
    quotes = {q["ticker"]: q for q in get_all_quotes(active_tickers)}
    history_map = get_batched_history_closes(active_tickers)
    alloc_map = _compute_allocation_pcts(holding_meta, quotes)

    portfolio_exposure = build_portfolio_exposure(
        _holdings_for_exposure(holding_meta, alloc_map),
        quotes=quotes,
    )
    regime = get_market_regime()

    signals: dict[str, dict] = {}
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
                user_context=_user_context(meta, quote_data, db, ticker, portfolio_id),
            )
            signals[ticker] = signal_to_dict(sig)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "Signal build failed for %s; exception_type=%s",
                ticker, type(exc).__name__,
            )
            signals[ticker] = {**_NEEDS_DATA_SIGNAL, "ticker": ticker, "_signal_error": True}

    return {
        "active_tickers": active_tickers,
        "signals": signals,
        "alloc_map": alloc_map,
        "holding_meta": holding_meta,
        "portfolio_exposure": portfolio_exposure,
        "regime": regime,
        "quotes": quotes,
        "history_map": history_map,
    }


@router.get("/investment-signals/all")
async def get_all_investment_signals(  # pylint: disable=too-many-statements,too-many-branches
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
    core = _collect_portfolio_signals_core(db, portfolio_id)
    book_ticker = _portfolio_cache_ticker(portfolio_id)
    active_tickers = core["active_tickers"]
    holding_meta = core["holding_meta"]
    portfolio_exposure = core["portfolio_exposure"]
    regime = core["regime"]
    quotes = core["quotes"]
    alloc_map = core["alloc_map"]

    signals: dict[str, dict] = {}
    missing_quip_tickers: list[str] = []
    scan_snapshot_changed = False
    cache = narrative_cache.NarrativeCache(db, ttl=CACHE_TTL)
    # Calibration buckets are portfolio-wide (not ticker-specific), so compute them
    # once here instead of re-querying/re-aggregating on every loop iteration below.
    calibration_buckets = compute_calibration_buckets(db, window="1m", portfolio_id=portfolio_id)

    for ticker in active_tickers:
        try:
            raw = core["signals"].get(ticker) or {}
            sig_dict = dict(raw)
            # Tickers that failed signal-building in the core helper get an immediate
            # fallback quip — matching original behaviour (exceptions skip AI pipeline).
            if sig_dict.pop("_signal_error", False):
                sig_dict["quip"] = fallback_quip("needs-data")
                sig_dict["ai_enhanced"] = False
                sig_dict["disclaimer"] = _VERDICT_DISCLAIMER
                sig_dict["brand"] = _brand_payload()
                sig_dict.setdefault("generated_at", "")
                signals[ticker] = sig_dict
                continue

            meta = holding_meta.get(ticker, {})
            hold_class = meta.get("hold_class", "auto")
            action = sig_dict.get("action", "needs-data")
            confidence = sig_dict.get("confidence", 0)
            quote_data = quotes.get(ticker) or {}

            footnote = calibration_footnote(
                db, action=action, confidence=confidence,
                buckets=calibration_buckets, portfolio_id=portfolio_id,
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
                price_at_scan=quote_data.get("current_price"),
                hold_class=hold_class,
                portfolio_id=portfolio_id,
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
            cached = cache.get_verdict(
                ticker,
                summary_type,
                current_price=quote_data.get("current_price"),
            )
            if cached is not None:
                sig_dict["ai_enhanced"] = _hydrate_cached_verdict(sig_dict, cached)
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
    portfolio_cached = cache.get_verdict(
        book_ticker,
        portfolio_state["summary_type"],
    )
    portfolio_quip: str | None = None
    include_portfolio_quip = False
    if portfolio_cached is not None:
        portfolio_quip = portfolio_cached.get("quip") or None
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
                    "ticker": book_ticker,
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
                cache.store_verdict(
                    ticker,
                    summary_type,
                    quip,
                    ai_raw if claude_live else None,
                    MODEL if bundle.get("quip") and claude_live else "fallback",
                    price_when_generated=current_price,
                    commit=False,
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug(
                    "Failed to cache quip for %s; exception_type=%s",
                    ticker, type(exc).__name__,
                )
        if include_portfolio_quip:
            book_bundle = new_bundles.get(book_ticker) or {}
            portfolio_quip = book_bundle.get("quip") or _portfolio_fallback_quip(
                portfolio_state["dominant_action"],
                portfolio_state["concentration_band"],
            )
            try:
                cache.store_verdict(
                    book_ticker,
                    portfolio_state["summary_type"],
                    portfolio_quip,
                    None,
                    MODEL if book_bundle.get("quip") and claude_live else "fallback",
                    commit=False,
                )
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
        "calibration_summary": calibration_summary(db, portfolio_id),
        "regime": regime,
        "claude_live": claude_live,
    }


@router.get("/portfolio-exposure")
async def get_portfolio_exposure(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """Look-through sector, country, and theme exposure for the active portfolio."""
    holding_meta = _holding_meta(db, portfolio_id)
    tickers = list(holding_meta.keys())
    quotes = {q["ticker"]: q for q in get_all_quotes(tickers)}
    alloc_map = _compute_allocation_pcts(holding_meta, quotes)
    exposure = build_portfolio_exposure(
        _holdings_for_exposure(holding_meta, alloc_map),
        quotes=quotes,
    )
    return exposure


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
async def get_all_analyst_recommendations(
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Return analyst consensus for all portfolio holdings.
    Iterates active portfolio holdings; ETFs resolve to ETF quality.
    """
    active_tickers = _active_portfolio_tickers(db, portfolio_id)
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

_BRIEFING_CACHE_TYPE = "briefing"

# Dashboard time ranges the briefing can narrate. "day" keeps the legacy
# live-quote path and the legacy "briefing" cache type; longer ranges compute
# from daily closes and cache under "briefing_<range>" so each range gets its
# own 24 h entry.
_BRIEFING_RANGES: dict[str, dict] = {
    "day":        {"phrase": "today",                  "calendar_days": None},
    "week":       {"phrase": "over the past week",     "calendar_days": 7},
    "month":      {"phrase": "over the past month",    "calendar_days": 30},
    "threeMonth": {"phrase": "over the past 3 months", "calendar_days": 90},
    "sixMonth":   {"phrase": "over the past 6 months", "calendar_days": 180},
    "year":       {"phrase": "over the past year",     "calendar_days": 365},
}


def _normalize_briefing_range(range_key: str | None) -> str:
    return range_key if range_key in _BRIEFING_RANGES else "day"


def _briefing_cache_type(range_key: str) -> str:
    if range_key == "day":
        return _BRIEFING_CACHE_TYPE
    return f"{_BRIEFING_CACHE_TYPE}_{range_key}"


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


def _briefing_snapshot(db: Session, portfolio_id: int = 1) -> tuple[dict, list[dict]]:
    """
    Build the compact portfolio snapshot fed to Haiku (and used for the local
    briefing lead line).  Returns (snapshot_dict, non_watchlist_holdings).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    holdings_rows = valuation.holdings
    total_value = valuation.total_value
    total_daily_change = valuation.total_daily_change
    non_watchlist = [h for h in holdings_rows if not h.get("is_watchlist")]

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


def _briefing_period_snapshot(
    db: Session, range_key: str, portfolio_id: int = 1
) -> tuple[dict, list[dict]]:
    """
    Range-aware snapshot variant: swaps the day-scoped fields for period ones
    (daily-close lookbacks for movers, snapshot history for portfolio P&L) so
    Haiku narrates the selected window instead of today's tape.
    """
    from app.services.portfolio_analytics import compute_range_rows

    snapshot, non_watchlist = _briefing_snapshot(db, portfolio_id)
    cfg = _BRIEFING_RANGES[range_key]
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


def _briefing_local_period(db: Session, range_key: str, portfolio_id: int = 1) -> dict:
    """
    Local briefing over a non-day range: deterministic period digest from daily
    closes. Move explainers are day-scoped, so period movers carry no
    explanation text.
    """
    from app.services.portfolio_analytics import compute_range_rows

    cfg = _BRIEFING_RANGES[range_key]
    phrase = cfg["phrase"]
    snapshot, non_watchlist = _briefing_snapshot(db, portfolio_id)
    quality = snapshot.get("valuation") or {}
    if quality.get("data_quality") != "complete":
        return _briefing_local_quality_response(snapshot, period_label=phrase)
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


def _briefing_local(db: Session, portfolio_id: int = 1) -> dict:
    """Compute local briefing using move_explainer. Never calls Claude."""
    snapshot, non_watchlist = _briefing_snapshot(db, portfolio_id)
    if (snapshot.get("valuation") or {}).get("data_quality") != "complete":
        return _briefing_local_quality_response(snapshot)
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


def _briefing_local_quality_response(
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


@router.get("/portfolio-summary")
async def get_portfolio_summary(
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
    range_key = _normalize_briefing_range(time_range)
    book_ticker = _portfolio_cache_ticker(portfolio_id)

    if mode == "local":
        try:
            if range_key == "day":
                return _briefing_local(db, portfolio_id)
            return _briefing_local_period(db, range_key, portfolio_id)
        except Exception as exc:
            logger.error("Local briefing failed; exception_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=500, detail="Briefing temporarily unavailable."
            ) from exc

    # AI mode — check 24 h cache first (one entry per range)
    cache_type = _briefing_cache_type(range_key)
    cache = narrative_cache.NarrativeCache(db, ttl=CACHE_TTL)
    if not force_refresh:
        stored = cache.get_json(book_ticker, cache_type)
        if stored is not None:
            stored["from_cache"] = True
            return stored

    # Build snapshot; surface 500 so the card can show a clear error
    try:
        if range_key == "day":
            snapshot, _ = _briefing_snapshot(db, portfolio_id)
        else:
            snapshot, _ = _briefing_period_snapshot(db, range_key, portfolio_id)
    except Exception as exc:
        logger.error("Briefing snapshot failed; exception_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=500, detail="Briefing temporarily unavailable."
        ) from exc

    if (snapshot.get("valuation") or {}).get("data_quality") != "complete":
        return _briefing_fallback(snapshot)

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
            cache.store_json(book_ticker, cache_type, payload, MODEL)
        except Exception as exc:
            logger.debug("Failed to cache briefing; exception_type=%s", type(exc).__name__)
        return payload

    except Exception as exc:
        _log_claude_call_result("AI briefing", exc)
        return _briefing_fallback(snapshot)


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


def _cache_analytics_insights(db: Session, payload: dict, portfolio_id: int = 1) -> None:
    try:
        narrative_cache.NarrativeCache(db, ttl=CACHE_TTL).store_json(
            _portfolio_cache_ticker(portfolio_id),
            _ANALYTICS_INSIGHTS_CACHE_TYPE,
            payload,
            MODEL,
        )
    except Exception as exc:
        logger.debug(
            "Failed to cache analytics insights; exception_type=%s",
            type(exc).__name__,
        )


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

    if not force_refresh:
        stored = narrative_cache.NarrativeCache(db, ttl=CACHE_TTL).get_json(
            _portfolio_cache_ticker(portfolio_id),
            _ANALYTICS_INSIGHTS_CACHE_TYPE,
            validator=lambda payload: not _analytics_cache_needs_regeneration(payload),
        )
        if stored is not None:
            stored["from_cache"] = True
            return stored

    try:
        snapshot = build_analytics_snapshot(db, portfolio_id)
    except Exception as exc:
        logger.error("Analytics snapshot failed; exception_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Analytics insights temporarily unavailable.",
        ) from exc

    valuation_state = snapshot.get("valuation") or {}
    if valuation_state.get("data_quality") != "complete":
        return build_analytics_fallback(snapshot)

    try:
        parsed = generate_analytics_insights(snapshot)
        local_widgets = build_local_widget_insights(snapshot)
        merged_widgets = _merge_ai_widget_insights(
            local_widgets,
            parsed.get("widget_insights") or {},
        )
        payload: dict = {
            "mode": "ai",
            "source": "claude",
            "insights": parsed.get("insights") or {},
            "widget_insights": merged_widgets,
            "widget_insights_version": _ANALYTICS_WIDGET_INSIGHTS_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        _cache_analytics_insights(db, payload, portfolio_id)
        return payload

    except Exception as exc:
        _log_claude_call_result("AI analytics insights", exc)
        return build_analytics_fallback(snapshot)


# ── Portfolio Action Plan endpoint ────────────────────────────────────────────

# Bumped v2 → v3: portfolio_state_signature now folds in the secondary action
# (fixing a cache collision between e.g. "2 hold, 1 add" and "2 hold, 1 trim"
# books). Bumping the version cleanly orphans any pre-fix cached rows instead
# of risking a stale, collision-prone entry being read under the old key.
_ACTION_PLAN_CACHE_TYPE = "action_plan_v3"

_GAP_TYPE_LABEL: dict[str, str] = {
    "heavy_hold":    "large position on hold",
    "large_trim":    "oversized position flagged for trim",
    "small_add":     "undersized position with buy signal",
    "uncertain_hold": "low-confidence hold",
}


def _action_plan_snapshot(
    db: Session, core: dict, portfolio_id: int = 1
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

    signals = core["signals"]
    alloc_map = core["alloc_map"]
    holding_meta = core["holding_meta"]
    portfolio_exposure = core["portfolio_exposure"]
    regime = core["regime"]
    active_tickers = core["active_tickers"]

    # Portfolio value + per-holding total_return_pct from the valuation module.
    try:
        valuation = portfolio_valuation.evaluate(db, portfolio_id)
        holdings_rows = valuation.holdings
        total_value = valuation.total_value
        valuation_quality = {
            "data_quality": valuation.data_quality,
            "missing_tickers": list(valuation.missing_tickers),
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
            "priced_position_count": 0,
            "expected_position_count": len(active_tickers),
        }

    return_map = {
        h["ticker"]: float(h.get("total_return_pct") or 0)
        for h in holdings_rows
    }

    # Per-holding compact entries
    holdings_data = []
    for ticker in active_tickers:
        sig = {k: v for k, v in (signals.get(ticker) or {}).items()
               if not k.startswith("_")}
        meta = holding_meta.get(ticker, {})
        entry: dict = {
            "t": ticker,
            "action": sig.get("action", "needs-data"),
            "conf": sig.get("confidence", 0),
            "alloc_pct": alloc_map.get(ticker, 0),
            "ret_pct": return_map.get(ticker, 0),
            "reason": (sig.get("reasons") or [""])[0][:80],
            "risk": (sig.get("risks") or [""])[0][:60],
            "flip": sig.get("flip_triggers"),
            "hold_class": sig.get("hold_class", "auto"),
            "watchlist": meta.get("is_watchlist", False),
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

    # Exposure summary — top 4 sectors + top 3 countries
    sectors = (portfolio_exposure.get("sectors") or [])[:4]
    countries = (portfolio_exposure.get("countries") or [])[:3]
    hhi = float(portfolio_exposure.get("concentration_hhi") or 0)

    # Conviction gaps summary
    gap_items = (conviction_data.get("gaps") or [])[:3]

    snapshot: dict = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "valuation": valuation_quality,
        "total_value": round(total_value, 0),
        "regime": {
            "label": regime.get("label", ""),
            "mood": regime.get("mood", ""),
        },
        "concentration_hhi": round(hhi, 3),
        "hhi_band": (
            "high" if hhi >= 0.25 else "medium" if hhi >= 0.10 else "low"
        ),
        "holdings": holdings_data,
        "exposure": {
            "top_sectors": [
                {
                    "s": s.get("sector") or s.get("name", ""),
                    "w": round(float(s.get("weight_pct") or 0), 1),
                }
                for s in sectors
            ],
            "top_countries": [
                {
                    "c": c.get("country") or c.get("name", ""),
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
        "tilt": [
            {"s": t.get("sector", ""), "vs_spy": round(float(t.get("overweight_pct") or 0), 1)}
            for t in (sector_tilt_data.get("tilt") or [])[:3]
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


def _action_plan_fallback(core: dict) -> dict:
    """
    Deterministic fallback when Claude is unavailable or force_local=True.
    Buckets holdings purely from their existing verdict actions.
    """
    signals = core["signals"]
    alloc_map = core["alloc_map"]
    holding_meta = core["holding_meta"]
    active_tickers = core["active_tickers"]
    regime = core["regime"]

    buckets: dict[str, list[dict]] = {"hold": [], "add": [], "trim": [], "exit": []}
    for ticker in active_tickers:
        sig = signals.get(ticker) or {}
        action = str(sig.get("action") or "hold").lower()
        meta = holding_meta.get(ticker, {})
        reason = (sig.get("reasons") or [""])[0][:80]

        # Map verdict actions: watchlist "trim" or needs-data → exit bucket
        if meta.get("is_watchlist") and action in ("trim", "needs-data"):
            bucket_key = "exit"
        elif action in ("hold", "add", "trim"):
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

    # Build a plain-language headline from the dominant signal
    if n_trim or n_exit:
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
        f"FolioOrb local signals: {n_hold} hold · {n_add} add · "
        f"{n_trim} trim · {n_exit} exit. "
        f"Market: {regime_label}. "
        "Enable Claude AI in Settings for a cross-holding, risk-adjusted plan."
    )

    alloc_sorted = sorted(
        [(t, alloc_map.get(t, 0)) for t in active_tickers],
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
            "Diversify concentration to close the gap to the optimal mix."
        ),
        "regime": regime,
        "disclaimer": _VERDICT_DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/action-plan")
async def get_action_plan(
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
    # Build portfolio state signature for cache invalidation
    core = _collect_portfolio_signals_core(db, portfolio_id)
    book_ticker = _portfolio_cache_ticker(portfolio_id)

    # Local-only path: skip Claude entirely — return deterministic buckets instantly
    if force_local:
        return _action_plan_fallback(core)

    alloc_map = core["alloc_map"]
    raw_signals = core["signals"]
    # Strip internal flags before portfolio_state_signature
    clean_signals = {
        t: {k: v for k, v in sig.items() if not k.startswith("_")}
        for t, sig in raw_signals.items()
    }
    port_state = _portfolio_state_signature(clean_signals, alloc_map)
    cache_summary_type = f"{_ACTION_PLAN_CACHE_TYPE}:{port_state['summary_type']}"
    cache = narrative_cache.NarrativeCache(db, ttl=CACHE_TTL)

    if not force_refresh:
        stored = cache.get_json(book_ticker, cache_summary_type)
        if stored is not None:
            stored["from_cache"] = True
            return stored

    # Build compact snapshot for Claude
    try:
        snapshot = _action_plan_snapshot(db, core, portfolio_id)
    except Exception as exc:
        logger.warning(
            "Action plan snapshot failed; exception_type=%s",
            type(exc).__name__,
        )
        return _action_plan_fallback(core)

    valuation_state = snapshot.get("valuation") or {}
    if valuation_state.get("data_quality") != "complete":
        fallback = _action_plan_fallback(core)
        quality = valuation_state.get("data_quality", "unavailable")
        missing = list(valuation_state.get("missing_tickers") or [])
        fallback.update(
            {
                "source": "data-unavailable" if quality == "unavailable" else "partial-data",
                "data_quality": quality,
                "missing_tickers": missing,
                "headline": f"Live Portfolio valuation is {quality}",
                "thesis": (
                    "No Claude plan was generated because unpriced positions would make "
                    "Portfolio-level totals incomplete."
                ),
            }
        )
        return fallback

    # Call Claude — fall back deterministically on any failure
    try:
        parsed = generate_action_plan(snapshot)
        payload: dict = {
            "source": "claude",
            **parsed,
            "regime": core["regime"],
            "disclaimer": _VERDICT_DISCLAIMER,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            cache.store_json(
                book_ticker,
                cache_summary_type,
                payload,
                ACTION_PLAN_MODEL,
            )
        except Exception as exc:
            logger.debug(
                "Failed to cache action plan; exception_type=%s",
                type(exc).__name__,
            )
        return payload

    except Exception as exc:
        _log_claude_call_result("Action plan Claude call", exc)
        return _action_plan_fallback(core)
