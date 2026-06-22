"""
app/services/move_explainer.py
Explains why a holding moved today using market data, volume, and recent news.
Every explanation is grounded in retrieved data — no invented reasons.
Benchmarks are chosen per-holding, not defaulted to SPY/QQQ for everything.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf

from app.services.security_type import SecurityType, classify_security

logger = logging.getLogger(__name__)

SECTOR_ETF_MAP: dict[str, str] = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
    "Telecommunications": "XLC",
}

# Per-ticker benchmark configuration.
# "primary": the most relevant benchmark (fetched and shown prominently).
# "suppress_spy": hide SPY from pills/explanation when not relevant.
# "suppress_qqq": hide QQQ when the holding has no Nasdaq exposure.
_TICKER_BENCHMARKS: dict[str, dict] = {
    "IBIT":  {"primary": "BTC-USD", "label": "Bitcoin",
              "suppress_spy": True, "suppress_qqq": True},
    "VT":    {"primary": "ACWI",    "label": "Global Equities (ACWI)",   "suppress_qqq": True},
    "IEMG":  {"primary": "EEM",     "label": "Emerging Markets (EEM)",
              "suppress_qqq": True, "suppress_spy": True},
    "ITA":   {"primary": "XAR",     "label": "Aerospace/Defense (XAR)",  "suppress_qqq": True},
    "QTUM":  {"primary": "QQQ",     "label": "Nasdaq 100 (QQQ)",         "suppress_spy": True},
    "VOO":   {"primary": "SPY",     "label": "S&P 500 (SPY)",            "suppress_qqq": True},
    "NOW":   {"primary": "IGV",     "label": "Software Sector (IGV)"},
    "CGDV":  {"primary": "SCHD",    "label": "Dividend Value (SCHD)",    "suppress_qqq": True},
    "SETM":  {"primary": "LIT",     "label": "Lithium/Battery (LIT)",
              "suppress_spy": True, "suppress_qqq": True},
    "WSML":  {"primary": "IWM",     "label": "Global Small Cap (IWM)",   "suppress_qqq": True},
}

DRIVER_ICONS: dict[str, str] = {
    "market": "bi-globe2",
    "sector": "bi-diagram-3",
    "earnings": "bi-calendar-event-fill",
    "news": "bi-newspaper",
    "volume": "bi-bar-chart-fill",
    "filing": "bi-file-earmark-text-fill",
    "etf-index": "bi-stack",
    "holdings": "bi-list-task",
    "macro": "bi-graph-up-arrow",
    "unclear": "bi-question-circle",
}


@dataclass
class MoveDriver:
    driver_type: str
    description: str
    magnitude: str  # strong | moderate | weak
    icon: str
    evidence_url: Optional[str] = None


@dataclass
class NewsCatalyst:
    title: str
    source: str
    url: str
    published_at: str


@dataclass
class FilingCatalyst:
    filing_type: str
    title: str
    url: str
    filed_at: str


@dataclass
class MacroContext:  # pylint: disable=too-many-instance-attributes
    spy_change_pct: float
    qqq_change_pct: float
    sector_etf: Optional[str]
    sector_etf_change_pct: Optional[float]
    # Per-holding primary benchmark (overrides SPY/QQQ when relevant)
    primary_benchmark: Optional[str] = None
    primary_benchmark_label: Optional[str] = None
    primary_benchmark_chg: Optional[float] = None
    suppress_spy: bool = False
    suppress_qqq: bool = False


@dataclass
class HoldingMoveSummary:  # pylint: disable=too-many-instance-attributes
    ticker: str
    day_change_pct: float
    day_change_dollar: float
    attribution_type: str  # see _attribute() for possible values
    drivers: list = field(default_factory=list)
    confidence: str = "Low"   # Low | Medium | High
    news: list = field(default_factory=list)
    filings: list = field(default_factory=list)
    macro_context: Optional[MacroContext] = None
    explanation_text: str = ""
    is_etf: bool = False
    volume_vs_avg: Optional[float] = None


def _day_change_pct(ticker: str) -> float:
    try:
        info = yf.Ticker(ticker).info
        current = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")
            or 0
        )
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose") or 0
        if prev > 0 and current > 0:
            return round((current - prev) / prev * 100, 2)
    except Exception:
        pass
    return 0.0


# Per-ticker daily-change cache so batch contribution fetches don't spam yfinance.
_HOLDING_CHANGE_CACHE: dict[str, tuple[float, float]] = {}  # ticker → (pct, monotonic_ts)
_HOLDING_CACHE_TTL = 300.0  # 5 minutes


def _day_change_pct_cached(ticker: str) -> float:
    now = time.monotonic()
    entry = _HOLDING_CHANGE_CACHE.get(ticker)
    if entry and now - entry[1] < _HOLDING_CACHE_TTL:
        return entry[0]
    pct = _day_change_pct(ticker)
    _HOLDING_CHANGE_CACHE[ticker] = (pct, now)
    return pct


def compute_contribution_breakdown(
    top_holdings: list[dict],
    *,
    preloaded_changes: dict[str, float] | None = None,
    max_workers: int = 10,
    timeout: float = 8.0,
) -> list[dict]:
    """
    Return weight-adjusted contribution (in percentage points) for each holding.

    Pass preloaded_changes when prices were already fetched in batch (avoids redundant
    network calls). Falls back to concurrent yfinance fetches for any ticker not covered.
    """
    if not top_holdings:
        return []

    changes: dict[str, float] = dict(preloaded_changes or {})
    missing = [h["ticker"] for h in top_holdings if h["ticker"] not in changes]

    if missing:
        try:
            with ThreadPoolExecutor(max_workers=min(max_workers, len(missing))) as pool:
                futures = {pool.submit(_day_change_pct_cached, t): t for t in missing}
                done = as_completed(futures, timeout=timeout)
                for future in done:
                    t = futures[future]
                    try:
                        changes[t] = future.result()
                    except Exception:
                        changes[t] = 0.0
        except Exception:
            pass  # use what we have; missing tickers get 0.0 below

    results = []
    for h in top_holdings:
        t = h["ticker"]
        w = float(h.get("weight") or 0)
        chg = changes.get(t, 0.0)
        results.append({
            "ticker": t,
            "name": h.get("name", t),
            "weight": w,
            "day_change_pct": round(chg, 2),
            "contribution_pp": round(w / 100.0 * chg, 4),
        })

    results.sort(key=lambda x: abs(x["contribution_pp"]), reverse=True)
    return results


def get_benchmark_data() -> dict[str, float]:
    """Fetch SPY and QQQ day change pct. Call once per batch to share across holdings."""
    return {
        "SPY": _day_change_pct("SPY"),
        "QQQ": _day_change_pct("QQQ"),
    }


def _primary_benchmark_chg(
    ticker: str, cache: dict[str, float]
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """
    Return (benchmark_ticker, label, change_pct) for a ticker's primary benchmark.
    Uses cache to avoid redundant API calls across holdings.
    """
    cfg = _TICKER_BENCHMARKS.get(ticker)
    if not cfg:
        return None, None, None
    bm = cfg["primary"]
    label = cfg["label"]
    if bm not in cache:
        cache[bm] = _day_change_pct(bm)
    return bm, label, cache[bm]


def _sector_etf_change(sector: str) -> tuple[Optional[str], Optional[float]]:
    etf = SECTOR_ETF_MAP.get(sector)
    if not etf:
        return None, None
    return etf, _day_change_pct(etf)


def _extract_news(stock: yf.Ticker) -> list[NewsCatalyst]:
    results: list[NewsCatalyst] = []
    try:
        for item in (stock.news or [])[:5]:
            try:
                content = item.get("content", {}) or {}
                if content:
                    title = content.get("title", "")
                    source = (content.get("provider") or {}).get("displayName", "")
                    url = (content.get("canonicalUrl") or {}).get("url", "")
                    pub = str(content.get("pubDate", ""))
                else:
                    title = item.get("title", "")
                    source = item.get("publisher", "")
                    url = item.get("link", "")
                    pub = str(item.get("providerPublishTime", ""))
                if title:
                    results.append(NewsCatalyst(
                        title=title, source=source, url=url, published_at=pub
                    ))
            except Exception:
                continue
    except Exception:
        pass
    return results


def _earnings_near(stock: yf.Ticker) -> tuple[bool, Optional[str]]:
    try:
        cal = stock.calendar
        if cal is None:
            return False, None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        dates = []

        if hasattr(cal, "loc"):  # pandas DataFrame (older yfinance)
            try:
                val = cal.loc["Earnings Date"]
                dates = list(val) if hasattr(val, "__iter__") else [val]
            except (KeyError, Exception):
                return False, None
        elif isinstance(cal, dict):
            raw = cal.get("Earnings Date", [])
            dates = raw if isinstance(raw, list) else [raw]

        for d in dates:
            try:
                if hasattr(d, "to_pydatetime"):
                    d = d.to_pydatetime().replace(tzinfo=None)
                elif not hasattr(d, "year"):
                    continue
                if abs((d - now).days) <= 3:
                    return True, d.strftime("%b %d")
            except Exception:
                continue
    except Exception:
        pass
    return False, None


def _attribute(  # pylint: disable=too-many-positional-arguments,too-many-return-statements
    ticker_chg: float,
    spy_chg: float,
    sector_chg: Optional[float],
    has_news: bool,
    high_vol: bool,
    near_earnings: bool,
) -> tuple[str, str]:
    """Algorithmic attribution. Returns (attribution_type, confidence)."""
    alpha_spy = ticker_chg - spy_chg
    alpha_sector = (ticker_chg - sector_chg) if sector_chg is not None else None

    company_specific = abs(alpha_spy) > 1.5
    market_explains = abs(alpha_spy) <= 0.5
    sector_explains = alpha_sector is not None and abs(alpha_sector) <= 0.5

    if near_earnings:
        return "earnings-driven", "High" if (high_vol or has_news) else "Medium"

    if company_specific:
        if has_news and high_vol:
            return "company-specific", "High"
        if has_news or high_vol:
            return "company-specific", "Medium"
        return "company-specific", "Low"

    if sector_explains:
        return "sector-driven", "Medium" if abs(sector_chg or 0) > 0.3 else "Low"

    if market_explains:
        return "market-driven", "Medium" if abs(spy_chg) > 0.3 else "Low"

    return "mixed", "Low"


def explain_move(  # pylint: disable=too-many-branches,too-many-statements
    stock_data: dict,
    shared_benchmarks: Optional[dict] = None,
    _benchmark_cache: Optional[dict] = None,
) -> HoldingMoveSummary:
    """
    Explain why this holding moved today.

    Pass shared_benchmarks={SPY: pct, QQQ: pct} from get_benchmark_data() to
    avoid refetching those across multiple holdings.  _benchmark_cache is a
    mutable dict shared across calls to cache per-ticker primary benchmarks.
    """
    ticker = str(stock_data.get("ticker", "UNKNOWN")).upper()
    day_chg_pct = float(stock_data.get("day_change_pct") or 0)
    day_chg_dollar = float(stock_data.get("day_change") or 0)
    sector = str(stock_data.get("sector") or "N/A")
    security_type = classify_security(ticker, stock_data)
    is_etf = security_type == SecurityType.ETF

    bm = shared_benchmarks if shared_benchmarks else get_benchmark_data()
    spy_chg = float(bm.get("SPY", 0))
    qqq_chg = float(bm.get("QQQ", 0))

    # Per-holding benchmark config
    cfg = _TICKER_BENCHMARKS.get(ticker, {})
    suppress_spy = bool(cfg.get("suppress_spy", False))
    suppress_qqq = bool(cfg.get("suppress_qqq", False))

    # Fetch the primary benchmark for this holding (may be BTC, EEM, XAR, etc.)
    cache = _benchmark_cache if _benchmark_cache is not None else {}
    prim_bm, prim_label, prim_chg = _primary_benchmark_chg(ticker, cache)
    # Promote primary benchmark into the shared bm dict so callers can cache it
    if prim_bm and prim_bm not in bm:
        bm[prim_bm] = prim_chg or 0.0

    # Sector ETF for individual stocks only
    sector_etf, sector_chg = (None, None) if is_etf else _sector_etf_change(sector)

    macro = MacroContext(
        spy_change_pct=spy_chg,
        qqq_change_pct=qqq_chg,
        sector_etf=sector_etf,
        sector_etf_change_pct=sector_chg,
        primary_benchmark=prim_bm,
        primary_benchmark_label=prim_label,
        primary_benchmark_chg=prim_chg,
        suppress_spy=suppress_spy,
        suppress_qqq=suppress_qqq,
    )

    vol = float(stock_data.get("volume") or 0)
    avg_vol = float(stock_data.get("average_volume") or 0)
    vol_ratio = round(vol / avg_vol, 2) if vol > 0 and avg_vol > 0 else None
    high_vol = (vol_ratio or 0) >= 1.5

    news: list[NewsCatalyst] = []
    near_earnings = False
    earnings_date_str: Optional[str] = None

    # Fetch news for individual stocks and thematic/sector ETFs (not broad-market)
    fetch_news = (not is_etf) or ticker in ("ITA", "QTUM", "SETM", "IBIT")
    if fetch_news:
        try:
            yf_stock = yf.Ticker(ticker)
            news = _extract_news(yf_stock)
            if not is_etf:
                near_earnings, earnings_date_str = _earnings_near(yf_stock)
        except Exception as e:
            logger.debug("Extra data fetch failed for %s: %s", ticker, e)

    has_news = len(news) > 0
    drivers: list[MoveDriver] = []
    attribution_type = "unclear"
    confidence = "Low"
    explanation = ""

    # ── Crypto ETF (IBIT) ─────────────────────────────────────────────────────
    if is_etf and prim_bm == "BTC-USD":
        # Pure Bitcoin ETF — all moves trace back to BTC
        btc_chg = prim_chg or 0.0
        btc_mag = "strong" if abs(btc_chg) > 2.0 else "moderate" if abs(btc_chg) > 0.5 else "weak"
        drivers.append(MoveDriver(
            driver_type="market",
            description=f"Bitcoin moved {btc_chg:+.2f}% — IBIT tracks BTC spot price directly",
            magnitude=btc_mag,
            icon=DRIVER_ICONS["market"],
        ))
        alpha_btc = day_chg_pct - btc_chg
        if abs(alpha_btc) < 0.3:
            attribution_type, confidence = "market-driven", "High"
            drivers.append(MoveDriver(
                driver_type="etf-index",
                description=(
                    "Tracking Bitcoin spot price closely"
                    " — difference reflects intraday ETF premium/discount"
                ),
                magnitude="weak",
                icon=DRIVER_ICONS["etf-index"],
            ))
        else:
            attribution_type, confidence = "market-driven", "Medium"
            word = "outperformed" if alpha_btc > 0 else "underperformed"
            drivers.append(MoveDriver(
                driver_type="etf-index",
                description=(
                    f"ETF {word} BTC by {abs(alpha_btc):.2f}%"
                    " — likely premium/discount to NAV"
                ),
                magnitude="moderate",
                icon=DRIVER_ICONS["etf-index"],
            ))
        if high_vol:
            drivers.append(MoveDriver(
                driver_type="volume",
                description=f"Trading volume {vol_ratio:.1f}× average — elevated ETF flows",
                magnitude="strong",
                icon=DRIVER_ICONS["volume"],
            ))
        if has_news:
            drivers.append(MoveDriver(
                driver_type="news",
                description=(
                    f"Crypto news activity detected — "
                    f"{len(news)} item{'s' if len(news) > 1 else ''} in circulation"
                ),
                magnitude="moderate",
                icon=DRIVER_ICONS["news"],
            ))
        direction = "rose" if btc_chg >= 0 else "fell"
        explanation = (
            f"Bitcoin {direction} {btc_chg:+.2f}% today, and IBIT followed ({day_chg_pct:+.2f}%). "
            "IBIT holds physical BTC — it tracks the Bitcoin spot price"
            " directly, not the stock market. "
            "S&P 500 and Nasdaq moves are not relevant to IBIT's daily performance."
        )

    # ── Broad market ETF (VOO, VT) ────────────────────────────────────────────
    elif is_etf and prim_bm in ("SPY", "ACWI"):
        ref_chg = prim_chg if prim_chg is not None else spy_chg
        ref_label = prim_label or "S&P 500"
        alpha = day_chg_pct - ref_chg
        ref_mag = "strong" if abs(ref_chg) > 1.0 else "moderate" if abs(ref_chg) > 0.3 else "weak"
        drivers.append(MoveDriver(
            driver_type="market",
            description=f"{ref_label} moved {ref_chg:+.2f}% — {ticker} tracks this index",
            magnitude=ref_mag,
            icon=DRIVER_ICONS["market"],
        ))
        if abs(alpha) < 0.3:
            attribution_type, confidence = "market-driven", "High"
            drivers.append(MoveDriver(
                driver_type="etf-index",
                description=(
                    f"Tracking the index very closely — {abs(alpha):.2f}%"
                    " difference is within normal tracking error"
                ),
                magnitude="weak",
                icon=DRIVER_ICONS["etf-index"],
            ))
            explanation = (
                f"{ticker} moved {day_chg_pct:+.2f}% today, "
                f"closely tracking {ref_label} ({ref_chg:+.2f}%). "
                "As an index fund, moves reflect the aggregate performance"
                " of its underlying holdings."
            )
        else:
            attribution_type, confidence = "holdings-driven", "Medium"
            word = "outperformed" if alpha > 0 else "underperformed"
            drivers.append(MoveDriver(
                driver_type="etf-index",
                description=(
                    f"{word.capitalize()} the index by {abs(alpha):.2f}%"
                    " — sector composition or FX effects"
                ),
                magnitude="moderate",
                icon=DRIVER_ICONS["etf-index"],
            ))
            explanation = (
                f"{ticker} {word} {ref_label} by {abs(alpha):.2f}% today"
                f" (total: {day_chg_pct:+.2f}%). "
                "The gap reflects differences in sector weights or, "
                "for global funds, currency movements."
            )
        if high_vol:
            drivers.append(MoveDriver(
                driver_type="volume",
                description=(
                    f"Volume {vol_ratio:.1f}× average"
                    " — possibly index rebalancing or large inflows/outflows"
                ),
                magnitude="strong",
                icon=DRIVER_ICONS["volume"],
            ))

    # ── Sector / thematic / international ETF ────────────────────────────────
    elif is_etf:
        ref_chg = prim_chg if prim_chg is not None else spy_chg
        ref_label = prim_label or "its primary benchmark"
        alpha_ref = day_chg_pct - ref_chg
        alpha_spy = day_chg_pct - spy_chg

        ref_mag = "strong" if abs(ref_chg) > 1.0 else "moderate" if abs(ref_chg) > 0.3 else "weak"
        if prim_bm and prim_bm != "SPY":
            drivers.append(MoveDriver(
                driver_type="sector",
                description=f"{ref_label} moved {ref_chg:+.2f}% — {ticker}'s closest benchmark",
                magnitude=ref_mag,
                icon=DRIVER_ICONS["sector"],
            ))
        else:
            spy_mag = (
                "strong" if abs(spy_chg) > 1.0
                else "moderate" if abs(spy_chg) > 0.3 else "weak"
            )
            drivers.append(MoveDriver(
                driver_type="market",
                description=f"S&P 500 moved {spy_chg:+.2f}% today",
                magnitude=spy_mag,
                icon=DRIVER_ICONS["market"],
            ))

        if abs(alpha_ref) < 0.5:
            attribution_type, confidence = "market-driven", "Medium"
            drivers.append(MoveDriver(
                driver_type="etf-index",
                description=f"Tracking {ref_label} closely — move is benchmark-driven",
                magnitude="moderate",
                icon=DRIVER_ICONS["etf-index"],
            ))
        else:
            attribution_type, confidence = "holdings-driven", "Medium"
            word = "outperformed" if alpha_ref > 0 else "underperformed"
            drivers.append(MoveDriver(
                driver_type="holdings",
                description=(
                    f"{word.capitalize()} its benchmark by {abs(alpha_ref):.2f}%"
                    " — fund-specific holdings drove the gap"
                ),
                magnitude="moderate",
                icon=DRIVER_ICONS["holdings"],
            ))

        if not suppress_spy and abs(alpha_spy) > 0.3 and prim_bm != "SPY":
            spy_word = "outperformed" if alpha_spy > 0 else "underperformed"
            drivers.append(MoveDriver(
                driver_type="macro",
                description=(
                    f"{spy_word.capitalize()} S&P 500 by {abs(alpha_spy):.2f}%"
                    " — theme or region diverged from broad market"
                ),
                magnitude="moderate",
                icon=DRIVER_ICONS["macro"],
            ))

        if high_vol:
            drivers.append(MoveDriver(
                driver_type="volume",
                description=f"Volume {vol_ratio:.1f}× average — elevated sector or thematic flows",
                magnitude="strong",
                icon=DRIVER_ICONS["volume"],
            ))
        if has_news:
            drivers.append(MoveDriver(
                driver_type="news",
                description=(
                    f"News activity detected — "
                    f"{len(news)} relevant item{'s' if len(news) > 1 else ''} in circulation"
                ),
                magnitude="moderate",
                icon=DRIVER_ICONS["news"],
            ))

        if ref_label and ref_chg is not None:
            if abs(alpha_ref) < 0.3:
                explanation = (
                    f"{ticker} moved {day_chg_pct:+.2f}% today, "
                    f"closely tracking {ref_label} ({ref_chg:+.2f}%). "
                    "The move is driven by the fund's underlying holdings, "
                    "not broad S&P 500 moves."
                )
            else:
                word = "outperformed" if alpha_ref > 0 else "underperformed"
                explanation = (
                    f"{ticker} {word} {ref_label} by {abs(alpha_ref):.2f}% today"
                    f" (total: {day_chg_pct:+.2f}%). "
                    f"{ref_label} itself moved {ref_chg:+.2f}%. "
                    "The gap reflects the fund's specific holdings or country/FX effects."
                )
        else:
            explanation = (
                f"{ticker} moved {day_chg_pct:+.2f}% today,"
                " driven by the performance of its underlying holdings."
            )

    # ── Individual stock ──────────────────────────────────────────────────────
    else:
        attribution_type, confidence = _attribute(
            day_chg_pct, spy_chg, sector_chg, has_news, high_vol, near_earnings
        )

        # Primary benchmark (e.g. IGV for NOW software stock)
        if prim_bm and prim_chg is not None and prim_bm not in ("SPY", "QQQ"):
            prim_mag = (
                "strong" if abs(prim_chg) > 1.0
                else "moderate" if abs(prim_chg) > 0.3 else "weak"
            )
            drivers.append(MoveDriver(
                driver_type="sector",
                description=(
                    f"{prim_label} moved {prim_chg:+.2f}%"
                    " — most comparable sector benchmark"
                ),
                magnitude=prim_mag,
                icon=DRIVER_ICONS["sector"],
            ))
        elif not suppress_spy:
            spy_mag = (
                "strong" if abs(spy_chg) > 1.0
                else "moderate" if abs(spy_chg) > 0.3 else "weak"
            )
            drivers.append(MoveDriver(
                driver_type="market",
                description=f"S&P 500 moved {spy_chg:+.2f}% today",
                magnitude=spy_mag,
                icon=DRIVER_ICONS["market"],
            ))

        if sector_chg is not None:
            sect_mag = (
                "strong" if abs(sector_chg) > 1.0
                else "moderate" if abs(sector_chg) > 0.3 else "weak"
            )
            drivers.append(MoveDriver(
                driver_type="sector",
                description=f"Sector ETF ({sector_etf}) moved {sector_chg:+.2f}% today",
                magnitude=sect_mag,
                icon=DRIVER_ICONS["sector"],
            ))

        if high_vol:
            drivers.append(MoveDriver(
                driver_type="volume",
                description=(
                    f"Volume {vol_ratio:.1f}× the 30-day average"
                    " — unusually high trading activity"
                ),
                magnitude="strong",
                icon=DRIVER_ICONS["volume"],
            ))

        if near_earnings:
            date_label = f" (around {earnings_date_str})" if earnings_date_str else ""
            drivers.append(MoveDriver(
                driver_type="earnings",
                description=f"Earnings report{date_label} — prices often swing around earnings",
                magnitude="strong",
                icon=DRIVER_ICONS["earnings"],
            ))

        if has_news:
            drivers.append(MoveDriver(
                driver_type="news",
                description=(
                    f"News activity detected — "
                    f"{len(news)} recent article{'s' if len(news) > 1 else ''} in circulation"
                ),
                magnitude="moderate",
                icon=DRIVER_ICONS["news"],
            ))

        # Reference benchmark for alpha calculation
        not_spy_qqq = prim_chg is not None and prim_bm not in ("SPY", "QQQ")
        ref_chg_for_alpha = prim_chg if not_spy_qqq else spy_chg
        ref_name_for_alpha = prim_label if not_spy_qqq else "S&P 500"
        alpha = day_chg_pct - ref_chg_for_alpha

        if attribution_type == "market-driven":
            explanation = (
                f"{ticker} moved {day_chg_pct:+.2f}% today, tracking the broad market "
                f"(S&P 500: {spy_chg:+.2f}%). No clear company-specific catalyst found."
            )
        elif attribution_type == "sector-driven":
            ref_used = sector_etf or ref_name_for_alpha
            ref_val = sector_chg if sector_chg is not None else ref_chg_for_alpha
            direction = "rising" if (ref_val or 0) > 0 else "falling"
            explanation = (
                f"{ticker} moved {day_chg_pct:+.2f}% alongside its sector "
                f"({ref_used}: {ref_val:+.2f}%). "
                f"The whole sector is {direction} today."
            )
        elif attribution_type == "earnings-driven":
            date_label = f" around {earnings_date_str}" if earnings_date_str else ""
            explanation = (
                f"{ticker} moved {day_chg_pct:+.2f}% with earnings{date_label}. "
                "Stocks often swing significantly before and after quarterly earnings."
            )
        elif attribution_type == "company-specific":
            word = "more" if alpha > 0 else "less"
            if has_news:
                explanation = (
                    f"{ticker} moved {day_chg_pct:+.2f}% today"
                    f" — {abs(alpha):.1f}% {word} than {ref_name_for_alpha}. "
                    "Recent news appears to be the primary catalyst for today's move."
                )
            else:
                explanation = (
                    f"{ticker} moved {day_chg_pct:+.2f}% today"
                    f" — {abs(alpha):.1f}% {word} than {ref_name_for_alpha}. "
                    "No obvious public catalyst found"
                    " — could be institutional activity or a delayed reaction."
                )
        else:
            explanation = (
                f"{ticker} moved {day_chg_pct:+.2f}% today. Multiple factors may be at play — "
                f"{ref_name_for_alpha} ({ref_chg_for_alpha:+.2f}%)"
                + (
                    f", {sector_etf} sector ETF ({sector_chg:+.2f}%)"
                    if sector_chg is not None and sector_etf else ""
                )
                + ", and possibly company-specific activity."
            )

        if not has_news and not high_vol and not near_earnings and attribution_type not in (
            "market-driven", "sector-driven"
        ):
            explanation += (
                " No obvious company-specific catalyst found. "
                "The move appears mostly market or sector-driven, "
                "or within normal daily volatility."
            )

    return HoldingMoveSummary(
        ticker=ticker,
        day_change_pct=day_chg_pct,
        day_change_dollar=day_chg_dollar,
        attribution_type=attribution_type,
        drivers=drivers[:5],
        confidence=confidence,
        news=news[:3],
        filings=[],
        macro_context=macro,
        explanation_text=explanation,
        is_etf=is_etf,
        volume_vs_avg=vol_ratio,
    )
