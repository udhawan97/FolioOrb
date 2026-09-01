"""Shared currency policy for deterministic, dollar-denominated totals.

FolioOrb does not perform FX conversion. A stored fact therefore participates
in a USD aggregate only when its own persisted currency explicitly says USD.
Quote-only views retain the historic missing-currency-as-USD display fallback,
but persistence and reporting never use that fallback as provenance.
"""
from __future__ import annotations

from sqlalchemy import and_, func

REPORTING_CURRENCY = "USD"
LEGACY_UNKNOWN_PROVENANCE = "legacy_unknown"
TRUSTED_SALE_PRICE_SOURCES = frozenset({"manual_entry", "market_quote"})
TRUSTED_DCA_PLAN_CURRENCY_SOURCES = frozenset({"ticker_validation"})
TRUSTED_DCA_CONTRIBUTION_CURRENCY_SOURCES = frozenset({"validated_plan"})


def normalize_currency(value) -> str | None:
    """Return the source spelling of a non-empty currency, otherwise ``None``."""
    if value is None:
        return None
    currency = str(value).strip()
    return currency or None


def quote_currency(value) -> str:
    """Return the display currency for a live quote.

    Domestic quote adapters historically omitted currency. Preserve that live
    display behavior without turning absence into persisted USD provenance.
    """
    return normalize_currency(value) or REPORTING_CURRENCY


def is_reporting_currency(value) -> bool:
    """True only when ``value`` explicitly names FolioOrb's reporting currency."""
    currency = normalize_currency(value)
    return bool(currency and currency.upper() == REPORTING_CURRENCY)


def is_trusted_reporting_fact(currency, provenance) -> bool:
    """True for a persisted USD sale with an explicitly supported price source."""
    source = normalize_currency(provenance)
    return bool(
        is_reporting_currency(currency)
        and source
        and source.lower() in TRUSTED_SALE_PRICE_SOURCES
    )


def reporting_currency_clause(column):
    """SQL expression selecting rows with explicit, normalized USD currency."""
    return func.upper(func.trim(column)) == REPORTING_CURRENCY


def trusted_reporting_fact_clause(currency_column, provenance_column):
    """SQL expression selecting USD sales with explicitly supported price sources."""
    normalized_source = func.lower(func.trim(provenance_column))
    return and_(
        reporting_currency_clause(currency_column),
        normalized_source.in_(tuple(sorted(TRUSTED_SALE_PRICE_SOURCES))),
    )
