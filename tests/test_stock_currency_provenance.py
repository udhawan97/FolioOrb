"""Quote display fallbacks must not become persisted currency evidence."""

from app.services import stock_service


def test_full_quote_keeps_missing_source_currency_apart_from_display_fallback(
    monkeypatch,
):
    stock_service.get_stock_data.cache_clear()
    monkeypatch.setattr(
        stock_service,
        "get_ticker_info",
        lambda _ticker: {
            "currentPrice": 100.0,
            "previousClose": 99.0,
            "longName": "Fictional Quote",
        },
    )

    quote = stock_service.get_stock_data("NOSRC")

    assert quote["currency"] == "USD"  # established display compatibility
    assert quote["source_currency"] is None  # not evidence for persistence


def test_full_quote_preserves_explicit_source_currency(monkeypatch):
    stock_service.get_stock_data.cache_clear()
    monkeypatch.setattr(
        stock_service,
        "get_ticker_info",
        lambda _ticker: {
            "currentPrice": 100.0,
            "previousClose": 99.0,
            "currency": "USD",
            "longName": "Fictional USD Quote",
        },
    )

    quote = stock_service.get_stock_data("WITHSRC")

    assert quote["currency"] == "USD"
    assert quote["source_currency"] == "USD"
