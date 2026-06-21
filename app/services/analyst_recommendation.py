"""
app/services/analyst_recommendation.py

Analyst consensus recommendation for portfolio holdings.
Primary provider: yfinance (Yahoo Finance consensus data).
Swap _fetch_from_yfinance() to replace the provider without touching callers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import yfinance as yf

from app.services.etf_quality import calculate_etf_quality_score
from app.services.holding_intelligence import get_static_holding_metadata
from app.services.security_type import SecurityType, classify_security

logger = logging.getLogger(__name__)

# Quote types that carry no stock analyst coverage.
_NO_ANALYST_COVERAGE_TYPES = {"cryptocurrency", "crypto", "fund"}

_REC_KEY_TO_ACTION: dict[str, str] = {
    "strong_buy":  "buy",
    "buy":         "buy",
    "hold":        "hold",
    "underperform": "sell",
    "sell":        "sell",
    "strong_sell": "sell",
}

_ACTION_LABEL: dict[str, str] = {
    "buy":       "Buy",
    "hold":      "Hold",
    "sell":      "Sell",
    "unavailable": "Unavailable",
    "etf-quality": "ETF Quality",
}


@dataclass
class AnalystRec:  # pylint: disable=too-many-instance-attributes
    ticker: str
    action: str                      # buy | hold | sell | unavailable | etf-quality
    label: str                       # Buy | Hold | Sell | Unavailable | ETF Quality: ...
    analyst_count: Optional[int]
    recommendation_mean: Optional[float]
    target_price: Optional[float]
    target_upside_pct: Optional[float]
    subtext: str                     # e.g. "18 analysts · PT +12%"
    source: str
    security_type: str = "STOCK"
    rating_type: str = "analyst"
    etf_quality: Optional[dict] = None


def _not_rated(ticker: str) -> AnalystRec:
    """Backward-compatible helper name for an unavailable analyst rating."""
    return AnalystRec(
        ticker=ticker,
        action="unavailable",
        label="Unavailable",
        analyst_count=None,
        recommendation_mean=None,
        target_price=None,
        target_upside_pct=None,
        subtext="Analyst rating unavailable",
        source="yfinance",
    )


def _etf_quality_rec(ticker: str, info: dict) -> AnalystRec:
    static = get_static_holding_metadata(ticker)
    data = {
        **static,
        **info,
        "ticker": ticker,
        "expense_ratio": (
            info.get("annualReportExpenseRatio")
            or info.get("expenseRatio")
            or info.get("netExpenseRatio")
            or static.get("expense_ratio")
        ),
        "aum": info.get("totalAssets") or info.get("netAssets"),
        "average_volume": info.get("averageVolume") or info.get("averageVolume10days"),
        "current_price": (
            info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice")
        ),
    }
    quality = calculate_etf_quality_score(data)
    label = f"ETF Quality: {quality['qualityLabel']}"
    subparts = []
    if quality["costLabel"] != "Unknown":
        subparts.append(f"{quality['costLabel']} cost")
    if quality["liquidityLabel"] != "Unknown":
        subparts.append(f"{quality['liquidityLabel']} liquidity")
    if quality["categoryRiskLabel"] != "Unknown":
        subparts.append(f"{quality['categoryRiskLabel']} risk")
    return AnalystRec(
        ticker=ticker,
        action="etf-quality",
        label=label,
        analyst_count=None,
        recommendation_mean=None,
        target_price=None,
        target_upside_pct=None,
        subtext=" · ".join(subparts) if subparts else "Insufficient ETF data",
        source="etf-quality",
        security_type="ETF",
        rating_type="etf_quality",
        etf_quality=quality,
    )


def _build_subtext(count: Optional[int], upside_pct: Optional[float]) -> str:
    parts: list[str] = []
    if count:
        parts.append(f"{count} analyst{'s' if count != 1 else ''}")
    if upside_pct is not None:
        sign = "+" if upside_pct >= 0 else ""
        parts.append(f"PT {sign}{upside_pct:.0f}%")
    return " · ".join(parts) if parts else "Analyst rating unavailable"


def _action_from_mean(mean: float) -> str:
    if mean <= 2.0:
        return "buy"
    if mean <= 3.5:
        return "hold"
    return "sell"


def _fetch_from_yfinance(ticker: str) -> AnalystRec:
    """
    Pull analyst consensus from Yahoo Finance.
    Returns ETF quality for ETFs and unavailable for missing stock analyst data.
    """
    info = yf.Ticker(ticker).info

    security_type = classify_security(ticker, info)
    if security_type == SecurityType.ETF:
        return _etf_quality_rec(ticker, info)

    quote_type = str(info.get("quoteType") or "").lower()
    if quote_type in _NO_ANALYST_COVERAGE_TYPES or security_type in {
        SecurityType.CRYPTO,
        SecurityType.CASH,
        SecurityType.UNKNOWN,
    }:
        return _not_rated(ticker)

    # Determine action from recommendationKey (preferred) or mean score (fallback)
    rec_key = str(info.get("recommendationKey") or "").lower()
    action = _REC_KEY_TO_ACTION.get(rec_key, "")

    if not action:
        mean_raw = info.get("recommendationMean")
        if mean_raw is None:
            return _not_rated(ticker)
        action = _action_from_mean(float(mean_raw))

    count = info.get("numberOfAnalystOpinions")
    count = int(count) if count is not None else None

    target_raw = info.get("targetMeanPrice") or info.get("targetMedianPrice")
    target = round(float(target_raw), 2) if target_raw is not None else None

    current = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
    upside_pct: Optional[float] = None
    if target is not None and current > 0:
        upside_pct = round((target - current) / current * 100, 1)

    mean_val = info.get("recommendationMean")
    mean_val = round(float(mean_val), 2) if mean_val is not None else None

    return AnalystRec(
        ticker=ticker,
        action=action,
        label=_ACTION_LABEL[action],
        analyst_count=count,
        recommendation_mean=mean_val,
        target_price=target,
        target_upside_pct=upside_pct,
        subtext=_build_subtext(count, upside_pct),
        source="yfinance",
    )


def get_analyst_recommendation(ticker: str) -> AnalystRec:
    """
    Return analyst consensus for a single ticker.
    Always returns a result — falls back to unavailable on any error.
    """
    ticker = ticker.upper()
    try:
        return _fetch_from_yfinance(ticker)
    except Exception as exc:
        logger.warning("Analyst rec fetch failed for %s: %s", ticker, exc)
        return _not_rated(ticker)


def rec_to_dict(rec: AnalystRec) -> dict:
    """Serialize AnalystRec to a JSON-safe dict."""
    return {
        "ticker": rec.ticker,
        "action": rec.action,
        "label": rec.label,
        "analyst_count": rec.analyst_count,
        "recommendation_mean": rec.recommendation_mean,
        "target_price": rec.target_price,
        "target_upside_pct": rec.target_upside_pct,
        "subtext": rec.subtext,
        "source": rec.source,
        "security_type": rec.security_type,
        "rating_type": rec.rating_type,
        "etf_quality": rec.etf_quality,
    }
