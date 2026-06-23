"""
Tests for app/services/holding_intelligence.py and move attribution logic.
No real network calls — yfinance is mocked where needed.
"""
from unittest.mock import patch, MagicMock

from app.services.holding_intelligence import (
    get_holding_intelligence,
    intelligence_to_dict,
    COVERAGE_TYPE_LABELS,
    TopHolding,
    _STATIC,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

IBIT_STOCK_DATA = {
    "ticker": "IBIT",
    "name": "iShares Bitcoin Trust ETF",
    "quote_type": "ETF",
    "sector": "N/A",
    "current_price": 45.00,
    "day_change_pct": 3.2,
}

NOW_STOCK_DATA = {
    "ticker": "NOW",
    "name": "ServiceNow, Inc.",
    "quote_type": "EQUITY",
    "sector": "Technology",
    "current_price": 920.00,
    "day_change_pct": 1.5,
}

VOO_STOCK_DATA = {
    "ticker": "VOO",
    "name": "Vanguard S&P 500 ETF",
    "quote_type": "ETF",
    "sector": "N/A",
    "current_price": 530.00,
    "day_change_pct": 0.5,
}

UNKNOWN_STOCK_DATA = {
    "ticker": "XYZ",
    "name": "Unknown Corp",
    "quote_type": "EQUITY",
    "sector": "Technology",
    "current_price": 100.00,
    "day_change_pct": 0.0,
}


# ── Static metadata coverage ──────────────────────────────────────────────────

class TestStaticMetadataCompleteness:
    DEFAULT_TICKERS = ["NOW", "QTUM", "VOO", "CGDV", "IBIT", "VT", "ITA", "IEMG", "SETM", "WSML"]

    def test_all_default_tickers_have_metadata(self):
        for ticker in self.DEFAULT_TICKERS:
            assert ticker in _STATIC, f"{ticker} missing from static metadata"

    def test_all_metadata_has_required_fields(self):
        required = ["coverage_type", "strategy", "asset_class", "benchmark_tickers",
                    "benchmark_labels", "key_drivers"]
        for ticker, meta in _STATIC.items():
            for field in required:
                assert field in meta and meta[field], f"{ticker} missing required field: {field}"

    def test_ibit_has_crypto_coverage_type(self):
        assert _STATIC["IBIT"]["coverage_type"] == "etf-crypto"

    def test_ibit_benchmark_is_btc(self):
        assert "BTC-USD" in _STATIC["IBIT"]["benchmark_tickers"]
        assert "SPY" not in _STATIC["IBIT"]["benchmark_tickers"]
        assert "QQQ" not in _STATIC["IBIT"]["benchmark_tickers"]

    def test_voo_benchmark_is_spy(self):
        assert "SPY" in _STATIC["VOO"]["benchmark_tickers"]
        assert "QQQ" not in _STATIC["VOO"]["benchmark_tickers"]

    def test_iemg_has_eem_benchmark(self):
        assert "EEM" in _STATIC["IEMG"]["benchmark_tickers"]

    def test_ita_has_defense_benchmark(self):
        assert "XAR" in _STATIC["ITA"]["benchmark_tickers"]

    def test_setm_has_commodity_benchmarks(self):
        bms = _STATIC["SETM"]["benchmark_tickers"]
        assert any(b in bms for b in ["LIT", "COPX", "XME"]), (
            "SETM should have commodity benchmarks"
        )

    def test_all_etfs_have_sector_data(self):
        etf_tickers = [t for t, m in _STATIC.items() if m["coverage_type"] != "equity"]
        for ticker in etf_tickers:
            meta = _STATIC[ticker]
            # Crypto ETF has no sectors by design
            if meta["coverage_type"] == "etf-crypto":
                assert meta["sectors"] == []
            else:
                assert meta["sectors"], f"{ticker} should have sector data"

    def test_concentration_level_is_valid(self):
        valid = {"very-low", "low", "medium", "high"}
        for ticker, meta in _STATIC.items():
            level = meta.get("concentration_level")
            assert level in valid, f"{ticker} has invalid concentration_level: {level}"


# ── get_holding_intelligence ──────────────────────────────────────────────────

class TestGetHoldingIntelligence:
    def test_ibit_returns_crypto_coverage(self):
        intel = get_holding_intelligence("IBIT", IBIT_STOCK_DATA)
        assert intel.coverage_type == "etf-crypto"
        assert intel.asset_class == "crypto"
        assert intel.theme == "Bitcoin"

    def test_ibit_benchmark_is_btc_not_spy(self):
        intel = get_holding_intelligence("IBIT", IBIT_STOCK_DATA)
        assert "BTC-USD" in intel.benchmark_tickers
        assert "SPY" not in intel.benchmark_tickers
        assert "QQQ" not in intel.benchmark_tickers

    def test_now_returns_equity_coverage(self):
        intel = get_holding_intelligence("NOW", NOW_STOCK_DATA)
        assert intel.coverage_type == "equity"
        assert intel.asset_class == "equities"

    def test_now_has_peer_tickers(self):
        intel = get_holding_intelligence("NOW", NOW_STOCK_DATA)
        assert len(intel.peer_tickers) > 0
        assert any(p in intel.peer_tickers for p in ["CRM", "WDAY", "SNOW"])

    def test_voo_has_spy_benchmark(self):
        intel = get_holding_intelligence("VOO", VOO_STOCK_DATA)
        assert "SPY" in intel.benchmark_tickers

    def test_voo_has_sector_data(self):
        intel = get_holding_intelligence("VOO", VOO_STOCK_DATA)
        assert len(intel.sectors) > 0
        total = sum(s.weight for s in intel.sectors)
        assert 90 <= total <= 110, f"Sector weights should sum near 100, got {total}"

    def test_iemg_has_country_data(self):
        intel = get_holding_intelligence("IEMG", None)
        assert len(intel.countries) > 0
        country_names = [c.name for c in intel.countries]
        assert any("China" in n or "India" in n or "Taiwan" in n for n in country_names)

    def test_ita_has_top_holdings(self):
        intel = get_holding_intelligence("ITA", None)
        assert len(intel.top_holdings) > 0
        tickers = [h.ticker for h in intel.top_holdings]
        assert any(t in tickers for t in ["RTX", "LMT", "GD", "NOC", "BA"])

    def test_static_etf_keeps_extended_live_holdings_for_contributions(self):
        live_holdings = [
            TopHolding(ticker=f"H{i}", name=f"Holding {i}", weight=1.0)
            for i in range(8)
        ]
        with patch("app.services.holding_intelligence._try_yfinance_enrichment") as mock_yf:
            mock_yf.return_value = ([], [], live_holdings)
            intel = get_holding_intelligence("IEMG", None)

        assert len(intel.top_holdings) == 8
        assert intel.top_holdings[-1].ticker == "H7"

    def test_unknown_ticker_returns_derived_intelligence(self):
        with patch("app.services.holding_intelligence._try_yfinance_enrichment") as mock_yf:
            mock_yf.return_value = ([], [], [])
            intel = get_holding_intelligence("XYZ", UNKNOWN_STOCK_DATA)
        assert intel.ticker == "XYZ"
        assert intel.coverage_type in ("equity", "etf-sector")

    def test_ticker_normalized_to_upper(self):
        intel = get_holding_intelligence("voo", VOO_STOCK_DATA)
        assert intel.ticker == "VOO"

    def test_coverage_label_is_human_readable(self):
        intel = get_holding_intelligence("IBIT", IBIT_STOCK_DATA)
        assert intel.coverage_label in COVERAGE_TYPE_LABELS.values()
        assert intel.coverage_label != "etf-crypto"

    def test_data_quality_is_static_without_yfinance(self):
        intel = get_holding_intelligence("NOW", NOW_STOCK_DATA)
        assert intel.data_quality in ("static", "partial", "live")
        assert "static_metadata" in intel.data_sources

    def test_key_drivers_are_non_empty_for_all_defaults(self):
        tickers = ["NOW", "QTUM", "VOO", "CGDV", "IBIT", "VT", "ITA", "IEMG", "SETM", "WSML"]
        for ticker in tickers:
            intel = get_holding_intelligence(ticker, None)
            assert len(intel.key_drivers) > 0, f"{ticker} should have key_drivers"

    def test_expense_ratio_present_for_etfs(self):
        etf_tickers = ["VOO", "VT", "IBIT", "ITA", "IEMG", "QTUM"]
        for ticker in etf_tickers:
            intel = get_holding_intelligence(ticker, None)
            assert intel.expense_ratio is not None, f"{ticker} ETF should have expense_ratio"

    def test_now_equity_has_no_expense_ratio(self):
        intel = get_holding_intelligence("NOW", NOW_STOCK_DATA)
        assert intel.expense_ratio is None


# ── intelligence_to_dict ──────────────────────────────────────────────────────

class TestIntelligenceToDict:
    def test_returns_json_serializable_dict(self):
        import json
        intel = get_holding_intelligence("IBIT", IBIT_STOCK_DATA)
        d = intelligence_to_dict(intel)
        # Should not raise
        json.dumps(d)

    def test_dict_has_required_keys(self):
        intel = get_holding_intelligence("VOO", VOO_STOCK_DATA)
        d = intelligence_to_dict(intel)
        required = ["ticker", "coverage_type", "coverage_label", "strategy", "asset_class",
                    "sectors", "countries", "top_holdings", "benchmark_tickers",
                    "benchmark_labels", "peer_tickers", "key_drivers",
                    "concentration_level", "concentration_label", "data_quality", "data_sources"]
        for key in required:
            assert key in d, f"intelligence_to_dict missing key: {key}"

    def test_expense_ratio_bps_calculation(self):
        intel = get_holding_intelligence("VOO", VOO_STOCK_DATA)
        d = intelligence_to_dict(intel)
        assert d["expense_ratio_bps"] == 3  # 0.0003 * 10000 = 3

    def test_ibit_expense_ratio_bps(self):
        intel = get_holding_intelligence("IBIT", IBIT_STOCK_DATA)
        d = intelligence_to_dict(intel)
        assert d["expense_ratio_bps"] == 25  # 0.0025 * 10000 = 25

    def test_sectors_are_serialized_correctly(self):
        intel = get_holding_intelligence("VOO", VOO_STOCK_DATA)
        d = intelligence_to_dict(intel)
        assert isinstance(d["sectors"], list)
        for s in d["sectors"]:
            assert "name" in s and "weight" in s

    def test_countries_are_serialized_correctly(self):
        intel = get_holding_intelligence("IEMG", None)
        d = intelligence_to_dict(intel)
        assert isinstance(d["countries"], list)
        for c in d["countries"]:
            assert "name" in c and "weight" in c


# ── Move explainer benchmark logic ───────────────────────────────────────────

class TestMoveExplainerBenchmarks:
    """Verify that per-holding benchmarks are selected correctly."""

    def _mock_yf_ticker(self, chg_pct):
        info = MagicMock()
        info.get = lambda key, default=None: {
            "currentPrice": 100.0,
            "regularMarketPrice": 100.0,
            "previousClose": 100.0 / (1 + chg_pct / 100),
            "regularMarketPreviousClose": 100.0 / (1 + chg_pct / 100),
        }.get(key, default)
        ticker_mock = MagicMock()
        ticker_mock.info = info
        ticker_mock.calendar = None
        return ticker_mock

    def test_ibit_uses_btc_benchmark(self):
        from app.services.move_explainer import _TICKER_BENCHMARKS
        cfg = _TICKER_BENCHMARKS.get("IBIT", {})
        assert cfg.get("primary") == "BTC-USD"
        assert cfg.get("suppress_spy") is True
        assert cfg.get("suppress_qqq") is True

    def test_ibit_explanation_mentions_bitcoin(self):
        from app.services.move_explainer import explain_move

        ibit_data = {
            "ticker": "IBIT",
            "day_change_pct": 3.5,
            "day_change": 1.5,
            "quote_type": "ETF",
            "sector": "N/A",
            "volume": 1000000,
            "average_volume": 1000000,
        }
        benchmarks = {"SPY": 0.2, "QQQ": 0.3}

        with patch("app.services.move_explainer._day_change_pct") as mock_chg:
            mock_chg.return_value = 3.4  # BTC change
            result = explain_move(ibit_data, shared_benchmarks=benchmarks)

        assert "Bitcoin" in result.explanation_text or "BTC" in result.explanation_text
        assert result.macro_context.suppress_spy is True
        assert result.macro_context.suppress_qqq is True
        assert result.macro_context.primary_benchmark == "BTC-USD"

    def test_voo_uses_spy_not_qqq(self):
        from app.services.move_explainer import _TICKER_BENCHMARKS
        cfg = _TICKER_BENCHMARKS.get("VOO", {})
        assert cfg.get("primary") == "SPY"
        assert cfg.get("suppress_qqq") is True

    def test_iemg_does_not_use_nasdaq(self):
        from app.services.move_explainer import _TICKER_BENCHMARKS
        cfg = _TICKER_BENCHMARKS.get("IEMG", {})
        assert cfg.get("suppress_qqq") is True
        assert cfg.get("suppress_spy") is True
        assert cfg.get("primary") == "EEM"

    def test_ita_uses_defense_benchmark(self):
        from app.services.move_explainer import _TICKER_BENCHMARKS
        cfg = _TICKER_BENCHMARKS.get("ITA", {})
        assert cfg.get("primary") == "XAR"
        assert cfg.get("suppress_qqq") is True

    def test_macro_context_has_primary_benchmark_fields(self):
        from app.services.move_explainer import explain_move

        ibit_data = {
            "ticker": "IBIT",
            "day_change_pct": 2.0,
            "day_change": 0.9,
            "quote_type": "ETF",
            "sector": "N/A",
            "volume": 500000,
            "average_volume": 500000,
        }
        benchmarks = {"SPY": 0.3, "QQQ": 0.4}

        with patch("app.services.move_explainer._day_change_pct", return_value=2.1):
            result = explain_move(ibit_data, shared_benchmarks=benchmarks)

        assert result.macro_context is not None
        assert result.macro_context.primary_benchmark == "BTC-USD"
        assert result.macro_context.primary_benchmark_label == "Bitcoin"
        assert result.macro_context.primary_benchmark_chg is not None

    def test_now_explanation_does_not_only_say_spy(self):
        from app.services.move_explainer import explain_move

        now_data = {
            "ticker": "NOW",
            "day_change_pct": 3.8,
            "day_change": 36.0,
            "quote_type": "EQUITY",
            "sector": "Technology",
            "volume": 2000000,
            "average_volume": 1000000,  # high volume
        }
        benchmarks = {"SPY": 0.3, "QQQ": 0.4}

        with patch("yfinance.Ticker") as mock_yf:
            mock_instance = MagicMock()
            mock_instance.calendar = None
            mock_yf.return_value = mock_instance
            with patch("app.services.move_explainer._day_change_pct", return_value=2.0):
                result = explain_move(now_data, shared_benchmarks=benchmarks)

        # For NOW, the primary benchmark is IGV — the explanation should be company-specific
        # given high alpha vs IGV, not just "S&P 500 moved"
        assert result.macro_context.primary_benchmark == "IGV"
        # Should NOT attribute to broad market given 3.8% vs 0.3% SPY
        assert result.attribution_type in ("company-specific", "mixed", "sector-driven")

    def test_move_explanation_does_not_surface_news_activity(self):
        from app.services.move_explainer import explain_move

        csco_data = {
            "ticker": "CSCO",
            "day_change_pct": 1.66,
            "day_change": 1.99,
            "quote_type": "EQUITY",
            "sector": "Technology",
            "volume": 800000,
            "average_volume": 1000000,
        }
        benchmarks = {"SPY": -0.31, "QQQ": -0.36}

        with patch("yfinance.Ticker") as mock_yf:
            mock_instance = MagicMock()
            mock_instance.calendar = None
            mock_yf.return_value = mock_instance
            with patch("app.services.move_explainer._day_change_pct", return_value=0.49):
                result = explain_move(csco_data, shared_benchmarks=benchmarks)

        assert not hasattr(result, "news")
        assert all(driver.driver_type != "news" for driver in result.drivers)
        assert "News activity" not in result.explanation_text
        assert "Recent news" not in result.explanation_text

    def test_etf_attribution_uses_primary_benchmark_alpha(self):
        from app.services.move_explainer import explain_move

        vt_data = {
            "ticker": "VT",
            "day_change_pct": 0.8,
            "day_change": 0.3,
            "quote_type": "ETF",
            "sector": "N/A",
            "volume": 500000,
            "average_volume": 500000,
        }
        benchmarks = {"SPY": 0.5, "QQQ": 0.6}

        # ACWI returns 0.75% — VT closely tracks it
        with patch("app.services.move_explainer._day_change_pct", return_value=0.75):
            result = explain_move(vt_data, shared_benchmarks=benchmarks)

        assert result.macro_context.primary_benchmark == "ACWI"
        assert result.macro_context.suppress_qqq is True
