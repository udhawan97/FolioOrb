"""
ETF quality scoring from ETF-specific data.

The scorer only uses fields present in provider/static metadata. When too few
inputs are available, it returns Insufficient Data instead of guessing.
"""
from __future__ import annotations

from typing import Any, Mapping


_PROFILE_OVERRIDES: dict[str, dict[str, Any]] = {
    "VOO": {"category": "broad", "concentration_level": "low", "holdings_count": 500},
    "VTI": {"category": "broad", "concentration_level": "very-low", "holdings_count": 3500},
    "VT": {"category": "broad", "concentration_level": "very-low", "holdings_count": 9500},
    "IOO": {"category": "broad", "concentration_level": "low", "holdings_count": 100},
    "VO": {"category": "broad", "concentration_level": "low", "holdings_count": 300},
    "VB": {"category": "broad", "concentration_level": "low", "holdings_count": 1400},
    "VXF": {"category": "broad", "concentration_level": "low", "holdings_count": 3000},
    "IJH": {"category": "broad", "concentration_level": "low", "holdings_count": 400},
    "IJR": {"category": "broad", "concentration_level": "low", "holdings_count": 600},
    "QQQ": {"category": "growth", "concentration_level": "medium", "holdings_count": 100},
    "QQQM": {"category": "growth", "concentration_level": "medium", "holdings_count": 100},
    "SCHD": {"category": "dividend", "concentration_level": "medium", "holdings_count": 100},
    "VIG": {"category": "dividend", "concentration_level": "low", "holdings_count": 300},
    "VIGI": {"category": "international", "concentration_level": "low", "holdings_count": 300},
    "CGDV": {"category": "dividend", "concentration_level": "medium"},
    "GARP": {"category": "factor", "concentration_level": "medium"},
    "IEMG": {"category": "international", "concentration_level": "low", "holdings_count": 2500},
    "VEA": {"category": "international", "concentration_level": "low", "holdings_count": 4000},
    "HEFA": {"category": "international", "concentration_level": "low", "holdings_count": 1400},
    "SMIN": {"category": "international", "concentration_level": "medium"},
    "INDA": {"category": "international", "concentration_level": "medium"},
    "NFTY": {"category": "international", "concentration_level": "high"},
    "PIN": {"category": "international", "concentration_level": "medium"},
    "WSML": {"category": "international", "concentration_level": "very-low"},
    "IXJ": {"category": "sector", "concentration_level": "medium"},
    "PPA": {"category": "sector", "concentration_level": "high"},
    "ITA": {"category": "sector", "concentration_level": "medium"},
    "SHLD": {"category": "sector", "concentration_level": "high"},
    "SMH": {"category": "sector", "concentration_level": "high"},
    "QTUM": {"category": "thematic", "concentration_level": "medium"},
    "SETM": {"category": "thematic", "concentration_level": "medium"},
    "URA": {"category": "thematic", "concentration_level": "high"},
    "NUKZ": {"category": "thematic", "concentration_level": "high"},
    "JEPQ": {"category": "options-income", "concentration_level": "medium", "options_income": True},
    "IBIT": {
        "category": "crypto", "concentration_level": "high",
        "crypto_linked": True, "holdings_count": 1,
    },
    "BTGD": {
        "category": "crypto", "concentration_level": "high",
        "crypto_linked": True, "holdings_count": 1,
    },
}

_CONCENTRATION_LABEL: dict[str, str] = {
    "very-low": "Broad", "low": "Broad",
    "medium": "Moderate", "high": "Concentrated",
}

_DIVERSIFICATION_SCORE: dict[str, int] = {"Broad": 15, "Moderate": 8, "Concentrated": 2}

_CATEGORY_RISK_PENALTY: dict[str, int] = {"Speculative": 25, "High": 12, "Moderate": 5}


def _first_number(data: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_text(data: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def _cost_label(expense_ratio: float | None) -> str:
    if expense_ratio is None:
        return "Unknown"
    if expense_ratio <= 0.0015:
        return "Low"
    if expense_ratio <= 0.006:
        return "Medium"
    return "High"


def _liquidity_label(avg_volume: float | None, aum: float | None, spread: float | None) -> str:
    if avg_volume is None and aum is None and spread is None:
        return "Unknown"
    score = 0
    if avg_volume is not None:
        score += 2 if avg_volume >= 1_000_000 else 1 if avg_volume >= 100_000 else 0
    if aum is not None:
        score += 2 if aum >= 10_000_000_000 else 1 if aum >= 1_000_000_000 else 0
    if spread is not None:
        score += 2 if spread <= 0.001 else 1 if spread <= 0.004 else 0
    if score >= 4:
        return "High"
    if score >= 2:
        return "Medium"
    return "Low"


def _diversification_label(concentration: str, holdings_count: float | None) -> str:
    if concentration in _CONCENTRATION_LABEL:
        return _CONCENTRATION_LABEL[concentration]
    if holdings_count is None:
        return "Unknown"
    if holdings_count >= 300:
        return "Broad"
    if holdings_count >= 75:
        return "Moderate"
    return "Concentrated"


def _category_risk_label(data: Mapping[str, Any], category: str, concentration: str) -> str:
    if data.get("leverage") or data.get("inverse") or data.get("crypto_linked"):
        return "Speculative"
    if data.get("options_income") or category in {"options-income", "sector", "thematic"}:
        return "High"
    if category in {"international", "growth"} or concentration == "medium":
        return "Moderate"
    if concentration == "high":
        return "High"
    return "Low" if category else "Unknown"


def _top10_from_holdings(
    top_holdings: list,
    top10_weight: float | None,
) -> float | None:
    if top10_weight is not None or not isinstance(top_holdings, list) or not top_holdings:
        return top10_weight
    weights = []
    for holding in top_holdings[:10]:
        if isinstance(holding, Mapping):
            weight = _first_number(holding, "weight", "holdingPercent")
            if weight is not None:
                weights.append(weight * 100 if weight <= 1 else weight)
    return sum(weights) if weights else None


def _list_missing_fields(  # pylint: disable=too-many-positional-arguments
    expense_ratio: float | None,
    aum: float | None,
    spread: float | None,
    avg_volume: float | None,
    holdings_count: float | None,
    top10_weight: float | None,
    tracking: float | None,
) -> list[str]:
    checks = [
        (expense_ratio, "expenseRatio"),
        (aum, "aum"),
        (spread, "bidAskSpread"),
        (avg_volume, "averageVolume"),
        (holdings_count, "holdingsCount"),
        (top10_weight, "top10HoldingsWeight"),
        (tracking, "trackingDifference"),
    ]
    return [name for value, name in checks if value is None]


def _quality_score_and_label(  # pylint: disable=too-many-positional-arguments
    expense_ratio: float | None,
    aum: float | None,
    spread: float | None,
    avg_volume: float | None,
    diversification: str,
    top10_weight: float | None,
    tracking: float | None,
    category_risk: str,
) -> tuple[int, str]:
    score = 40
    if expense_ratio is not None:
        score += 20 if expense_ratio <= 0.0015 else 14 if expense_ratio <= 0.006 else 6
    if aum is not None:
        score += 15 if aum >= 10_000_000_000 else 10 if aum >= 1_000_000_000 else 4
    if spread is not None:
        score += 10 if spread <= 0.001 else 6 if spread <= 0.004 else 1
    if avg_volume is not None:
        score += 10 if avg_volume >= 1_000_000 else 6 if avg_volume >= 100_000 else 2
    score += _DIVERSIFICATION_SCORE.get(diversification, 0)
    if top10_weight is not None:
        score += 8 if top10_weight <= 35 else 4 if top10_weight <= 55 else 0
    if tracking is not None:
        score += 7 if abs(tracking) <= 0.001 else 3 if abs(tracking) <= 0.005 else 0
    score -= _CATEGORY_RISK_PENALTY.get(category_risk, 0)
    score = max(0, min(100, round(score)))
    label = next(
        (lbl for threshold, lbl in [(80, "Strong"), (65, "Good"), (45, "Fair")]
         if score >= threshold),
        "Speculative",
    )
    if category_risk == "Speculative":
        label = "Speculative"
    elif category_risk == "High" and label == "Strong":
        label = "Good"
    return score, label


def calculate_etf_quality_score(etf_data: Mapping[str, Any]) -> dict[str, Any]:
    """Return ETF quality labels, score, explanation bullets, and missing fields."""
    ticker = str(etf_data.get("ticker") or "").upper()
    data = {**_PROFILE_OVERRIDES.get(ticker, {}), **dict(etf_data)}

    expense_ratio = _first_number(data, "expenseRatio", "expense_ratio", "annualReportExpenseRatio")
    aum = _first_number(data, "aum", "totalAssets", "total_assets", "netAssets")
    bid = _first_number(data, "bid")
    ask = _first_number(data, "ask")
    price = _first_number(data, "current_price", "currentPrice", "regularMarketPrice", "navPrice")
    spread = _first_number(data, "bidAskSpread", "bid_ask_spread", "bid_ask_spread_pct")
    if spread is None and bid is not None and ask is not None and price and ask >= bid:
        spread = (ask - bid) / price
    avg_volume = _first_number(data, "averageVolume", "average_volume", "averageVolume10days")
    holdings_count = _first_number(data, "holdingsCount", "holdings_count")
    top10_weight = _first_number(data, "top10HoldingsWeight", "top_10_holdings_weight")
    tracking = _first_number(data, "trackingDifference", "trackingError", "tracking_error")
    category = _first_text(data, "category", "categoryName", "coverage_type").lower()
    concentration = _first_text(data, "concentration_level").lower()
    top_holdings = data.get("top_holdings") or data.get("holdings") or []
    top10_weight = _top10_from_holdings(top_holdings, top10_weight)

    meaningful = [
        expense_ratio is not None, aum is not None, spread is not None,
        avg_volume is not None, holdings_count is not None, top10_weight is not None,
        tracking is not None, bool(category), bool(concentration),
    ]
    missing_fields = _list_missing_fields(
        expense_ratio, aum, spread, avg_volume, holdings_count, top10_weight, tracking
    )

    cost = _cost_label(expense_ratio)
    liquidity = _liquidity_label(avg_volume, aum, spread)
    diversification = _diversification_label(concentration, holdings_count)
    concentration_risk = {
        "very-low": "Low", "low": "Low", "medium": "Medium", "high": "High",
    }.get(concentration, "Unknown")
    category_risk = _category_risk_label(data, category, concentration)

    if sum(meaningful) < 3:
        return {
            "qualityLabel": "Insufficient Data",
            "score": None,
            "costLabel": cost,
            "liquidityLabel": liquidity,
            "diversificationLabel": diversification,
            "concentrationRiskLabel": concentration_risk,
            "categoryRiskLabel": category_risk,
            "explanationBullets": ["Insufficient ETF data to score quality."],
            "missingFields": missing_fields,
        }

    score, label = _quality_score_and_label(
        expense_ratio, aum, spread, avg_volume,
        diversification, top10_weight, tracking, category_risk,
    )

    bullets = [
        f"Cost is {cost.lower()}." if cost != "Unknown"
        else "Expense ratio is unavailable.",
        f"Liquidity is {liquidity.lower()}." if liquidity != "Unknown"
        else "Liquidity data is incomplete.",
        f"Diversification is {diversification.lower()}." if diversification != "Unknown"
        else "Diversification data is incomplete.",
        f"Category risk is {category_risk.lower()}." if category_risk != "Unknown"
        else "Category risk is unclear.",
    ]

    return {
        "qualityLabel": label,
        "score": score,
        "costLabel": cost,
        "liquidityLabel": liquidity,
        "diversificationLabel": diversification,
        "concentrationRiskLabel": concentration_risk,
        "categoryRiskLabel": category_risk,
        "explanationBullets": bullets,
        "missingFields": missing_fields,
    }
