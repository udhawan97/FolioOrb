from app.services.etf_price_signal import calculate_etf_price_signal


def test_price_signal_uses_one_year_percentile():
    closes = list(range(80, 121))
    result = calculate_etf_price_signal(
        {"ticker": "VOO", "current_price": 100, "twoHundredDayAverage": 102},
        closes,
    )

    assert result["basis"] == "1Y percentile"
    assert result["priceZoneLabel"] == "Fair"
    assert result["percentile"] == 51.2
    assert result["vs200dPct"] == -2.0


def test_low_percentile_is_bargain_zone():
    result = calculate_etf_price_signal(
        {"ticker": "VT", "current_price": 89, "twoHundredDayAverage": 100},
        list(range(80, 121)),
    )

    assert result["priceZoneLabel"] == "Bargain"
    assert result["vs200dPct"] == -11.0


def test_high_percentile_is_rich_zone():
    result = calculate_etf_price_signal(
        {"ticker": "ITA", "current_price": 118, "twoHundredDayAverage": 108},
        list(range(80, 121)),
    )

    assert result["priceZoneLabel"] == "Rich"
    assert result["percentile"] == 95.1
    assert result["vs200dPct"] == 9.3


def test_falls_back_to_52_week_range_when_history_missing():
    result = calculate_etf_price_signal(
        {
            "ticker": "CGDV",
            "current_price": 75,
            "fiftyTwoWeekLow": 50,
            "fiftyTwoWeekHigh": 100,
        }
    )

    assert result["basis"] == "52W range"
    assert result["priceZoneLabel"] == "Fair"
    assert result["percentile"] == 50.0
    assert result["rangePositionPct"] == 50.0


def test_sparse_data_returns_unavailable_without_raising():
    result = calculate_etf_price_signal({"ticker": "UNKNOWN"})

    assert result["priceZoneLabel"] == "Unavailable"
    assert result["percentile"] is None
    assert "currentPrice" in result["missingFields"]
