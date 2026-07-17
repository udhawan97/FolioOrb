"""The dividend fields leaving the chokepoint use consistent, honest units.

yfinance is treacherous here (all verified live 2026-07-17): `dividendYield` is
a PERCENT (AAPL 0.32 means 0.32%), while `trailingAnnualDividendYield` is a
FRACTION (AAPL 0.0031) — the same number, two fields, 100x apart. Meanwhile
every consumer (the AI prompt's `_dv * 100`, the frontend's percent formatter)
expects a fraction, so a sub-1% yield was rendering 100x too high. `dividendRate`
($/share) is the one unambiguous field. Normalize once, here.
"""
import math

from app.services.stock_service import _ex_dividend_date, _normalized_dividend


def test_yield_is_derived_from_rate_over_price_when_possible():
    # AAPL: rate $1.08, price $333.74 -> 0.32%, as a fraction.
    rate, yld = _normalized_dividend({"dividendRate": 1.08}, 333.74)
    assert rate == 1.08
    assert math.isclose(yld, 0.0032, abs_tol=0.0002)


def test_percent_yield_field_is_divided_when_no_rate():
    # SCHD: no dividendRate, dividendYield 3.3 (a percent) -> 0.033 fraction.
    rate, yld = _normalized_dividend({"dividendYield": 3.3}, 32.91)
    assert math.isclose(yld, 0.033, abs_tol=0.0005)
    # ...and the $/share rate is backfilled from yield x price.
    assert math.isclose(rate, 0.033 * 32.91, rel_tol=0.01)


def test_trailing_yield_field_is_already_a_fraction():
    # Only the trailing field is present, and it's a fraction — used as-is.
    _rate, yld = _normalized_dividend({"trailingAnnualDividendYield": 0.063}, 43.59)
    assert math.isclose(yld, 0.063, abs_tol=0.0005)


def test_a_non_payer_has_no_dividend():
    rate, yld = _normalized_dividend({}, 380.0)
    assert rate is None
    assert yld is None


def test_zero_rate_is_a_non_payer_not_a_zero_yield():
    rate, yld = _normalized_dividend({"dividendRate": 0.0}, 100.0)
    assert rate is None
    assert yld is None


def test_nan_and_negative_are_rejected():
    assert _normalized_dividend({"dividendRate": float("nan")}, 100.0) == (None, None)
    assert _normalized_dividend({"dividendRate": -1.0}, 100.0) == (None, None)


def test_a_low_yield_stock_never_reads_as_a_high_one():
    # The bug this guards: AAPL's 0.32% arriving as 0.32 and rendering as 32%.
    _rate, yld = _normalized_dividend({"dividendRate": 1.08}, 333.74)
    assert yld < 0.01  # well under 1%, as a fraction


def test_missing_price_still_yields_from_the_percent_field():
    # No price to divide by; fall back to the percent field, converted.
    _rate, yld = _normalized_dividend({"dividendYield": 2.5}, 0)
    assert math.isclose(yld, 0.025, abs_tol=0.0005)


# --- ex-dividend date normalization (unix seconds -> ISO date) ---


def test_ex_dividend_date_from_unix_timestamp():
    # 2026-05-11 in unix seconds.
    assert _ex_dividend_date({"exDividendDate": 1778457600}) == "2026-05-11"


def test_ex_dividend_date_absent():
    assert _ex_dividend_date({}) is None
    assert _ex_dividend_date({"exDividendDate": None}) is None


def test_ex_dividend_date_garbage():
    assert _ex_dividend_date({"exDividendDate": "soon"}) is None
