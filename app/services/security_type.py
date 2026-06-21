"""
Security type detection for portfolio holdings.

Use provider metadata first, then fall back to known portfolio ETF tickers.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Mapping, Any


class SecurityType(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    CRYPTO = "CRYPTO"
    CASH = "CASH"
    UNKNOWN = "UNKNOWN"


COMMON_ETF_TICKERS = {
    "VOO", "VTI", "VT", "QQQ", "QQQM", "SCHD", "VIG", "VIGI", "CGDV",
    "JEPQ", "IXJ", "PPA", "SHLD", "SMH", "IEMG", "VEA", "HEFA", "IOO",
    "GARP", "VO", "VB", "VXF", "IJH", "IJR", "SMIN", "INDA", "NFTY",
    "PIN", "URA", "NUKZ", "QTUM", "IBIT", "BTGD",
    # Current dashboard defaults not present in the attachment list.
    "ITA", "SETM", "WSML",
}

_CASH_TICKERS = {"CASH", "USD", "US$", "MMF"}
_CRYPTO_SUFFIXES = ("-USD", "-USDT", "-USDC")
_ETF_HINTS = {"etf", "fund", "trust", "ishares", "vanguard", "schwab", "invesco"}


def _field(data: Mapping[str, Any] | None, *names: str) -> str:
    if not data:
        return ""
    for name in names:
        value = data.get(name)
        if value is not None:
            return str(value).strip()
    return ""


def classify_security(
    ticker: str,
    metadata: Mapping[str, Any] | None = None,
) -> SecurityType:
    """Classify a holding using metadata first, then ticker fallbacks."""
    symbol = ticker.upper().strip()
    quote_type = _field(metadata, "quoteType", "quote_type").lower()
    asset_type = _field(metadata, "assetType", "asset_type").lower()
    instrument_type = _field(metadata, "instrumentType", "instrument_type").lower()
    fund_family = _field(metadata, "fundFamily", "fund_family").lower()
    category = _field(metadata, "category", "categoryName", "sector").lower()
    exchange = _field(metadata, "exchange", "fullExchangeName").lower()

    joined = " ".join(
        part for part in (quote_type, asset_type, instrument_type, fund_family, category)
        if part
    )

    if symbol in _CASH_TICKERS or "cash" in joined or "money market" in joined:
        return SecurityType.CASH
    if (quote_type in {"cryptocurrency", "crypto"} or asset_type == "crypto"
            or symbol.endswith(_CRYPTO_SUFFIXES)):
        return SecurityType.CRYPTO
    if (quote_type in {"etf", "mutualfund"} or instrument_type == "etf"
            or any(hint in joined for hint in _ETF_HINTS)
            or symbol in COMMON_ETF_TICKERS):
        return SecurityType.ETF
    if (quote_type in {"equity", "stock"} or asset_type in {"equity", "stock"}
            or (exchange and symbol)):
        return SecurityType.STOCK
    return SecurityType.UNKNOWN
