"""
app/routers/news.py

News zone endpoints.

GET /api/news/feed   — Always available (local-safe). Returns grouped news
                       for all active holdings + watchlist, ordered by sector
                       then ticker.  Empty/no-news holdings are still listed so
                       the UI can show a meaningful empty state per holding.

GET /api/news/themes — Claude mode only. Heartbeat-gated; cached by headline
                       signature so re-opening the zone costs 0 extra tokens;
                       returns HTTP 503 when Claude is unreachable or fails.

GET /api/news/filings — Always available (local-safe). Recent SEC filings per
                       holding, straight from EDGAR. Only operating companies
                       file: funds and crypto are reported as non-filers rather
                       than as companies that happened to file nothing.
"""
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Holding
from app.services import holdings_repository
from app.services.ai_service import generate_news_themes, get_cached_claude_heartbeat
from app.services.edgar_service import get_cik, get_recent_filings
from app.services.news_service import (
    build_themes_snapshot,
    fetch_portfolio_news,
)
from app.services.stock_service import get_ticker_info, normalize_ticker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/news", tags=["news"])

# ── In-memory themes cache ─────────────────────────────────────────────────────
# Keyed by SHA-1 of the headline set — identical feeds cost 0 Claude tokens.
_THEMES_CACHE: dict[str, tuple[float, dict]] = {}
_THEMES_TTL = 30 * 60  # 30 min

# ── Filings timeline ──────────────────────────────────────────────────────────
_FILINGS_PER_HOLDING = 5
_FILINGS_WORKERS = 8


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _get_active_holdings(db: Session, portfolio_id: int = 1) -> list[Holding]:
    """Return the portfolio's active holdings as ORM rows, oldest first.

    What "active" means belongs to holdings_repository; this is only the name
    the two row-shaped endpoints below share, so their tests stub one seam here
    instead of reaching into the repository every module imports.
    """
    return holdings_repository.active(db, portfolio_id)


def _holding_info_brief(ticker: str) -> dict:
    """
    Fetch a minimal subset of yfinance .info for display purposes.
    Returns {company_name, sector} — fails gracefully to empty strings.
    """
    try:
        info = get_ticker_info(ticker)
        return {
            "company_name": (
                info.get("longName") or info.get("shortName") or ticker
            ),
            "sector": info.get("sector") or info.get("quoteType") or "",
        }
    except Exception:  # pylint: disable=broad-except
        return {"company_name": ticker, "sector": ""}


def _headlines_signature(news_by_ticker: dict[str, list[dict]]) -> str:
    """SHA-1 over the sorted headline set — themes cache key."""
    titles = sorted(
        item["title"]
        for items in news_by_ticker.values()
        for item in items
    )
    return hashlib.sha1(  # noqa: S324 — non-security digest
        "\n".join(titles).encode(), usedforsecurity=False
    ).hexdigest()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/feed")
def get_news_feed(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Grouped news feed for all active holdings + watchlist.
    Always available — no AI required, no heartbeat gate.
    Holdings are ordered by sector then watchlist flag then ticker so related
    companies cluster together in the UI.
    """
    holdings  = _get_active_holdings(db, portfolio_id)
    tickers   = [normalize_ticker(h.ticker) for h in holdings]

    news_by_ticker = fetch_portfolio_news(tickers) if tickers else {}

    enriched: list[dict] = []
    for h in holdings:
        ticker = normalize_ticker(h.ticker)
        brief  = _holding_info_brief(ticker)
        enriched.append({
            "ticker":       ticker,
            "company_name": brief["company_name"],
            "sector":       brief["sector"],
            "is_watchlist": bool(h.is_watchlist),
            "items":        news_by_ticker.get(ticker, []),
        })

    # Sector → watchlist flag → ticker (empty sector sorts last)
    enriched.sort(key=lambda h: (
        h["sector"] or "~",
        int(h["is_watchlist"]),
        h["ticker"],
    ))

    return {
        "holdings":     enriched,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.get("/themes")
def get_news_themes(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Claude-mode news themes: portfolio briefing + cross-holding clusters.
    Heartbeat-gated — returns 503 when Claude is unreachable.
    Cached by headline signature so re-opening the zone costs 0 extra tokens.
    """
    heartbeat = get_cached_claude_heartbeat()
    if not heartbeat.get("live"):
        raise HTTPException(
            status_code=503,
            detail="Claude AI is not reachable; news themes unavailable.",
        )

    # meta_map already returns ticker → position context, which is the shape
    # build_themes_snapshot reads, so this endpoint needs no ORM rows at all.
    holding_meta = holdings_repository.meta_map(db, portfolio_id)

    news_by_ticker = fetch_portfolio_news(list(holding_meta)) if holding_meta else {}

    sig   = _headlines_signature(news_by_ticker)
    now   = time.monotonic()
    cached = _THEMES_CACHE.get(sig)
    if cached and cached[0] > now:
        result = dict(cached[1])
        result["from_cache"] = True
        return result

    snapshot = build_themes_snapshot(holding_meta, news_by_ticker)

    try:
        themes_data = generate_news_themes(snapshot)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "news_themes: Claude call failed; exception_type=%s", type(exc).__name__
        )
        raise HTTPException(
            status_code=503,
            detail="News themes generation failed; Claude returned an error.",
        ) from exc

    result = {
        "briefing":     themes_data["briefing"],
        "themes":       themes_data["themes"],
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _THEMES_CACHE[sig] = (now + _THEMES_TTL, result)
    return result


@router.get("/filings")
def get_portfolio_filings(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """
    Recent SEC filings for every active holding — always available, no AI.

    Only operating companies have a CIK, so funds, crypto and most foreign
    listings are flagged ``is_filer: false`` instead of being shown as
    companies that filed nothing. EDGAR trouble degrades to empty timelines
    with ``degraded: true`` rather than an error page.
    """
    holdings = _get_active_holdings(db, portfolio_id)
    tickers = [normalize_ticker(h.ticker) for h in holdings]

    degraded = False

    def _filings_for(ticker: str) -> tuple[str, bool, list[dict]]:
        try:
            if not get_cik(ticker):
                return ticker, False, []
            return ticker, True, get_recent_filings(ticker, limit=_FILINGS_PER_HOLDING)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug(
                "Filing lookup failed; ticker=%s exception_type=%s",
                ticker,
                type(exc).__name__,
            )
            raise

    results: dict[str, tuple[bool, list[dict]]] = {}
    if tickers:
        # EDGAR throttles at the service layer; a pool just stops one slow
        # holding from stalling the rest.
        with ThreadPoolExecutor(max_workers=_FILINGS_WORKERS) as pool:
            for ticker, future in [
                (t, pool.submit(_filings_for, t)) for t in tickers
            ]:
                try:
                    _, is_filer, filings = future.result()
                    results[ticker] = (is_filer, filings)
                except Exception:  # pylint: disable=broad-except
                    degraded = True
                    results[ticker] = (True, [])

    enriched: list[dict] = []
    not_filers: list[str] = []
    for h in holdings:
        ticker = normalize_ticker(h.ticker)
        is_filer, filings = results.get(ticker, (True, []))
        if not is_filer:
            not_filers.append(ticker)
        brief = _holding_info_brief(ticker)
        enriched.append({
            "ticker":       ticker,
            "company_name": brief["company_name"],
            "sector":       brief["sector"],
            "is_watchlist": bool(h.is_watchlist),
            "is_filer":     is_filer,
            "filings":      filings,
        })

    # Holdings with fresh filings first; then filers; then the rest by ticker.
    enriched.sort(key=lambda h: (
        not h["filings"],
        not h["is_filer"],
        h["ticker"],
    ))

    return {
        "holdings":     enriched,
        "not_filers":   not_filers,
        "degraded":     degraded,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
