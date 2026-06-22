"""
app/services/holding_intelligence.py

Provides structured per-holding intelligence:
  - What the holding covers (strategy, sectors, countries, top holdings)
  - Relevant benchmarks for move comparison
  - Key drivers specific to each security type

Data priority: static metadata → yfinance enrichment → graceful "not available".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class SectorWeight:
    name: str
    weight: float  # percentage 0–100


@dataclass
class CountryWeight:
    name: str
    weight: float  # percentage 0–100


@dataclass
class TopHolding:
    ticker: str
    name: str
    weight: float  # percentage 0–100


@dataclass
class HoldingIntelligence:  # pylint: disable=too-many-instance-attributes
    ticker: str
    coverage_type: str  # equity|etf-broad|etf-sector|etf-thematic|etf-international|etf-crypto
    coverage_label: str      # Human-readable label for coverage_type
    strategy: str            # What this holding does / tracks
    asset_class: str         # equities | crypto | fixed-income | mixed
    theme: Optional[str]     # e.g. "Quantum Computing & AI Hardware"
    sectors: list[SectorWeight]
    countries: list[CountryWeight]
    top_holdings: list[TopHolding]
    benchmark_tickers: list[str]       # Ordered by relevance
    benchmark_labels: dict[str, str]   # ticker → human label
    peer_tickers: list[str]
    key_drivers: list[str]
    concentration_level: str           # very-low | low | medium | high
    expense_ratio: Optional[float]     # Annual expense ratio as decimal (e.g. 0.03 = 3bps)
    data_quality: str                  # live | partial | static
    data_sources: list[str]


# ── Coverage type labels ──────────────────────────────────────────────────────

COVERAGE_TYPE_LABELS: dict[str, str] = {
    "equity":            "Individual Stock",
    "etf-broad":         "Broad Market ETF",
    "etf-sector":        "Sector ETF",
    "etf-thematic":      "Thematic ETF",
    "etf-international": "International ETF",
    "etf-crypto":        "Crypto ETF",
}

CONCENTRATION_LABELS: dict[str, str] = {
    "very-low": "Very Low (1000s of holdings)",
    "low":      "Low (diversified)",
    "medium":   "Medium",
    "high":     "High (concentrated)",
}


# ── Static metadata ───────────────────────────────────────────────────────────
# Sourced from fund prospectuses, MSCI/Bloomberg index documentation.
# Weights are approximate and reflect approximate recent fund composition.

_STATIC: dict[str, dict] = {
    "IBIT": {
        "coverage_type": "etf-crypto",
        "strategy": (
            "Direct spot exposure to Bitcoin via a regulated ETF. "
            "Holds physical BTC in custody — not futures."
        ),
        "asset_class": "crypto",
        "theme": "Bitcoin",
        "sectors": [],
        "countries": [],
        "top_holdings": [{"ticker": "BTC-USD", "name": "Bitcoin", "weight": 100.0}],
        "benchmark_tickers": ["BTC-USD"],
        "benchmark_labels": {"BTC-USD": "Bitcoin (BTC-USD)"},
        "peer_tickers": ["FBTC", "GBTC", "BTCO"],
        "key_drivers": [
            "Bitcoin spot price — 1:1 tracking (minus fees)",
            "Crypto market sentiment and on-chain metrics",
            "Institutional BTC demand and ETF flows",
            "Regulatory news: SEC, global crypto policy",
        ],
        "concentration_level": "high",
        "expense_ratio": 0.0025,
    },
    "VOO": {
        "coverage_type": "etf-broad",
        "strategy": (
            "Tracks the S&P 500 index — 500 largest US public companies, "
            "market-cap weighted."
        ),
        "asset_class": "equities",
        "theme": None,
        "sectors": [
            {"name": "Technology",     "weight": 31.5},
            {"name": "Financials",     "weight": 13.1},
            {"name": "Healthcare",     "weight": 11.6},
            {"name": "Consumer Disc.", "weight": 10.2},
            {"name": "Industrials",    "weight": 8.5},
            {"name": "Other",          "weight": 25.1},
        ],
        "countries": [{"name": "United States", "weight": 100.0}],
        "top_holdings": [
            {"ticker": "AAPL",  "name": "Apple",     "weight": 7.2},
            {"ticker": "MSFT",  "name": "Microsoft", "weight": 6.8},
            {"ticker": "NVDA",  "name": "NVIDIA",    "weight": 6.1},
            {"ticker": "AMZN",  "name": "Amazon",    "weight": 3.7},
            {"ticker": "META",  "name": "Meta",      "weight": 2.6},
        ],
        "benchmark_tickers": ["SPY"],
        "benchmark_labels": {"SPY": "S&P 500 (SPY)"},
        "peer_tickers": ["SPY", "IVV", "SPLG"],
        "key_drivers": [
            "S&P 500 index performance — essentially identical to SPY",
            "Mega-cap tech (AAPL, MSFT, NVDA) = ~20% of portfolio",
            "Top 10 holdings account for ~31% of total weight",
            "US macro: Fed rates, GDP revisions, earnings season",
        ],
        "concentration_level": "low",
        "expense_ratio": 0.0003,
    },
    "VT": {
        "coverage_type": "etf-broad",
        "strategy": (
            "Tracks the FTSE Global All Cap Index — ~9,500 stocks across "
            "49 countries, all market caps."
        ),
        "asset_class": "equities",
        "theme": "Global Equities",
        "sectors": [
            {"name": "Technology",     "weight": 22.4},
            {"name": "Financials",     "weight": 15.3},
            {"name": "Healthcare",     "weight": 11.2},
            {"name": "Consumer Disc.", "weight": 10.8},
            {"name": "Industrials",    "weight": 10.1},
            {"name": "Other",          "weight": 30.2},
        ],
        "countries": [
            {"name": "United States",  "weight": 61.8},
            {"name": "Japan",          "weight": 5.9},
            {"name": "United Kingdom", "weight": 3.7},
            {"name": "China",          "weight": 2.8},
            {"name": "Canada",         "weight": 2.7},
            {"name": "Other",          "weight": 23.1},
        ],
        "top_holdings": [
            {"ticker": "AAPL",  "name": "Apple",     "weight": 4.2},
            {"ticker": "MSFT",  "name": "Microsoft", "weight": 4.0},
            {"ticker": "NVDA",  "name": "NVIDIA",    "weight": 3.5},
            {"ticker": "AMZN",  "name": "Amazon",    "weight": 2.2},
            {"ticker": "META",  "name": "Meta",      "weight": 1.5},
        ],
        "benchmark_tickers": ["ACWI", "SPY"],
        "benchmark_labels": {"ACWI": "Global Equities (ACWI)", "SPY": "US S&P 500"},
        "peer_tickers": ["ACWI", "VXUS", "IXUS"],
        "key_drivers": [
            "US equities (~62%) dominate day-to-day moves",
            "International developed (Japan, UK, Europe) = ~28%",
            "Emerging markets (China, Korea, India) = ~10%",
            "USD strength reduces non-US holding values",
            "Global macro: central bank divergence across regions",
        ],
        "concentration_level": "very-low",
        "expense_ratio": 0.0007,
    },
    "IEMG": {
        "coverage_type": "etf-international",
        "strategy": (
            "Tracks the MSCI Emerging Markets Investable Market Index "
            "— large, mid, small cap across EM countries."
        ),
        "asset_class": "equities",
        "theme": "Emerging Markets",
        "sectors": [
            {"name": "Technology",     "weight": 29.4},
            {"name": "Financials",     "weight": 20.1},
            {"name": "Consumer Disc.", "weight": 13.8},
            {"name": "Materials",      "weight": 7.3},
            {"name": "Energy",         "weight": 5.8},
            {"name": "Other",          "weight": 23.6},
        ],
        "countries": [
            {"name": "China",        "weight": 25.3},
            {"name": "India",        "weight": 20.1},
            {"name": "Taiwan",       "weight": 17.2},
            {"name": "South Korea",  "weight": 12.4},
            {"name": "Brazil",       "weight": 4.8},
            {"name": "Other",        "weight": 20.2},
        ],
        "top_holdings": [
            {"ticker": "TSM",   "name": "Taiwan Semi.",   "weight": 5.8},
            {"ticker": "005930.KS", "name": "Samsung",   "weight": 3.7},
            {"ticker": "700.HK", "name": "Tencent",      "weight": 3.9},
            {"ticker": "RELIANCE.NS", "name": "Reliance","weight": 1.7},
            {"ticker": "9988.HK", "name": "Alibaba HK",  "weight": 1.8},
        ],
        "benchmark_tickers": ["EEM", "ACWI"],
        "benchmark_labels": {"EEM": "Emerging Markets (EEM)", "ACWI": "Global Equities (ACWI)"},
        "peer_tickers": ["EEM", "VWO", "SCHE"],
        "key_drivers": [
            "USD strength inversely affects EM returns",
            "China policy & tech regulation (~25% of fund)",
            "Taiwan Semiconductor — largest holding at ~6%",
            "India growth story now ~20% of the fund",
            "Commodity prices affect Brazil and South Africa exposure",
        ],
        "concentration_level": "low",
        "expense_ratio": 0.0009,
    },
    "ITA": {
        "coverage_type": "etf-sector",
        "strategy": (
            "Tracks the Dow Jones U.S. Select Aerospace & Defense Index "
            "— US defense primes and suppliers."
        ),
        "asset_class": "equities",
        "theme": "Aerospace & Defense",
        "sectors": [
            {"name": "Aerospace & Defense", "weight": 89.3},
            {"name": "Industrials",          "weight": 7.2},
            {"name": "Technology",           "weight": 3.5},
        ],
        "countries": [{"name": "United States", "weight": 100.0}],
        "top_holdings": [
            {"ticker": "RTX",  "name": "RTX Corp",        "weight": 16.2},
            {"ticker": "LMT",  "name": "Lockheed Martin", "weight": 13.8},
            {"ticker": "GD",   "name": "General Dynamics", "weight": 8.4},
            {"ticker": "NOC",  "name": "Northrop Grumman","weight": 8.1},
            {"ticker": "BA",   "name": "Boeing",           "weight": 5.9},
        ],
        "benchmark_tickers": ["XAR", "SPY"],
        "benchmark_labels": {"XAR": "Aerospace/Defense Sector (XAR)", "SPY": "S&P 500"},
        "peer_tickers": ["XAR", "PPA", "DFEN"],
        "key_drivers": [
            "US defense budget and Pentagon appropriations",
            "Geopolitical events: conflict escalation / de-escalation",
            "Government contract awards (DoD, NATO procurement)",
            "RTX (~16%) and LMT (~14%) together drive ~30% of moves",
            "Earnings from defense primes (quarterly, heavily guided)",
        ],
        "concentration_level": "medium",
        "expense_ratio": 0.004,
    },
    "QTUM": {
        "coverage_type": "etf-thematic",
        "strategy": (
            "Tracks companies involved in quantum computing, machine learning, "
            "and cloud infrastructure hardware."
        ),
        "asset_class": "equities",
        "theme": "Quantum Computing & AI Hardware",
        "sectors": [
            {"name": "Technology",  "weight": 88.5},
            {"name": "Industrials", "weight": 6.8},
            {"name": "Healthcare",  "weight": 2.4},
            {"name": "Other",       "weight": 2.3},
        ],
        "countries": [
            {"name": "United States", "weight": 63.4},
            {"name": "Japan",         "weight": 8.2},
            {"name": "Netherlands",   "weight": 5.1},
            {"name": "Canada",        "weight": 4.3},
            {"name": "United Kingdom","weight": 3.8},
            {"name": "Other",         "weight": 15.2},
        ],
        "top_holdings": [
            {"ticker": "IBM",   "name": "IBM",       "weight": 7.1},
            {"ticker": "GOOGL", "name": "Alphabet",  "weight": 6.3},
            {"ticker": "HON",   "name": "Honeywell", "weight": 5.2},
            {"ticker": "IONQ",  "name": "IonQ",      "weight": 4.8},
            {"ticker": "RGTI",  "name": "Rigetti",   "weight": 3.9},
        ],
        "benchmark_tickers": ["QQQ", "SOXX"],
        "benchmark_labels": {"QQQ": "Nasdaq 100 (QQQ)", "SOXX": "Semiconductors (SOXX)"},
        "peer_tickers": ["QBTS", "IONQ", "RGTI"],
        "key_drivers": [
            "Quantum computing breakthroughs (error-correction, qubit milestones)",
            "Semiconductor momentum (chips underpin quantum hardware)",
            "AI infrastructure spend and big-tech capex plans",
            "Broad Nasdaq / tech risk-on sentiment (QQQ correlation ~0.8)",
            "Specific news: IBM, Google, Rigetti, IonQ announcements",
        ],
        "concentration_level": "medium",
        "expense_ratio": 0.0045,
    },
    "CGDV": {
        "coverage_type": "etf-sector",
        "strategy": (
            "Actively managed — Capital Group seeks dividend income + "
            "capital appreciation from undervalued stocks."
        ),
        "asset_class": "equities",
        "theme": "Dividend Value",
        "sectors": [
            {"name": "Healthcare",      "weight": 20.1},
            {"name": "Financials",      "weight": 18.4},
            {"name": "Energy",          "weight": 12.3},
            {"name": "Consumer Staples","weight": 10.6},
            {"name": "Industrials",     "weight": 9.8},
            {"name": "Other",           "weight": 28.8},
        ],
        "countries": [
            {"name": "United States", "weight": 83.2},
            {"name": "Europe",        "weight": 10.4},
            {"name": "Other",         "weight": 6.4},
        ],
        "top_holdings": [
            {"ticker": "ABBV", "name": "AbbVie",           "weight": 3.5},
            {"ticker": "XOM",  "name": "Exxon Mobil",       "weight": 2.8},
            {"ticker": "JPM",  "name": "JPMorgan Chase",    "weight": 2.6},
            {"ticker": "JNJ",  "name": "Johnson & Johnson", "weight": 2.4},
            {"ticker": "CVX",  "name": "Chevron",            "weight": 2.2},
        ],
        "benchmark_tickers": ["SCHD", "DVY"],
        "benchmark_labels": {"SCHD": "Dividend ETF (SCHD)", "DVY": "Dividend ETF (DVY)"},
        "peer_tickers": ["DVY", "SCHD", "VYM", "HDV"],
        "key_drivers": [
            "Dividend sustainability and payout ratio quality",
            "Value vs. growth rotation — benefits in value up-cycles",
            "Healthcare (~20%) and Financials (~18%) sector trends",
            "Interest rates: rising rates pressure high-yield dividend stocks",
            "Capital Group active stock picks — not index-driven",
        ],
        "concentration_level": "medium",
        "expense_ratio": 0.0033,
    },
    "SETM": {
        "coverage_type": "etf-thematic",
        "strategy": (
            "Tracks companies mining and producing materials critical for "
            "clean energy: lithium, copper, nickel, rare earths."
        ),
        "asset_class": "equities",
        "theme": "Energy Transition Materials",
        "sectors": [
            {"name": "Materials",   "weight": 68.4},
            {"name": "Energy",      "weight": 16.2},
            {"name": "Industrials", "weight": 11.3},
            {"name": "Technology",  "weight": 4.1},
        ],
        "countries": [
            {"name": "Canada",       "weight": 28.7},
            {"name": "Australia",    "weight": 21.3},
            {"name": "United States","weight": 14.8},
            {"name": "Chile",        "weight": 8.2},
            {"name": "South Africa", "weight": 5.6},
            {"name": "Other",        "weight": 21.4},
        ],
        "top_holdings": [
            {"ticker": "ALB",  "name": "Albemarle",         "weight": 9.2},
            {"ticker": "SQM",  "name": "SQM",               "weight": 6.8},
            {"ticker": "MP",   "name": "MP Materials",       "weight": 5.1},
            {"ticker": "FCX",  "name": "Freeport-McMoRan",  "weight": 4.6},
            {"ticker": "LAC",  "name": "Lithium Americas",  "weight": 3.4},
        ],
        "benchmark_tickers": ["LIT", "COPX", "XME"],
        "benchmark_labels": {
            "LIT":  "Lithium & Battery (LIT)",
            "COPX": "Copper Miners (COPX)",
            "XME":  "Metals & Mining (XME)",
        },
        "peer_tickers": ["LIT", "REMX", "COPX"],
        "key_drivers": [
            "EV adoption rates and battery material demand trajectory",
            "Lithium and copper spot prices (highly correlated to fund)",
            "Clean energy policy: US IRA, European Green Deal",
            "Mine supply disruptions (weather, labor, regulations)",
            "China strategic material stockpiling or export restrictions",
        ],
        "concentration_level": "medium",
        "expense_ratio": 0.0065,
    },
    "WSML": {
        "coverage_type": "etf-international",
        "strategy": (
            "Tracks the MSCI World Small Cap Index — small cap stocks "
            "across 23 developed market countries."
        ),
        "asset_class": "equities",
        "theme": "Global Small Cap",
        "sectors": [
            {"name": "Industrials",    "weight": 22.1},
            {"name": "Consumer Disc.", "weight": 14.3},
            {"name": "Financials",     "weight": 12.7},
            {"name": "Technology",     "weight": 11.8},
            {"name": "Healthcare",     "weight": 10.4},
            {"name": "Other",          "weight": 28.7},
        ],
        "countries": [
            {"name": "United States",  "weight": 57.8},
            {"name": "Japan",          "weight": 9.8},
            {"name": "United Kingdom", "weight": 7.1},
            {"name": "Canada",         "weight": 5.2},
            {"name": "Australia",      "weight": 4.3},
            {"name": "Other",          "weight": 15.8},
        ],
        "top_holdings": [],
        "benchmark_tickers": ["IWM", "EFA"],
        "benchmark_labels": {"IWM": "US Small Cap (IWM)", "EFA": "Intl Developed (EFA)"},
        "peer_tickers": ["IWM", "VSS", "GWX"],
        "key_drivers": [
            "Global risk appetite — small caps lead in risk-on rallies",
            "US small cap (IWM) is closest proxy (~58% of fund)",
            "Japan (~10%) and UK (~7%) add FX sensitivity",
            "Small cap premium: more volatile than large cap indexes",
            "Regional growth divergence (US vs Europe vs Asia)",
        ],
        "concentration_level": "very-low",
        "expense_ratio": 0.0035,
    },
    "NOW": {
        "coverage_type": "equity",
        "strategy": (
            "Enterprise cloud platform for digital workflow automation "
            "— IT, HR, customer service, and app development."
        ),
        "asset_class": "equities",
        "theme": "Enterprise SaaS",
        "sectors": [{"name": "Enterprise Software (SaaS)", "weight": 100.0}],
        "countries": [
            {"name": "Americas",     "weight": 49.0},
            {"name": "EMEA",         "weight": 37.0},
            {"name": "Asia-Pacific", "weight": 14.0},
        ],
        "top_holdings": [],
        "benchmark_tickers": ["IGV", "QQQ"],
        "benchmark_labels": {"IGV": "Software Sector (IGV)", "QQQ": "Nasdaq 100 (QQQ)"},
        "peer_tickers": ["CRM", "WDAY", "SNOW", "MSFT"],
        "key_drivers": [
            "Enterprise software spend and IT budget cycles",
            "Net Revenue Retention (NRR) > 120% validates land-and-expand model",
            "Now AI platform: AI-native product suite adoption rates",
            "Large deal wins (>$1M ACV) signal competitive positioning",
            "High P/E (~60–80×) requires strong forward guidance to hold multiple",
        ],
        "concentration_level": "high",
        "expense_ratio": None,
    },
}


# ── Live enrichment via yfinance ──────────────────────────────────────────────

def _try_yfinance_enrichment(ticker: str) -> tuple[list, list, list]:
    """
    Attempt to fetch sector weights, country weights, and top holdings from yfinance.
    Returns (sectors, countries, top_holdings) — any element may be empty.
    """
    sectors: list[SectorWeight] = []
    countries: list[CountryWeight] = []
    top_holdings: list[TopHolding] = []
    try:
        info = yf.Ticker(ticker).info

        sw = info.get("sectorWeightings") or []
        for item in sw:
            if isinstance(item, dict):
                for name, weight in item.items():
                    label = name.replace("_", " ").title()
                    sectors.append(SectorWeight(name=label, weight=round(float(weight) * 100, 1)))
        if sectors:
            sectors.sort(key=lambda x: x.weight, reverse=True)

        cw = info.get("countryWeightings") or []
        for item in cw:
            if isinstance(item, dict):
                for name, weight in item.items():
                    countries.append(CountryWeight(name=name, weight=round(float(weight) * 100, 1)))
        if countries:
            countries.sort(key=lambda x: x.weight, reverse=True)

        for h in (info.get("holdings") or [])[:5]:
            if isinstance(h, dict):
                sym = h.get("symbol") or ""
                name = h.get("holdingName") or sym
                pct = round(float(h.get("holdingPercent") or 0) * 100, 1)
                if sym:
                    top_holdings.append(TopHolding(ticker=sym, name=name, weight=pct))
    except Exception as e:
        logger.debug("yfinance enrichment failed for %s: %s", ticker, e)
    return sectors, countries, top_holdings


# ── Public API ────────────────────────────────────────────────────────────────

def get_static_holding_metadata(ticker: str) -> dict:
    """Return built-in metadata for a holding without live enrichment."""
    return dict(_STATIC.get(ticker.upper(), {}))


def get_holding_intelligence(
    ticker: str,
    stock_data: Optional[dict] = None,
) -> HoldingIntelligence:
    """
    Return structured intelligence for any holding.
    Uses static metadata for the 10 default holdings; derives from yfinance for others.
    """
    ticker = ticker.upper()
    static = _STATIC.get(ticker)

    if static is None:
        return _derive_unknown(ticker, stock_data)

    raw_sectors  = [SectorWeight(**s) for s in static.get("sectors") or []]
    raw_countries = [CountryWeight(**c) for c in static.get("countries") or []]
    raw_holdings  = [TopHolding(**h) for h in static.get("top_holdings") or []]

    coverage_type = static["coverage_type"]
    data_quality = "static"
    data_sources = ["static_metadata"]

    # Attempt live enrichment for ETFs that have Yahoo Finance composition data
    if coverage_type not in ("equity", "etf-crypto"):
        live_s, live_c, live_h = _try_yfinance_enrichment(ticker)
        if live_s:
            raw_sectors = live_s[:6]
            data_quality = "live"
            data_sources.append("yfinance")
        if live_c and not raw_countries:
            raw_countries = live_c[:6]
        if live_h and not raw_holdings:
            raw_holdings = live_h[:5]

    return HoldingIntelligence(
        ticker=ticker,
        coverage_type=coverage_type,
        coverage_label=COVERAGE_TYPE_LABELS.get(coverage_type, coverage_type),
        strategy=static["strategy"],
        asset_class=static["asset_class"],
        theme=static.get("theme"),
        sectors=raw_sectors[:6],
        countries=raw_countries[:6],
        top_holdings=raw_holdings[:5],
        benchmark_tickers=static["benchmark_tickers"],
        benchmark_labels=static["benchmark_labels"],
        peer_tickers=static.get("peer_tickers") or [],
        key_drivers=static.get("key_drivers") or [],
        concentration_level=static.get("concentration_level") or "medium",
        expense_ratio=static.get("expense_ratio"),
        data_quality=data_quality,
        data_sources=data_sources,
    )


def _derive_unknown(ticker: str, stock_data: Optional[dict]) -> HoldingIntelligence:
    """Derive intelligence for a ticker not in the static catalog."""
    qt = "EQUITY"
    sector = "N/A"
    name = ticker
    if stock_data:
        qt = str(stock_data.get("quote_type") or "EQUITY").upper()
        sector = str(stock_data.get("sector") or "N/A")
        name = str(stock_data.get("name") or ticker)

    is_etf = qt in ("ETF", "MUTUALFUND")
    coverage_type = "etf-sector" if is_etf else "equity"

    live_s, live_c, live_h = _try_yfinance_enrichment(ticker)

    # Derive benchmark from sector
    from app.services.move_explainer import SECTOR_ETF_MAP
    sector_etf = SECTOR_ETF_MAP.get(sector)
    if sector_etf:
        benchmarks = [sector_etf, "SPY"]
        labels: dict[str, str] = {sector_etf: f"{sector} ({sector_etf})", "SPY": "S&P 500"}
    else:
        benchmarks = ["SPY"]
        labels = {"SPY": "S&P 500"}

    strategy = f"{name} — {sector}" if sector != "N/A" else name
    if is_etf:
        strategy = f"ETF tracking {sector or 'various'} securities."

    return HoldingIntelligence(
        ticker=ticker,
        coverage_type=coverage_type,
        coverage_label=COVERAGE_TYPE_LABELS.get(coverage_type, coverage_type),
        strategy=strategy,
        asset_class="equities",
        theme=sector if sector not in ("N/A", "") else None,
        sectors=live_s[:6],
        countries=live_c[:6],
        top_holdings=live_h[:5],
        benchmark_tickers=benchmarks,
        benchmark_labels=labels,
        peer_tickers=[],
        key_drivers=[],
        concentration_level="medium",
        expense_ratio=None,
        data_quality="partial" if (live_s or live_c) else "static",
        data_sources=["yfinance"] if (live_s or live_c) else [],
    )


def intelligence_to_dict(intel: HoldingIntelligence) -> dict:
    """Serialize HoldingIntelligence to a JSON-safe dict."""
    return {
        "ticker": intel.ticker,
        "coverage_type": intel.coverage_type,
        "coverage_label": intel.coverage_label,
        "strategy": intel.strategy,
        "asset_class": intel.asset_class,
        "theme": intel.theme,
        "sectors": [{"name": s.name, "weight": s.weight} for s in intel.sectors],
        "countries": [{"name": c.name, "weight": c.weight} for c in intel.countries],
        "top_holdings": [
            {"ticker": h.ticker, "name": h.name, "weight": h.weight}
            for h in intel.top_holdings
        ],
        "benchmark_tickers": intel.benchmark_tickers,
        "benchmark_labels": intel.benchmark_labels,
        "peer_tickers": intel.peer_tickers,
        "key_drivers": intel.key_drivers,
        "concentration_level": intel.concentration_level,
        "concentration_label": CONCENTRATION_LABELS.get(intel.concentration_level, ""),
        "expense_ratio": intel.expense_ratio,
        "expense_ratio_bps": round(intel.expense_ratio * 10000) if intel.expense_ratio else None,
        "data_quality": intel.data_quality,
        "data_sources": intel.data_sources,
    }
