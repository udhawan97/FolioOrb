"""Interface tests for the Portfolio-briefing domain module.

Every face of the card is driven directly here — no router, no endpoint.  The
range key is the thing under test: one call site asks for a range and the module
decides everything that follows from it (which prices it reads, which fields the
payload carries, which cache slot it lands in).
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Portfolio
from app.services import portfolio_briefing


_HOLDINGS = [
    {
        "ticker": "AAPL", "current_price": 180.0, "shares": 10.0, "current_value": 1800.0,
        "daily_value_change": 36.0, "day_change_pct": 2.0, "unrealized_gain": 800.0,
        "allocation_pct": 60.0, "total_return_pct": 80.0, "is_watchlist": False,
        "avg_cost": 100.0,
    },
    {
        "ticker": "MSFT", "current_price": 320.0, "shares": 10.0, "current_value": 3200.0,
        "daily_value_change": -32.0, "day_change_pct": -1.0, "unrealized_gain": 1200.0,
        "allocation_pct": 40.0, "total_return_pct": 60.0, "is_watchlist": False,
        "avg_cost": 100.0,
    },
]

_QUOTES = [
    {"ticker": "AAPL", "current_price": 180.0, "day_change": 3.6, "day_change_pct": 2.0},
    {"ticker": "MSFT", "current_price": 320.0, "day_change": -3.2, "day_change_pct": -1.0},
]


def _valuation(monkeypatch, **overrides):
    row = {
        "holdings": _HOLDINGS,
        "total_value": 5000.0,
        "total_daily_change": 4.0,
        "total_cost_basis": 2000.0,
        "total_unrealized_gain": 800.0,
        "realized_gain": 200.0,
        "total_return": 1000.0,
        "total_return_pct": 50.0,
        "data_quality": "complete",
        "missing_tickers": (),
        "priced_position_count": 2,
        "expected_position_count": 2,
    }
    row.update(overrides)
    monkeypatch.setattr(
        "app.services.portfolio_valuation.evaluate",
        lambda _db, _pid: SimpleNamespace(**row),
    )


@pytest.fixture(name="db")
def _db():
    """A real session: the period snapshot reads Portfolio snapshot history."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(Portfolio(id=1, name="Test"))
    session.commit()
    return session


@pytest.fixture(name="book", autouse=True)
def _book(monkeypatch):
    """A complete, priced two-holding book with a known regime and price history."""
    _valuation(monkeypatch)
    monkeypatch.setattr(
        portfolio_briefing, "get_market_regime", lambda: {"label": "Risk-on", "mood": "warm"}
    )
    monkeypatch.setattr(portfolio_briefing, "get_all_quotes", lambda _tickers: _QUOTES)
    monkeypatch.setattr(
        portfolio_briefing, "get_benchmark_data", lambda: {"SPY": 1.0, "QQQ": 0.8}
    )
    monkeypatch.setattr(
        portfolio_briefing,
        "explain_move",
        lambda _sd, **_kw: SimpleNamespace(
            drivers=[SimpleNamespace(icon="bi-globe2")],
            explanation_text="AAPL moved +2.00% tracking the broad market.",
        ),
    )
    # 300 trading days of $1/day linear growth for every requested ticker.
    closes = [100.0 + i for i in range(300)]
    monkeypatch.setattr(
        "app.services.portfolio_analytics.get_batched_history_closes",
        lambda tickers, period="1y": {t: list(closes) for t in tickers},
    )


# ── Cache namespace ───────────────────────────────────────────────────────────

class TestCacheType:
    def test_day_keeps_the_legacy_slot_and_longer_ranges_get_their_own(self):
        assert portfolio_briefing.cache_type("day") == "briefing"
        assert portfolio_briefing.cache_type("week") == "briefing_week"
        assert portfolio_briefing.cache_type("threeMonth") == "briefing_threeMonth"

    def test_an_unknown_range_can_never_claim_its_own_slot(self):
        assert portfolio_briefing.cache_type("bogus") == "briefing"
        assert portfolio_briefing.cache_type(None) == "briefing"
        assert portfolio_briefing.cache_type() == "briefing"


# ── Snapshot ──────────────────────────────────────────────────────────────────

class TestBuildSnapshot:
    def test_the_day_snapshot_is_scoped_to_todays_tape(self, db):
        snapshot = portfolio_briefing.build_snapshot(db, "day")

        assert snapshot["total_value"] == 5000.0
        assert snapshot["today_pl"] == {"dollar": 4.0, "pct": 0.08}
        assert snapshot["best_today"] == {"ticker": "AAPL", "day_change_pct": 2.0}
        assert snapshot["worst_today"] == {"ticker": "MSFT", "day_change_pct": -1.0}
        assert snapshot["market_regime"] == {"label": "Risk-on", "mood": "warm"}
        assert snapshot["valuation"]["data_quality"] == "complete"
        assert [h["ticker"] for h in snapshot["top_holdings"]] == ["AAPL", "MSFT"]
        assert "period_pl" not in snapshot

    def test_a_period_snapshot_swaps_every_day_scoped_field_for_a_period_one(self, db):
        snapshot = portfolio_briefing.build_snapshot(db, "week")

        assert snapshot["period_label"] == "over the past week"
        for key in ("period_pl", "best_period", "worst_period", "period_contributors"):
            assert key in snapshot, f"period snapshot missing {key}"
        for key in ("today_pl", "best_today", "worst_today", "today_contributors"):
            assert key not in snapshot, f"period snapshot still carries {key}"
        # Top holdings are re-scored over the window too, not left on day change.
        assert all("period_change_pct" in h for h in snapshot["top_holdings"])
        assert all("day_change_pct" not in h for h in snapshot["top_holdings"])

    def test_an_unknown_range_is_normalised_rather_than_rejected(self, db):
        assert portfolio_briefing.build_snapshot(db, "bogus") == (
            portfolio_briefing.build_snapshot(db, "day")
        )

    def test_watchlist_rows_are_not_narrated_as_positions(self, db, monkeypatch):
        _valuation(
            monkeypatch,
            holdings=[*_HOLDINGS, {
                "ticker": "NVDA", "day_change_pct": 99.0, "allocation_pct": 5.0,
                "daily_value_change": 500.0, "total_return_pct": 0.0, "is_watchlist": True,
            }],
        )

        snapshot = portfolio_briefing.build_snapshot(db, "day")

        assert snapshot["best_today"]["ticker"] == "AAPL"
        assert "NVDA" not in [h["ticker"] for h in snapshot["top_holdings"]]


# ── Local digest ──────────────────────────────────────────────────────────────

class TestBuildLocal:
    @pytest.mark.parametrize(
        ("changes", "expected_lead"),
        [
            ((-2.0, -1.0),
             "All 2 holdings fell today; AAPL pulled back the most (-2.0%)."),
            ((0.0, 0.0), "Holdings were mixed today — no clear directional trend."),
        ],
        ids=["all-falling", "all-flat"],
    )
    def test_day_lead_handles_declines_and_zero_directional_moves(
        self, db, monkeypatch, changes, expected_lead
    ):
        holdings = [
            {**holding, "day_change_pct": change}
            for holding, change in zip(_HOLDINGS, changes)
        ]
        _valuation(monkeypatch, holdings=holdings)

        assert portfolio_briefing.build_local(db, "day")["lead"] == expected_lead

    def test_the_day_digest_carries_move_explanations(self, db):
        result = portfolio_briefing.build_local(db, "day")

        assert result["mode"] == "local"
        assert result["lead"] == "1 of 2 holdings rose today, led by AAPL (+2.0%)."
        assert "period_label" not in result
        aapl = next(m for m in result["movers"] if m["ticker"] == "AAPL")
        assert aapl["day_change_dollar"] == 36.0
        assert aapl["icon"] == "bi-globe2"
        assert aapl["explanation"].startswith("AAPL moved")

    def test_the_period_digest_reads_closes_and_carries_no_explanations(self, db):
        result = portfolio_briefing.build_local(db, "week")

        assert result["period_label"] == "over the past week"
        assert "past week" in result["lead"]
        aapl = next(m for m in result["movers"] if m["ticker"] == "AAPL")
        # 10 shares × 5 trading days × $1/day — period change, not day change.
        assert aapl["day_change_dollar"] == 50.0
        assert aapl["explanation"] == ""

    def test_an_unknown_range_falls_back_to_the_day_payload(self, db):
        assert "period_label" not in portfolio_briefing.build_local(db, "bogus")

    def test_an_unpriced_book_is_declared_rather_than_narrated(self, db, monkeypatch):
        _valuation(monkeypatch, data_quality="partial", missing_tickers=("MSFT",))

        result = portfolio_briefing.build_local(db, "day")

        assert result["source"] == "partial-data"
        assert result["data_quality"] == "partial"
        assert result["missing_tickers"] == ["MSFT"]
        assert isinstance(result["movers"], list) and not result["movers"]

    def test_the_unpriced_declaration_names_the_period_it_covers(self, db, monkeypatch):
        _valuation(monkeypatch, data_quality="unavailable", missing_tickers=("AAPL", "MSFT"))

        result = portfolio_briefing.build_local(db, "month")

        assert result["source"] == "data-unavailable"
        assert "over the past month" in result["lead"]

    def test_a_quote_failure_downgrades_one_mover_not_the_whole_digest(self, db, monkeypatch):
        monkeypatch.setattr(
            portfolio_briefing, "get_all_quotes", lambda _t: [{"ticker": "AAPL", "error": "x"}]
        )

        def flaky(stock_data, **_kw):
            if stock_data["ticker"] == "AAPL":
                raise RuntimeError("explainer down")
            return SimpleNamespace(drivers=[], explanation_text="fine")

        monkeypatch.setattr(portfolio_briefing, "explain_move", flaky)

        result = portfolio_briefing.build_local(db, "day")

        aapl = next(m for m in result["movers"] if m["ticker"] == "AAPL")
        assert aapl["icon"] == "bi-question-circle"
        assert aapl["explanation"] == ""
        assert len(result["movers"]) == 2


# ── Claude's answer, dressed ──────────────────────────────────────────────────

def test_build_briefing_stamps_mode_and_provenance_around_claudes_answer():
    payload = portfolio_briefing.build_briefing({"health": "Up 2%", "drivers": []})

    assert payload["mode"] == "ai"
    assert payload["source"] == "claude"
    assert payload["health"] == "Up 2%"
    assert payload["generated_at"]


# ── The briefing FolioOrb writes on its own ───────────────────────────────────

class TestBuildFallback:
    def test_it_quotes_the_snapshot_rather_than_inventing_numbers(self, db):
        snapshot = portfolio_briefing.build_snapshot(db, "day")

        result = portfolio_briefing.build_fallback(snapshot)

        assert result["mode"] == "ai"
        assert result["source"] == "local-fallback"
        assert result["health"] == (
            "Your portfolio is up 0.08% today. Total return stands at +50.00% overall."
        )
        assert result["drivers"] == [
            "AAPL was your best mover today (+2.0%).",
            "MSFT pulled back (-1.0%).",
        ]
        assert result["quote"]

    def test_a_period_fallback_speaks_in_the_periods_phrase(self, db):
        snapshot = portfolio_briefing.build_snapshot(db, "month")

        result = portfolio_briefing.build_fallback(snapshot)

        assert "over the past month" in result["health"]
        assert "was your best mover over the past month" in result["drivers"][0]

    def test_an_unpriced_book_gets_the_missing_tickers_not_a_return_narrative(
        self, db, monkeypatch
    ):
        _valuation(monkeypatch, data_quality="partial", missing_tickers=("MSFT",))
        snapshot = portfolio_briefing.build_snapshot(db, "day")

        result = portfolio_briefing.build_fallback(snapshot)

        assert result["source"] == "partial-data"
        assert result["data_quality"] == "partial"
        assert result["missing_tickers"] == ["MSFT"]
        assert result["drivers"] == ["Missing current prices for: MSFT."]

    def test_a_flat_book_still_gets_a_driver_line(self, db):
        snapshot = portfolio_briefing.build_snapshot(db, "day")
        snapshot["best_today"] = {}
        snapshot["worst_today"] = {}

        result = portfolio_briefing.build_fallback(snapshot)

        assert result["drivers"] == ["No standout movers today."]
