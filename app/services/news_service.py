"""
app/services/news_service.py

News fetching, normalization, dedup, and theme-snapshot building for the News
zone.  Articles come from the ``market_data`` seam; everything downstream of the
raw payload — the two article shapes Yahoo alternates between, dedup across a
portfolio, and the Claude snapshot — lives here.  Designed to be fully useful
without any AI dependency: Claude is an optional enrichment layer added by the
router.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services import market_data, market_hours
from app.services.log_safety import sanitize_for_log
from app.services.stock_service import (
    normalize_ticker,
    ticker_shape_is_safe,
)
from app.services.ttl_cache import ttl_cache

logger = logging.getLogger(__name__)

# ── Cache window ──────────────────────────────────────────────────────────────
_NEWS_TTL_OPEN   = 15 * 60   # 15 min while market open
_NEWS_TTL_CLOSED = 60 * 60   # 60 min while market closed

_MAX_WORKERS  = 8
_FETCH_TIMEOUT = 20.0  # seconds for the concurrent fan-out


def _news_ttl() -> float:
    return _NEWS_TTL_OPEN if market_hours.is_open() else _NEWS_TTL_CLOSED


# ── Normalization ─────────────────────────────────────────────────────────────

def _thumbnail_url(content: dict) -> str | None:
    """
    Extract the best available thumbnail URL from a yfinance content dict.
    Prefers the highest-width entry in 'thumbnail.resolutions'; falls back
    to a plain 'url' field.
    """
    thumb = content.get("thumbnail")
    if not thumb:
        return None
    resolutions = thumb.get("resolutions")
    if isinstance(resolutions, list) and resolutions:
        best = max(resolutions, key=lambda r: r.get("width", 0))
        return best.get("url") or None
    return thumb.get("url") or None


def _article_url(content: dict) -> str:
    """Return the best available article URL from a yfinance content dict."""
    for key in ("canonicalUrl", "clickThroughUrl"):
        val = content.get(key)
        if isinstance(val, dict):
            u = val.get("url") or ""
        else:
            u = str(val) if val else ""
        if u:
            return u
    return ""


def _normalize_item(item: dict, ticker: str) -> dict | None:
    """
    Flatten one raw yfinance news item into a normalized dict.
    Returns None when the item lacks a usable title.
    yfinance wraps the payload under an 'content' key; we handle both shapes.
    """
    content = item.get("content") or item

    title = str(content.get("title") or "").strip()
    if not title:
        return None

    article_id = str(content.get("id") or item.get("id") or "").strip()
    url        = _article_url(content)
    # Stable dedup key: prefer explicit id, then url, then title as last resort.
    dedup_key  = article_id or url or title

    provider = content.get("provider") or {}
    source   = str(provider.get("displayName") or "").strip() or "Yahoo Finance"

    summary = str(
        content.get("summary") or content.get("description") or ""
    ).strip()

    return {
        "ticker":        ticker,
        "id":            article_id,
        "dedup_key":     dedup_key,
        "title":         title,
        "summary":       summary,
        "url":           url,
        "source":        source,
        "published_at":  str(content.get("pubDate") or ""),
        "thumbnail_url": _thumbnail_url(content),
    }


# ── Single-ticker fetch ───────────────────────────────────────────────────────

@ttl_cache(ttl=_news_ttl, key=normalize_ticker, cache_when=bool)
def _cached_ticker_news(symbol: str) -> list[dict]:
    """Normalized, newest-first articles for one already-validated symbol.

    An empty result is never remembered. The seam reports an unreachable Yahoo
    and a genuinely quiet symbol the same way — both are ``[]`` — so the only
    honest reading of an empty list is "ask again", and pinning it would risk
    showing a whole window of "no news" after one transient failure. The cost is
    that a quiet symbol is re-asked; the alternative costs correctness.
    """
    items: list[dict] = []
    for raw in market_data.get_news(symbol):
        normalized = _normalize_item(raw, symbol)
        if normalized:
            items.append(normalized)
    # Sort newest-first; ISO-8601 strings compare correctly lexicographically.
    items.sort(key=lambda a: a["published_at"], reverse=True)
    logger.debug("news_service: fetched %d articles for %s", len(items), symbol)
    return items


def fetch_ticker_news(ticker: str) -> list[dict]:
    """
    Fetch and cache news for a single ticker symbol.
    Returns a list of normalized article dicts (may be empty on failure).
    Validates the ticker shape before any network call — and before the cache,
    so a hostile symbol can never claim an entry.
    """
    symbol = normalize_ticker(ticker)
    if not ticker_shape_is_safe(symbol):
        logger.warning(
            "news_service: unsafe ticker shape skipped; ticker=%s",
            sanitize_for_log(ticker),
        )
        return []

    try:
        return _cached_ticker_news(symbol)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "news_service: fetch failed; ticker=%s exception_type=%s",
            symbol, type(exc).__name__,
        )
        return []


# ── Portfolio-level concurrent fetch ─────────────────────────────────────────

def fetch_portfolio_news(tickers: list[str]) -> dict[str, list[dict]]:
    """
    Concurrently fetch news for multiple tickers.
    Returns {ticker: [items...]} with global dedup applied across the whole set.
    One bad ticker never blocks or crashes the others.
    """
    if not tickers:
        return {}

    safe_tickers = [normalize_ticker(t) for t in tickers if ticker_shape_is_safe(t)]
    if not safe_tickers:
        return {}

    results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(safe_tickers))) as pool:
        futures = {pool.submit(fetch_ticker_news, t): t for t in safe_tickers}
        try:
            for future in as_completed(futures, timeout=_FETCH_TIMEOUT):
                ticker = futures[future]
                try:
                    results[ticker] = future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug(
                        "news_service: portfolio future exception; ticker=%s exception_type=%s",
                        ticker, type(exc).__name__,
                    )
                    results[ticker] = []
        except TimeoutError:
            logger.warning(
                "news_service: portfolio fetch timed out after %ss; %d/%d tickers completed",
                _FETCH_TIMEOUT, len(results), len(safe_tickers),
            )
            for t in safe_tickers:
                results.setdefault(t, [])

    # Global dedup: if the same article appears under multiple tickers keep only
    # the first occurrence (in the order tickers were supplied) and drop the rest.
    seen_keys: set[str] = set()
    for ticker in safe_tickers:
        items    = results.get(ticker, [])
        deduped: list[dict] = []
        for item in items:
            key = item["dedup_key"]
            if key and key not in seen_keys:
                seen_keys.add(key)
                deduped.append(item)
        results[ticker] = deduped

    return results


# ── Theme snapshot ─────────────────────────────────────────────────────────────

def build_themes_snapshot(
    holding_meta: dict[str, dict],
    news_by_ticker: dict[str, list[dict]],
) -> dict:
    """
    Build a compact snapshot dict for Claude's news-themes call.
    Keeps payload small: per-holding context + ≤3 headlines each.
    Watchlist items are flagged so Claude weights them appropriately.
    """
    holdings_summary = []
    for ticker, meta in holding_meta.items():
        headlines = [
            item["title"]
            for item in news_by_ticker.get(ticker, [])[:3]
        ]
        entry: dict = {
            "ticker":       ticker,
            "is_watchlist": bool(meta.get("is_watchlist")),
            "headlines":    headlines,
        }
        weight = meta.get("weight_pct")
        if weight is not None:
            entry["weight_pct"] = round(float(weight), 1)
        holdings_summary.append(entry)

    return {"holdings": holdings_summary}
