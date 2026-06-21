from app.services.etf_quality import calculate_etf_quality_score


def test_sparse_etf_data_returns_insufficient_data():
    result = calculate_etf_quality_score({"ticker": "UNKNOWN"})
    assert result["qualityLabel"] == "Insufficient Data"
    assert result["score"] is None


def test_broad_etfs_classify_as_broad_diversification():
    for ticker in ("VOO", "VTI", "VT"):
        result = calculate_etf_quality_score({"ticker": ticker, "expense_ratio": 0.0005})
        assert result["diversificationLabel"] == "Broad"
        assert result["qualityLabel"] in {"Strong", "Good", "Fair"}


def test_sector_etfs_classify_as_more_concentrated():
    for ticker in ("SMH", "PPA", "IXJ"):
        result = calculate_etf_quality_score({"ticker": ticker, "expense_ratio": 0.004})
        assert result["diversificationLabel"] in {"Moderate", "Concentrated"}
        assert result["categoryRiskLabel"] == "High"


def test_options_income_etf_has_higher_complexity_risk():
    result = calculate_etf_quality_score({"ticker": "JEPQ", "expense_ratio": 0.0035})
    assert result["categoryRiskLabel"] == "High"
    assert result["qualityLabel"] != "Strong"


def test_crypto_linked_etf_is_speculative():
    for ticker in ("IBIT", "BTGD"):
        result = calculate_etf_quality_score({"ticker": ticker, "expense_ratio": 0.0025})
        assert result["categoryRiskLabel"] == "Speculative"
        assert result["qualityLabel"] == "Speculative"
