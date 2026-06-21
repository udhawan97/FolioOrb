from app.services.security_type import SecurityType, classify_security


def test_etf_detection_from_quote_type():
    assert classify_security("ABC", {"quoteType": "ETF"}) == SecurityType.ETF


def test_stock_detection_from_quote_type():
    assert classify_security("NOW", {"quoteType": "EQUITY"}) == SecurityType.STOCK


def test_crypto_detection_from_quote_type():
    assert classify_security("BTC-USD", {"quoteType": "CRYPTOCURRENCY"}) == SecurityType.CRYPTO


def test_cash_detection_from_ticker():
    assert classify_security("CASH", {}) == SecurityType.CASH


def test_common_portfolio_etf_fallback():
    assert classify_security("VOO", {}) == SecurityType.ETF
    assert classify_security("IBIT", {}) == SecurityType.ETF
    assert classify_security("JEPQ", {}) == SecurityType.ETF
