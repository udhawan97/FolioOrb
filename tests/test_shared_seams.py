"""The small seams extracted to stop the same rule being written twice.

Each class here covers one definition that used to exist in two or three places
with drifting behaviour: what a usable price is, what a ticker looks like, how
concentration is banded, and how a return series is annualised.
"""
import math

import numpy as np
import pytest

from app.services import portfolio_exposure, returns_math, ticker, verdict_pipeline
from app.services.stock_service import usable_price


class TestUsablePrice:
    def test_a_normal_quote_passes_through(self):
        assert usable_price({"current_price": 189.5}) == 189.5

    def test_missing_zero_and_negative_are_rejected(self):
        assert usable_price({}) is None
        assert usable_price({"current_price": None}) is None
        assert usable_price({"current_price": 0}) is None
        assert usable_price({"current_price": -5.0}) is None

    def test_non_numeric_is_rejected_rather_than_raising(self):
        assert usable_price({"current_price": "n/a"}) is None

    def test_nan_and_inf_are_rejected(self):
        """The whole reason this function exists.

        `float("nan") or 0` evaluates to NaN, because NaN is truthy — so the
        common idiom this replaced let NaN straight through into arithmetic.
        """
        assert usable_price({"current_price": float("nan")}) is None
        assert usable_price({"current_price": float("inf")}) is None


class TestAllocationPercents:
    def _positions(self, **shares):
        return {
            symbol: {"shares": count, "avg_cost": 10.0,
                     "is_watchlist": False, "hold_class": "auto"}
            for symbol, count in shares.items()
        }

    def test_weights_are_shares_times_price_over_the_book(self):
        alloc = verdict_pipeline._allocation_pcts(  # pylint: disable=protected-access
            self._positions(AAA=10, BBB=10),
            {"AAA": {"current_price": 30.0}, "BBB": {"current_price": 10.0}},
        )
        assert alloc == {"AAA": 75.0, "BBB": 25.0}

    def test_watchlist_rows_are_excluded_entirely(self):
        positions = self._positions(AAA=10)
        positions["WATCH"] = {"shares": 100, "avg_cost": 1.0,
                              "is_watchlist": True, "hold_class": "auto"}
        alloc = verdict_pipeline._allocation_pcts(  # pylint: disable=protected-access
            positions,
            {"AAA": {"current_price": 10.0}, "WATCH": {"current_price": 10.0}},
        )
        assert alloc == {"AAA": 100.0}

    def test_one_nan_price_cannot_poison_every_weight(self):
        """The bug: NaN survived `or 0`, so total_value went NaN, `<= 0` was
        False, and every holding's weight came back NaN — into the HHI and the
        Claude prompt."""
        alloc = verdict_pipeline._allocation_pcts(  # pylint: disable=protected-access
            self._positions(GOOD=10, BAD=10),
            {"GOOD": {"current_price": 50.0},
             "BAD": {"current_price": float("nan")}},
        )
        assert all(math.isfinite(pct) for pct in alloc.values())
        assert alloc["GOOD"] == 100.0
        assert alloc["BAD"] == 0.0

    def test_an_entirely_unpriced_book_yields_no_weights(self):
        alloc = verdict_pipeline._allocation_pcts(  # pylint: disable=protected-access
            self._positions(AAA=10), {"AAA": {"current_price": 0}}
        )
        assert alloc == {}


class TestTickerShape:
    def test_normalisation_is_trim_and_upper(self):
        assert ticker.normalize_ticker("  brk.b ") == "BRK.B"
        assert ticker.normalize_ticker(None) == ""

    def test_common_yfinance_shapes_are_accepted(self):
        for symbol in ("VOO", "BRK.B", "BTC-USD", "^GSPC"):
            assert ticker.ticker_shape_is_safe(symbol)

    def test_injection_shaped_input_is_rejected(self):
        for symbol in ("');x//", "A" * 11, "", "VO O"):
            assert not ticker.ticker_shape_is_safe(symbol)

    def test_the_raising_form_returns_the_normalised_symbol(self):
        assert ticker.validated_ticker_shape(" voo ") == "VOO"

    def test_the_schemas_and_the_services_share_one_pattern(self):
        """They used to compile the same regex independently."""
        from app import schemas  # noqa: PLC0415
        from app.services import stock_service  # noqa: PLC0415

        assert stock_service.TICKER_PATTERN is ticker.TICKER_PATTERN
        assert schemas.validated_ticker_shape is ticker.validated_ticker_shape


class TestConcentrationBands:
    def test_band_and_prose_come_from_the_same_cutoffs(self):
        pairs = [
            (0.05, "low", "well spread"),
            (0.15, "medium", "moderately concentrated"),
            (0.30, "high", "concentrated"),
            (0.60, "very high", "very concentrated"),
        ]
        for hhi, band, word in pairs:
            assert portfolio_exposure.concentration_band(hhi) == band
            assert portfolio_exposure.concentration_word(hhi) == word

    def test_cutoffs_are_lower_inclusive_at_the_flag_threshold(self):
        assert portfolio_exposure.concentration_band(0.25) == "high"
        assert portfolio_exposure.CONCENTRATION_FLAG_HHI == 0.25

    def test_one_hhi_no_longer_gets_two_verdicts(self):
        """0.30 was "high" in the action plan and "moderately concentrated" in
        the analytics narration — the same book, two answers, one page."""
        from app.services import analytics_insights  # noqa: PLC0415

        hhi = 0.30
        assert portfolio_exposure.concentration_band(hhi) == "high"
        assert analytics_insights._concentration_word(hhi) == "concentrated"  # pylint: disable=protected-access


class TestReturnsMath:
    def test_log_returns_of_a_flat_series_are_zero(self):
        assert np.allclose(returns_math.log_returns([100.0, 100.0, 100.0]), 0.0)

    def test_a_series_shorter_than_two_has_no_returns(self):
        assert returns_math.log_returns([100.0]).size == 0
        assert returns_math.log_returns([]).size == 0

    def test_non_positive_closes_do_not_propagate_nan(self):
        for series in ([100.0, 0.0, 100.0], [100.0, -5.0, 100.0]):
            assert np.isfinite(returns_math.log_returns(series)).all()

    def test_annualized_refuses_to_guess_on_thin_history(self):
        assert returns_math.annualized(np.zeros(4)) is None

    def test_annualized_scales_by_the_trading_year(self):
        daily = np.full(returns_math.TRADING_DAYS, 0.001)
        mu, sigma = returns_math.annualized(daily)
        assert mu == pytest.approx(0.001 * returns_math.TRADING_DAYS)
        assert sigma == pytest.approx(0.0)  # a constant series has no dispersion

    def test_both_callers_apply_their_own_fallback_to_the_same_core(self):
        """Analytics reports measured zeros; the projection needs a live cone."""
        from app.services import portfolio_analytics, portfolio_projection  # noqa: PLC0415

        thin = np.zeros(2)
        assert portfolio_analytics._annualize_stats(thin) == (0.0, 0.0)  # pylint: disable=protected-access
        assert portfolio_projection._annualize_stats(thin) == (0.08, 0.15)  # pylint: disable=protected-access
