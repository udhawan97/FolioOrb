"""Tests for portfolio dividend income."""
from app.services.dividend_income import compute_portfolio_income


def _payer(ticker, value, shares, rate, yield_frac, **extra):
    row = {
        "ticker": ticker,
        "current_value": value,
        "shares": shares,
        "dividend_rate": rate,
        "dividend_yield": yield_frac,
        "is_watchlist": False,
    }
    row.update(extra)
    return row


def _non_payer(ticker, value, shares=10):
    return {
        "ticker": ticker,
        "current_value": value,
        "shares": shares,
        "dividend_rate": None,
        "dividend_yield": None,
        "is_watchlist": False,
    }


def test_annual_income_is_shares_times_rate():
    result = compute_portfolio_income([_payer("KO", 8156.0, 100, 2.12, 0.026)])
    assert result["has_data"] is True
    assert result["total_annual_income"] == 212.0
    assert result["payers"][0]["annual_income"] == 212.0


def test_portfolio_yield_is_income_over_total_value():
    # One payer worth 10k yielding 300/yr, plus a 10k non-payer.
    result = compute_portfolio_income([
        _payer("VZ", 10_000.0, 100, 3.0, 0.06),
        _non_payer("TSLA", 10_000.0),
    ])
    # 300 income / 20k total = 1.5% portfolio yield (fraction).
    assert abs(result["portfolio_yield"] - 0.015) < 1e-6
    assert result["total_annual_income"] == 300.0


def test_non_payers_are_listed_not_counted_as_zero_income():
    result = compute_portfolio_income([
        _payer("KO", 5000.0, 50, 2.0, 0.02),
        _non_payer("TSLA", 5000.0),
        _non_payer("BRK-B", 5000.0),
    ])
    assert result["coverage"]["payer_count"] == 1
    assert result["coverage"]["non_payer_count"] == 2
    assert set(result["coverage"]["non_payers"]) == {"TSLA", "BRK-B"}


def test_payers_sorted_by_income_descending():
    result = compute_portfolio_income([
        _payer("KO", 5000.0, 50, 2.0, 0.02),     # 100/yr
        _payer("VZ", 10_000.0, 100, 3.0, 0.06),  # 300/yr
    ])
    assert [p["ticker"] for p in result["payers"]] == ["VZ", "KO"]


def test_watchlist_rows_are_excluded():
    result = compute_portfolio_income([
        _payer("KO", 5000.0, 50, 2.0, 0.02),
        _payer("VZ", 10_000.0, 100, 3.0, 0.06, is_watchlist=True),
    ])
    assert [p["ticker"] for p in result["payers"]] == ["KO"]


def test_all_non_payers_gives_no_income_view():
    result = compute_portfolio_income([_non_payer("TSLA", 5000.0)])
    assert result["has_data"] is False
    assert result["total_annual_income"] == 0.0
    assert result["portfolio_yield"] is None


def test_empty_portfolio():
    result = compute_portfolio_income([])
    assert result["has_data"] is False
    assert not result["payers"]


def test_a_rate_without_shares_earns_nothing_but_is_not_a_payer_row():
    # A holding with 0 shares can't produce income; don't invent it.
    result = compute_portfolio_income([_payer("KO", 0.0, 0, 2.0, 0.02)])
    assert result["total_annual_income"] == 0.0
    assert result["has_data"] is False


def test_absurd_rate_is_rejected_as_bad_data():
    # A per-share dividend larger than the share price is not real.
    result = compute_portfolio_income([
        _payer("BOGUS", 1000.0, 100, 500.0, 5.0),  # $500/share dividend
    ])
    assert "BOGUS" in result["coverage"]["non_payers"]
    assert result["total_annual_income"] == 0.0


def test_payer_carries_the_ex_dividend_date():
    row = _payer("KO", 8156.0, 100, 2.12, 0.026, ex_dividend_date="2026-09-15")
    result = compute_portfolio_income([row])
    assert result["payers"][0]["ex_dividend_date"] == "2026-09-15"


def test_payer_without_an_ex_date_is_fine():
    result = compute_portfolio_income([_payer("KO", 8156.0, 100, 2.12, 0.026)])
    assert result["payers"][0]["ex_dividend_date"] is None
