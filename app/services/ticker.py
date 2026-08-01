"""What a ticker symbol is: its shape, and how to normalise one.

Deliberately dependency-free. This rule is needed at two very different
distances from the market data layer — the request schemas validate a symbol
before anything is loaded, and the services validate one before it reaches a
URL or a log line — and the two had grown separate copies of the same regex.
Keeping the definition in a leaf module lets `app.schemas` share it without
importing `stock_service` and, through it, the whole vendor stack.

`stock_service` re-exports these so its existing callers are unaffected; it
remains the place that decides what a *quote* means, while what a *symbol*
means lives here.
"""
from __future__ import annotations

import re

# Ticker symbols: letters, digits, '.', '-', '^'; max 10 chars.
TICKER_PATTERN = re.compile(r"^[A-Z0-9.^-]{1,10}$")

TICKER_SHAPE_MESSAGE = "Ticker may contain only letters, numbers, '.', '-', or '^'"


def normalize_ticker(ticker: str) -> str:
    """Strip whitespace and upper-case a user-supplied ticker symbol."""
    return (ticker or "").strip().upper()


def ticker_shape_is_safe(ticker: str) -> bool:
    """Return True if the symbol is narrow enough to be safe in logs, URLs, and storage."""
    return bool(TICKER_PATTERN.fullmatch(normalize_ticker(ticker)))


def validated_ticker_shape(ticker: str) -> str:
    """Normalise a symbol, raising ValueError if it isn't shaped like a ticker.

    The raising form the Pydantic validators want: one call instead of the
    normalise-then-check-then-raise trio each of them had written out.
    """
    symbol = normalize_ticker(ticker)
    if not TICKER_PATTERN.fullmatch(symbol):
        raise ValueError(TICKER_SHAPE_MESSAGE)
    return symbol
