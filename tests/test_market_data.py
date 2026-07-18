"""Behaviour tests for the market-data seam.

Two adapters have to agree on one contract: `YFinanceAdapter` normalising a
hostile vendor, and `FakeMarketData` standing in for it. These tests pin the
contract from both sides — no network, and no monkeypatching of yfinance
internals beyond the stub vendor handed to the adapter under test.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services import market_data


# ── Stub vendor: the shape yfinance presents, with failures on demand ─────────

class _StubTicker:
    """One vendor handle. Each surface is a value to return or an error to raise."""

    def __init__(self, **surfaces):
        self._surfaces = surfaces
        self.history_kwargs = None
        self.earnings_limit = None

    def _surface(self, name):
        value = self._surfaces.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    @property
    def info(self):
        return self._surface("info")

    @property
    def fast_info(self):
        return self._surface("fast_info")

    @property
    def news(self):
        return self._surface("news")

    @property
    def calendar(self):
        return self._surface("calendar")

    @property
    def dividends(self):
        return self._surface("dividends")

    @property
    def funds_data(self):
        return self._surface("funds_data")

    def history(self, **kwargs):
        self.history_kwargs = kwargs
        return self._surface("history")

    def get_earnings_dates(self, limit=None):
        self.earnings_limit = limit
        return self._surface("earnings")


def _vendor(ticker=None, *, ticker_error=None, quotes=None, search_error=None):
    """A stand-in for the `yfinance` module itself."""
    def _make_ticker(_symbol):
        if ticker_error is not None:
            raise ticker_error
        return ticker

    def _make_search(_query, **kwargs):
        if search_error is not None:
            raise search_error
        return SimpleNamespace(quotes=quotes, kwargs=kwargs)

    return SimpleNamespace(Ticker=_make_ticker, Search=_make_search)


def _adapter(ticker=None, **kwargs):
    return market_data.YFinanceAdapter(vendor=_vendor(ticker, **kwargs))


def _price_frame():
    """Two clean sessions and one with a NaN close, as yfinance returns them."""
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [104.0, 105.5, float("nan")],
            "Volume": [1000.0, 1100.0, 1200.0],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"], utc=True),
    )


def _holdings_frame():
    return pd.DataFrame(
        {"Name": ["Apple Inc", None], "Holding Percent": [0.072, 0.051]},
        index=["AAPL", "MSFT"],
    )


def _earnings_frame():
    return pd.DataFrame(
        {
            "EPS Estimate": [1.89, 1.94],
            "Surprise(%)": [float("nan"), 3.46],
        },
        index=pd.to_datetime(
            ["2026-07-30 16:00:00-04:00", "2026-04-30 16:00:00-04:00"], utc=True
        ),
    )


# The whole contract as one comparable snapshot: an unavailable read is the empty
# value of its return type, and the module and an adapter answer to the same names.
_UNAVAILABLE = {
    "info": None,
    "fast_info": None,
    "history": [],
    "news": [],
    "earnings_estimates": [],
    "earnings_calendar": [],
    "dividend_dates": [],
    "fund_holdings": [],
    "search": [],
}


def _all_reads(reader, symbol="AAPL"):
    """Every accessor's answer for one symbol, from the module or from an adapter."""
    return {
        "info": reader.get_info(symbol),
        "fast_info": reader.get_fast_info(symbol),
        "history": reader.get_history(symbol, period="1y"),
        "news": reader.get_news(symbol),
        "earnings_estimates": reader.get_earnings_estimates(symbol),
        "earnings_calendar": reader.get_earnings_calendar(symbol),
        "dividend_dates": reader.get_dividend_dates(symbol),
        "fund_holdings": reader.get_fund_holdings(symbol),
        "search": reader.search(symbol),
    }


def _module_reads(symbol="AAPL"):
    """The module's reads, plus `get_closes`, which only the module derives."""
    return {**_all_reads(market_data, symbol), "closes": market_data.get_closes(symbol)}


@pytest.fixture(autouse=True)
def _restore_adapter():
    """Every test hands the module back the adapter it found installed."""
    previous = market_data.get_adapter()
    yield
    market_data.set_adapter(previous)


def _install(adapter):
    """Install an adapter and hand it straight back, for terse arrange steps."""
    market_data.set_adapter(adapter)
    return adapter


# ── The seam ─────────────────────────────────────────────────────────────────

def test_reads_go_to_whichever_adapter_is_installed():
    _install(market_data.FakeMarketData(info={"AAPL": {"longName": "Apple"}}))

    assert market_data.get_info("AAPL") == {"longName": "Apple"}


def test_the_default_adapter_is_the_vendor_one():
    """The suite runs on a fake, so the module's own default has to be asked for."""
    with market_data.use_adapter(None) as active:
        assert isinstance(active, market_data.YFinanceAdapter)


def test_set_adapter_hands_back_the_adapter_it_replaced():
    before = market_data.get_adapter()
    fake = market_data.FakeMarketData()

    assert market_data.set_adapter(fake) is before
    assert market_data.get_adapter() is fake


def test_set_adapter_none_restores_the_vendor_adapter():
    _install(market_data.FakeMarketData())
    market_data.set_adapter(None)

    assert isinstance(market_data.get_adapter(), market_data.YFinanceAdapter)


def test_use_adapter_swaps_for_the_block_only():
    before = market_data.get_adapter()
    fake = market_data.FakeMarketData()

    with market_data.use_adapter(fake) as active:
        assert active is fake
        assert market_data.get_adapter() is fake

    assert market_data.get_adapter() is before


def test_use_adapter_restores_even_when_the_block_raises():
    before = market_data.get_adapter()

    with pytest.raises(RuntimeError):
        with market_data.use_adapter(market_data.FakeMarketData()):
            raise RuntimeError("caller blew up")

    assert market_data.get_adapter() is before


# ── Every accessor, through the fake ─────────────────────────────────────────

def test_each_accessor_reads_its_preloaded_table():
    _install(market_data.FakeMarketData(
        info={"AAPL": {"longName": "Apple"}},
        fast_info={"AAPL": {"last_price": 190.0}},
        history={"AAPL": [{"date": "2026-01-02", "close": 104.0}]},
        news={"AAPL": [{"id": "n1"}]},
        earnings_estimates={"AAPL": [{"date": date(2026, 7, 30), "eps_estimate": 1.89}]},
        earnings_calendar={"AAPL": [date(2026, 7, 30)]},
        dividend_dates={"AAPL": [date(2026, 2, 9), date(2026, 5, 11)]},
        fund_holdings={"VOO": [{"symbol": "AAPL", "name": "Apple Inc", "weight": 7.2}]},
        search={"apple": [{"symbol": "AAPL"}]},
    ))

    assert market_data.get_info("AAPL") == {"longName": "Apple"}
    assert market_data.get_fast_info("AAPL") == {"last_price": 190.0}
    assert market_data.get_history("AAPL") == [{"date": "2026-01-02", "close": 104.0}]
    assert market_data.get_closes("AAPL") == [104.0]
    assert market_data.get_news("AAPL") == [{"id": "n1"}]
    assert market_data.get_earnings_estimates("AAPL")[0]["eps_estimate"] == 1.89
    assert market_data.get_earnings_calendar("AAPL") == [date(2026, 7, 30)]
    assert market_data.get_dividend_dates("AAPL") == [date(2026, 2, 9), date(2026, 5, 11)]
    assert market_data.get_fund_holdings("VOO")[0]["weight"] == 7.2
    assert market_data.search("apple") == [{"symbol": "AAPL"}]


def test_unknown_keys_read_as_the_empty_value_of_each_return_type():
    _install(market_data.FakeMarketData())

    assert _module_reads("NOPE") == {**_UNAVAILABLE, "closes": []}


def test_symbols_are_normalised_before_any_adapter_sees_them():
    fake = _install(market_data.FakeMarketData(info={"aapl": {"longName": "Apple"}}))

    assert market_data.get_info("  aapl ") == {"longName": "Apple"}
    assert fake.calls == [("get_info", "AAPL")]


def test_search_queries_match_regardless_of_case_and_spacing():
    _install(market_data.FakeMarketData(search={"Apple Inc": [{"symbol": "AAPL"}]}))

    assert market_data.search(" apple inc ") == [{"symbol": "AAPL"}]


def test_the_fake_records_every_read_in_order():
    fake = _install(market_data.FakeMarketData())

    market_data.get_info("AAPL")
    market_data.get_closes("SPY", period="1y")

    assert fake.calls == [("get_info", "AAPL"), ("get_history", "SPY")]


def test_the_fake_hands_out_copies_so_a_caller_cannot_corrupt_it():
    _install(market_data.FakeMarketData(
        info={"AAPL": {"longName": "Apple"}},
        history={"AAPL": [{"close": 104.0}]},
    ))

    market_data.get_info("AAPL")["longName"] = "mutated"
    market_data.get_history("AAPL")[0]["close"] = 0.0

    assert market_data.get_info("AAPL") == {"longName": "Apple"}
    assert market_data.get_history("AAPL") == [{"close": 104.0}]


def test_closes_keep_only_usable_prices_and_read_history_once():
    fake = _install(market_data.FakeMarketData(history={"SPY": [
        {"close": 104.0},
        {"close": None},
        {"close": 0.0},
        {"close": -3.0},
        {"close": float("nan")},
        {"close": 105.5},
    ]}))

    assert market_data.get_closes("SPY", period="1y") == [104.0, 105.5]
    assert fake.calls == [("get_history", "SPY")]


# ── Failure normalisation, through the vendor adapter ────────────────────────

def test_a_vendor_that_cannot_build_a_handle_reads_as_unavailable():
    assert _all_reads(_adapter(ticker_error=OSError("no network"))) == _UNAVAILABLE


def test_every_surface_that_raises_reads_as_unavailable():
    boom = RuntimeError("Yahoo rate-limited the scrape")
    adapter = _adapter(
        _StubTicker(
            info=boom,
            fast_info=boom,
            history=boom,
            news=boom,
            earnings=boom,
            calendar=boom,
            funds_data=boom,
        ),
        search_error=boom,
    )

    assert _all_reads(adapter) == _UNAVAILABLE


def test_an_absent_vendor_package_reads_as_unavailable(monkeypatch):
    monkeypatch.setattr(market_data, "_yfinance", None)

    assert _all_reads(market_data.YFinanceAdapter()) == _UNAVAILABLE


def test_empty_vendor_payloads_read_as_empty_not_as_failure():
    adapter = _adapter(_StubTicker(
        info={},
        history=pd.DataFrame(),
        news=None,
        earnings=pd.DataFrame(),
        calendar={},
        funds_data=SimpleNamespace(top_holdings=pd.DataFrame()),
    ))

    # A record read keeps "Yahoo said nothing" apart from "the read failed".
    assert _all_reads(adapter) == {**_UNAVAILABLE, "info": {}}


def test_a_none_info_payload_still_reads_as_an_empty_record():
    assert _adapter(_StubTicker(info=None)).get_info("AAPL") == {}


# ── Shapes handed back by the vendor adapter ─────────────────────────────────

def test_history_bars_are_plain_python_oldest_first():
    adapter = _adapter(_StubTicker(history=_price_frame()))

    bars = adapter.get_history("AAPL", period="1mo")

    assert [row["date"] for row in bars] == ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert bars[0] == {
        "date": "2026-01-02",
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 104.0,
        "volume": 1000.0,
    }
    assert type(bars[0]["close"]) is float  # pylint: disable=unidiomatic-typecheck
    # NaN is missing data, not a price.
    assert bars[2]["close"] is None


def test_closes_come_out_of_the_bars_already_cleaned():
    with market_data.use_adapter(_adapter(_StubTicker(history=_price_frame()))):
        assert market_data.get_closes("AAPL", period="1y") == [104.0, 105.5]


def test_history_forwards_a_period_window_without_start_and_end():
    ticker = _StubTicker(history=_price_frame())
    _adapter(ticker).get_history("AAPL", period="5y", interval="1wk", auto_adjust=False)

    assert ticker.history_kwargs == {
        "period": "5y",
        "interval": "1wk",
        "auto_adjust": False,
    }


def test_history_forwards_a_date_window_without_a_period():
    ticker = _StubTicker(history=_price_frame())
    _adapter(ticker).get_history("AAPL", start="2026-01-01", end="2026-02-01")

    assert ticker.history_kwargs == {
        "start": "2026-01-01",
        "end": "2026-02-01",
        "interval": "1d",
        "auto_adjust": True,
    }


def test_fast_info_is_a_plain_dict_of_the_fields_callers_use():
    fast = SimpleNamespace(
        currency="USD",
        day_high=191.0,
        day_low=188.0,
        last_price=190.0,
        last_volume=5_000_000,
        market_cap=2_900_000_000_000,
        previous_close=189.0,
        year_high=199.0,
        year_low=140.0,
    )

    assert _adapter(_StubTicker(fast_info=fast)).get_fast_info("AAPL") == {
        "currency": "USD",
        "day_high": 191.0,
        "day_low": 188.0,
        "last_price": 190.0,
        "last_volume": 5_000_000.0,
        "market_cap": 2_900_000_000_000.0,
        "previous_close": 189.0,
        "year_high": 199.0,
        "year_low": 140.0,
    }


def test_fast_info_accepts_the_older_fifty_two_week_field_names():
    fast = SimpleNamespace(fifty_two_week_high=199.0, fifty_two_week_low=140.0)

    snapshot = _adapter(_StubTicker(fast_info=fast)).get_fast_info("AAPL")

    assert snapshot["year_high"] == 199.0
    assert snapshot["year_low"] == 140.0


def test_one_unreadable_fast_info_field_does_not_lose_the_others():
    class _HalfBrokenFastInfo:
        last_price = 190.0

        @property
        def market_cap(self):
            raise RuntimeError("that one field needs another scrape")

    snapshot = _adapter(_StubTicker(fast_info=_HalfBrokenFastInfo())).get_fast_info("AAPL")

    assert snapshot["last_price"] == 190.0
    assert snapshot["market_cap"] is None


def test_fund_holdings_come_back_in_percentage_points():
    frame = _holdings_frame()

    holdings = _adapter(_StubTicker(
        funds_data=SimpleNamespace(top_holdings=frame)
    )).get_fund_holdings("VOO")

    assert holdings == [
        {"symbol": "AAPL", "name": "Apple Inc", "weight": pytest.approx(7.2)},
        # A nameless row falls back to its symbol.
        {"symbol": "MSFT", "name": "MSFT", "weight": pytest.approx(5.1)},
    ]


def test_earnings_estimates_carry_plain_dates_and_none_for_unreported_quarters():
    rows = _adapter(_StubTicker(earnings=_earnings_frame())).get_earnings_estimates("AAPL")

    assert rows == [
        {"date": date(2026, 7, 30), "eps_estimate": 1.89, "surprise_pct": None},
        {"date": date(2026, 4, 30), "eps_estimate": 1.94, "surprise_pct": 3.46},
    ]


def test_the_earnings_limit_reaches_the_vendor():
    ticker = _StubTicker(earnings=_earnings_frame())
    _adapter(ticker).get_earnings_estimates("AAPL", limit=4)

    assert ticker.earnings_limit == 4


def test_the_earnings_calendar_reads_the_current_dict_shape():
    calendar = {"Earnings Date": [date(2026, 7, 30), date(2026, 7, 31)]}

    dates = _adapter(_StubTicker(calendar=calendar)).get_earnings_calendar("AAPL")

    assert dates == [date(2026, 7, 30), date(2026, 7, 31)]


def test_dividend_dates_normalise_the_vendor_series():
    """The vendor hands back a pandas Series indexed by timestamp; callers get dates."""
    series = pd.Series([0.24, 0.25], index=pd.to_datetime(["2026-02-09", "2026-05-11"]))

    dates = _adapter(_StubTicker(dividends=series)).get_dividend_dates("AAPL")

    assert dates == [date(2026, 2, 9), date(2026, 5, 11)]


def test_dividend_dates_are_empty_for_a_non_payer():
    assert _adapter(_StubTicker(dividends=pd.Series(dtype=float))).get_dividend_dates("X") == []


def test_dividend_dates_survive_a_vendor_error():
    stub = _StubTicker(dividends=RuntimeError("upstream is down"))

    assert _adapter(stub).get_dividend_dates("AAPL") == []


def test_the_earnings_calendar_reads_a_lone_timestamp():
    calendar = {"Earnings Date": pd.Timestamp("2026-07-30 16:00:00")}

    assert _adapter(_StubTicker(calendar=calendar)).get_earnings_calendar("AAPL") == [
        date(2026, 7, 30)
    ]


def test_the_earnings_calendar_reads_the_older_frame_shape():
    """Older yfinance returned a frame whose "Earnings Date" row holds the dates."""
    calendar = pd.DataFrame(
        [[pd.Timestamp("2026-07-30"), pd.Timestamp("2026-07-31")]],
        index=["Earnings Date"],
        columns=["Value", "Value 1"],
    )

    dates = _adapter(_StubTicker(calendar=calendar)).get_earnings_calendar("AAPL")

    assert dates == [date(2026, 7, 30), date(2026, 7, 31)]


def test_an_unrecognised_calendar_shape_reads_as_no_dates():
    assert not _adapter(_StubTicker(calendar="next tuesday")).get_earnings_calendar("A")


def test_news_items_pass_through_untouched():
    items = [{"id": "n1", "content": {"title": "Something happened"}}]

    assert _adapter(_StubTicker(news=items)).get_news("AAPL") == items


def test_search_returns_the_raw_matches():
    assert _adapter(quotes=[{"symbol": "AAPL"}]).search("apple", limit=3) == [
        {"symbol": "AAPL"}
    ]


def test_search_passes_the_limit_and_safe_defaults_to_the_vendor():
    captured = {}

    def _make_search(query, **kwargs):
        captured.update(kwargs)
        captured["query"] = query
        return SimpleNamespace(quotes=[])

    vendor = SimpleNamespace(Ticker=lambda _s: None, Search=_make_search)
    market_data.YFinanceAdapter(vendor=vendor).search("apple", limit=3)

    assert captured["query"] == "apple"
    assert captured["max_results"] == 3
    assert captured["raise_errors"] is False
    assert captured["news_count"] == 0
