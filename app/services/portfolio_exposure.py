"""
Portfolio look-through exposure — aggregate sector, region, and theme overlap.
No network calls; uses holding_intelligence static/live metadata × allocation %.
"""
from __future__ import annotations

from typing import Optional

from app.services.holding_intelligence import get_holding_intelligence

_THEME_KEYWORDS: dict[str, list[str]] = {
    "US mega-cap tech": ["technology", "mega-cap", "nasdaq", "growth"],
    "US broad equity": ["broad", "s&p", "total market"],
    "Emerging markets": ["emerging", "em "],
    "Crypto": ["crypto", "bitcoin"],
    "Defense": ["defense", "aerospace"],
    "Energy transition": ["energy transition", "lithium", "clean energy"],
}


def _normalize_sector(name: str) -> str:
    return name.strip().lower()


def _aggregate_weights(
    holdings: list[dict],
    key: str,
) -> list[dict]:
    """Sum look-through weights from sector or country lists on each holding."""
    totals: dict[str, float] = {}
    for item in holdings:
        alloc = float(item.get("allocation_pct") or 0)
        if alloc <= 0:
            continue
        intel = item.get("intelligence") or {}
        for entry in intel.get(key) or []:
            name = str(entry.get("name") or "").strip()
            weight = float(entry.get("weight") or 0)
            if not name or weight <= 0:
                continue
            # Guard: individual holding's sector/country weights should be ≤100 %.
            # A value >100 usually means the source already multiplied by 100 twice.
            if weight > 100:
                weight = 100.0
            contribution = alloc * weight / 100.0
            totals[name] = totals.get(name, 0.0) + contribution
    rows = [{"name": k, "weight_pct": round(v, 1)} for k, v in totals.items()]
    # Individual look-through entries must not exceed total portfolio weight (100 %).
    rows = [r for r in rows if r["weight_pct"] > 0]
    for r in rows:
        if r["weight_pct"] > 100:
            r["weight_pct"] = 100.0
    rows.sort(key=lambda x: x["weight_pct"], reverse=True)
    return rows


def _detect_theme_overlap(sector_exposure: list[dict], holdings: list[dict]) -> list[dict]:
    """Flag themes where combined exposure exceeds a threshold."""
    themes: list[dict] = []
    sector_text = " ".join(_normalize_sector(s["name"]) for s in sector_exposure)

    tech_pct = sum(
        s["weight_pct"]
        for s in sector_exposure
        if "tech" in _normalize_sector(s["name"])
    )
    if tech_pct >= 25:
        themes.append({
            "theme": "US tech exposure",
            "weight_pct": round(tech_pct, 1),
            "label": f"~{tech_pct:.0f}% look-through US tech",
        })

    country_exposure = _aggregate_weights(holdings, "countries") if holdings else []
    us_pct = next(
        (c["weight_pct"] for c in country_exposure if "united states" in c["name"].lower()),
        0.0,
    )
    if us_pct >= 50:
        themes.append({
            "theme": "US equity dominance",
            "weight_pct": round(us_pct, 1),
            "label": f"~{us_pct:.0f}% look-through US exposure",
        })

    for theme_name, keywords in _THEME_KEYWORDS.items():
        if any(kw in sector_text for kw in keywords):
            match_pct = sum(
                s["weight_pct"]
                for s in sector_exposure
                if any(kw in _normalize_sector(s["name"]) for kw in keywords)
            )
            if match_pct >= 15 and theme_name not in {t["theme"] for t in themes}:
                themes.append({
                    "theme": theme_name,
                    "weight_pct": round(match_pct, 1),
                    "label": f"~{match_pct:.0f}% {theme_name.lower()}",
                })
    return themes[:5]


def _detect_duplicates(holdings: list[dict]) -> list[dict]:
    """Find overlapping top holdings and redundant broad ETFs."""
    underlying: dict[str, float] = {}
    broad_etfs: list[str] = []

    for item in holdings:
        alloc = float(item.get("allocation_pct") or 0)
        if alloc <= 0:
            continue
        ticker = str(item.get("ticker") or "").upper()
        intel = item.get("intelligence") or {}
        coverage = intel.get("coverage_type") or ""
        if coverage == "etf-broad" and alloc >= 5:
            broad_etfs.append(ticker)
        for th in intel.get("top_holdings") or []:
            sym = str(th.get("ticker") or "").upper()
            weight = float(th.get("weight") or 0)
            if sym and weight > 0:
                contribution = alloc * weight / 100.0
                underlying[sym] = underlying.get(sym, 0.0) + contribution

    duplicates: list[dict] = []
    if len(broad_etfs) >= 2:
        duplicates.append({
            "type": "broad_etf_overlap",
            "tickers": broad_etfs,
            "message": (
                f"Multiple broad US ETFs ({', '.join(broad_etfs)}) "
                "— look-through overlap is high"
            ),
        })

    held_tickers = {h.get("ticker", "").upper() for h in holdings}
    for sym, pct in sorted(underlying.items(), key=lambda x: -x[1]):
        if pct >= 8 and sym not in held_tickers:
            duplicates.append({
                "type": "hidden_single_name",
                "ticker": sym,
                "weight_pct": round(pct, 1),
                "message": f"~{pct:.0f}% portfolio exposure to {sym} via ETF look-through",
            })
    return duplicates[:8]


def _concentration_hhi(sector_exposure: list[dict]) -> float:
    """Herfindahl index on sector weights (0–1 scale, higher = more concentrated)."""
    if not sector_exposure:
        return 0.0
    total = sum(s["weight_pct"] for s in sector_exposure)
    if total <= 0:
        return 0.0
    shares = [s["weight_pct"] / total for s in sector_exposure]
    return round(sum(s * s for s in shares), 3)


def build_portfolio_exposure(
    holdings: list[dict],
    *,
    quotes: Optional[dict] = None,
) -> dict:
    """
    Compute look-through portfolio exposure.

    Each holding dict: {ticker, allocation_pct, is_watchlist?}
    """
    quotes = quotes or {}
    enriched: list[dict] = []
    for item in holdings:
        if item.get("is_watchlist"):
            continue
        ticker = str(item.get("ticker") or "").upper()
        alloc = float(item.get("allocation_pct") or 0)
        if alloc <= 0:
            continue
        stock_data = quotes.get(ticker)
        intel = get_holding_intelligence(ticker, stock_data=stock_data)
        from app.services.holding_intelligence import intelligence_to_dict
        enriched.append({
            "ticker": ticker,
            "allocation_pct": alloc,
            "intelligence": intelligence_to_dict(intel),
        })

    sector_exposure = _aggregate_weights(enriched, "sectors")
    country_exposure = _aggregate_weights(enriched, "countries")
    theme_overlap = _detect_theme_overlap(sector_exposure, enriched)
    duplicate_flags = _detect_duplicates(enriched)
    hhi = _concentration_hhi(sector_exposure)

    flags: list[str] = []
    if hhi >= 0.25:
        flags.append("Sector concentration is elevated — book is not very diversified")
    if len(duplicate_flags) >= 2:
        flags.append("Hidden duplication detected across holdings")

    # Per-holding sector contributions: {ticker: {sector_name: contribution_pct}}
    holding_sector_contributions: dict[str, dict[str, float]] = {}
    for item in enriched:
        ticker = item["ticker"]
        alloc = float(item.get("allocation_pct") or 0)
        sectors = (item.get("intelligence") or {}).get("sectors") or []
        contribs: dict[str, float] = {}
        for s in sectors:
            name = str(s.get("name") or "").strip()
            weight = float(s.get("weight") or 0)
            if not name or weight <= 0:
                continue
            contribution = round(alloc * min(weight, 100.0) / 100.0, 2)
            if contribution > 0:
                contribs[name] = round(contribs.get(name, 0.0) + contribution, 2)
        holding_sector_contributions[ticker] = contribs

    return {
        "sector_exposure": sector_exposure[:11],
        "country_exposure": country_exposure[:12],
        "theme_overlap": theme_overlap,
        "duplicate_flags": duplicate_flags,
        "concentration_hhi": hhi,
        "flags": flags,
        "holding_count": len(enriched),
        "holding_sector_contributions": holding_sector_contributions,
    }


def exposure_context_for_ticker(
    portfolio_exposure: dict,
    ticker: str,
) -> dict | None:
    """Return per-ticker exposure context when book overlap is relevant."""
    if not portfolio_exposure:
        return None

    themes = portfolio_exposure.get("theme_overlap") or []
    sectors = portfolio_exposure.get("sector_exposure") or []
    context: dict = {"themes": themes[:3], "relevant_sectors": sectors[:3]}

    # Find if this ticker contributes to a crowded theme
    intel = get_holding_intelligence(ticker)
    ticker_sectors = {_normalize_sector(s.name) for s in intel.sectors}
    crowded = []
    for theme in themes:
        if theme.get("weight_pct", 0) >= 30:
            crowded.append(theme)
    if crowded:
        context["crowded_themes"] = crowded
        context["add_penalty_reason"] = crowded[0].get("label", "")

    for sec in sectors:
        if sec.get("weight_pct", 0) >= 35:
            sec_name = _normalize_sector(sec["name"])
            if any(sec_name in ts or ts in sec_name for ts in ticker_sectors):
                context["sector_already_heavy"] = sec
                break
    return context if context.get("crowded_themes") or context.get("sector_already_heavy") else None
