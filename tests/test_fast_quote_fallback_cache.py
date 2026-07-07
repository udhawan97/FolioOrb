"""
Regression test: get_fast_quote must cache its full-quote fallback under the fast key.

When fast_info carries no usable price, get_fast_quote falls back to get_stock_data.
Previously the fallback result was never stored under the ``fast:`` cache key, so every
dashboard valuation refresh re-ran the fast_info network call for that ticker. The
fallback must now be cached so a second call is a pure cache hit.

No real network calls — yfinance's fast_info is faked.
"""
# pylint: disable=protected-access
from app.services import stock_service


class _NoPriceFastInfo:
    """fast_info stand-in whose last_price is unusable, forcing the fallback path."""
    last_price = 0.0
    previous_close = 0.0


class _FakeTicker:
    calls = 0

    def __init__(self, _symbol):
        pass

    @property
    def fast_info(self):
        type(self).calls += 1
        return _NoPriceFastInfo()


def test_fast_quote_fallback_is_cached(monkeypatch):
    # Isolate the module caches so other tests aren't affected.
    monkeypatch.setattr(stock_service, "_QUOTE_CACHE", {})
    monkeypatch.setattr(stock_service, "_INFO_CACHE", {})
    _FakeTicker.calls = 0
    monkeypatch.setattr(stock_service.yf, "Ticker", _FakeTicker)

    stock_calls = {"n": 0}

    def _fake_get_stock_data(ticker):
        stock_calls["n"] += 1
        return {"ticker": ticker, "current_price": 42.0, "error": None}

    monkeypatch.setattr(stock_service, "get_stock_data", _fake_get_stock_data)

    first = stock_service.get_fast_quote("XYZ")
    second = stock_service.get_fast_quote("XYZ")

    assert first["current_price"] == 42.0
    assert second == first
    # Fallback fetch happened once; the second call was served from the fast cache.
    assert stock_calls["n"] == 1
    assert _FakeTicker.calls == 1
