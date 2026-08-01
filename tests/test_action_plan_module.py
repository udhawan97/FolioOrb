"""Interface tests for the action-plan domain module.

Driven with a ``ScanResult`` and a session, never through the endpoint — the
point of moving these builders out of the router is that a caller no longer needs
an HTTP request to produce, diff or verify a plan.
"""

from types import SimpleNamespace

import pytest

from app.services import action_plan
from app.services.portfolio_state import portfolio_state_signature
from app.services.verdict_pipeline import VERDICT_DISCLAIMER, ScanResult


def _signal(action="hold", **overrides):
    base = {
        "action": action,
        "confidence": 70,
        "reasons": ["Solid fundamentals"],
        "risks": ["Overvalued vs peers"],
        "hold_class": "auto",
        "timing": None,
        "flip_triggers": None,
        "_signal_error": False,
    }
    base.update(overrides)
    return base


def _scan(signals=None, allocation=None, positions=None, exposure=None):
    if signals is None:
        signals = {
            "AAPL": _signal("hold", ticker="AAPL"),
            "MSFT": _signal("add", ticker="MSFT"),
        }
    allocation = allocation if allocation is not None else {"AAPL": 55.0, "MSFT": 45.0}
    positions = positions if positions is not None else {
        ticker: {"shares": 10.0, "avg_cost": 100.0, "is_watchlist": False,
                 "hold_class": "auto"}
        for ticker in signals
    }
    return ScanResult(
        portfolio_id=1,
        tickers=list(signals),
        signals=signals,
        allocation_pct=allocation,
        positions=positions,
        # Keys here must match build_portfolio_exposure()'s real output — see
        # tests/test_verdict_pipeline.py::TestBookExposure. A fake that invents
        # its own shape is what let the empty-exposure bug ship green.
        exposure=exposure if exposure is not None else {
            "sector_exposure": [{"name": "Technology", "weight_pct": 80.0}],
            "country_exposure": [{"name": "US", "weight_pct": 100.0}],
            "concentration_hhi": 0.50,
        },
        regime={"label": "Risk-on", "mood": "warm"},
        state=portfolio_state_signature(signals, allocation),
    )


def _valuation(monkeypatch, **overrides):
    row = {
        "holdings": [{"ticker": "AAPL", "total_return_pct": 80.0}],
        "total_value": 5000.0,
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


@pytest.fixture(name="quiet_analytics", autouse=True)
def _quiet_analytics(monkeypatch):
    """Risk metrics have their own tests; keep them deterministic and cheap here."""
    monkeypatch.setattr(
        "app.services.portfolio_analytics.compute_portfolio_beta",
        lambda holdings: {"beta": 1.1, "label": "Market pace"},
    )
    monkeypatch.setattr(
        "app.services.portfolio_analytics.compute_rolling_volatility",
        lambda holdings: {"current_vol_pct": 16.0},
    )
    monkeypatch.setattr(
        "app.services.portfolio_analytics.compute_sector_tilt",
        lambda holdings: {"sectors": [{"name": "Technology", "tilt_pct": 12.34}]},
    )
    monkeypatch.setattr(
        "app.services.portfolio_analytics.compute_conviction_gaps",
        lambda holdings, signals: {"gaps": [{"ticker": "AAPL", "gap_type": "heavy_hold"}]},
    )


# ── Cache namespace ───────────────────────────────────────────────────────────

class TestCacheType:
    def test_key_carries_the_portfolio_state_signature(self):
        scan = _scan()
        assert action_plan.cache_type(scan) == f"action_plan_v3:{scan.state['summary_type']}"

    def test_a_book_that_flips_its_action_mix_reads_a_different_key(self):
        holds = _scan()
        trims = _scan(signals={
            "AAPL": _signal("trim", ticker="AAPL"),
            "MSFT": _signal("trim", ticker="MSFT"),
        })
        assert action_plan.cache_type(holds) != action_plan.cache_type(trims)


# ── Snapshot ──────────────────────────────────────────────────────────────────

class TestBuildSnapshot:
    def test_fuses_signals_exposure_risk_and_valuation(self, monkeypatch):
        _valuation(monkeypatch)

        snapshot = action_plan.build_snapshot(None, _scan())

        assert snapshot["valuation"]["data_quality"] == "complete"
        assert snapshot["total_value"] == 5000
        assert snapshot["regime"] == {"label": "Risk-on", "mood": "warm"}
        assert snapshot["concentration_hhi"] == 0.5
        # 0.50 HHI ≈ two effective sectors — the top band on the shared scale.
        assert snapshot["hhi_band"] == "very high"
        assert [h["t"] for h in snapshot["holdings"]] == ["AAPL", "MSFT"]
        assert snapshot["holdings"][0]["ret_pct"] == 80.0
        assert snapshot["holdings"][1]["ret_pct"] == 0
        assert snapshot["exposure"]["top_sectors"] == [{"s": "Technology", "w": 80.0}]
        assert snapshot["exposure"]["top_countries"] == [{"c": "US", "w": 100.0}]
        assert snapshot["risk"] == {"beta": 1.1, "beta_label": "Market pace", "vol_pct": 16.0}
        assert snapshot["tilt"] == [{"s": "Technology", "vs_spy": 12.3}]

    def test_conviction_gap_types_are_named_in_plain_english(self, monkeypatch):
        _valuation(monkeypatch)

        snapshot = action_plan.build_snapshot(None, _scan())

        assert snapshot["conviction_gaps"] == [
            {"t": "AAPL", "type": "large position on hold"}
        ]

    def test_private_signal_fields_never_reach_claude(self, monkeypatch):
        _valuation(monkeypatch)
        scan = _scan()
        scan.signals["AAPL"]["_secret"] = "internal"

        snapshot = action_plan.build_snapshot(None, scan)

        assert all(not k.startswith("_") for entry in snapshot["holdings"] for k in entry)

    def test_a_valuation_failure_is_declared_not_guessed(self, monkeypatch):
        def explode(_db, _pid):
            raise RuntimeError("quotes down")

        monkeypatch.setattr("app.services.portfolio_valuation.evaluate", explode)

        snapshot = action_plan.build_snapshot(None, _scan())

        assert snapshot["valuation"] == {
            "data_quality": "unavailable",
            "missing_tickers": ["AAPL", "MSFT"],
            "priced_position_count": 0,
            "expected_position_count": 2,
        }
        assert snapshot["total_value"] == 0
        # No holdings rows means no risk metrics were even attempted.
        assert snapshot["risk"] == {"beta": None, "beta_label": None, "vol_pct": None}


# ── Claude's plan, dressed ────────────────────────────────────────────────────

def test_build_plan_stamps_provenance_regime_and_disclaimer():
    scan = _scan()

    plan = action_plan.build_plan(scan, {"headline": "Steady", "buckets": {}})

    assert plan["source"] == "claude"
    assert plan["headline"] == "Steady"
    assert plan["regime"] == scan.regime
    assert plan["disclaimer"] == VERDICT_DISCLAIMER
    assert plan["generated_at"]


# ── The plan FolioOrb writes on its own ───────────────────────────────────────

class TestBuildFallback:
    def test_buckets_come_straight_from_the_verdict_actions(self):
        plan = action_plan.build_fallback(_scan())

        assert plan["source"] == "local-fallback"
        assert plan["buckets"] == {
            "hold": [{"ticker": "AAPL", "reason": "Solid fundamentals"}],
            "add": [{"ticker": "MSFT", "reason": "Solid fundamentals"}],
            "trim": [],
            "exit": [],
        }
        assert plan["priority_moves"] == [
            "Consider building into MSFT — local signal rates it a buy."
        ]
        assert "AAPL is your largest position at 55%" in plan["best_return_note"]
        assert plan["disclaimer"] == VERDICT_DISCLAIMER

    def test_research_ideas_never_become_portfolio_actions(self):
        scan = _scan(signals={
            "AAPL": _signal("trim", ticker="AAPL"),
            "MSFT": _signal("needs-data", ticker="MSFT"),
            "GOOG": _signal("trim", ticker="GOOG"),
        })
        scan.positions["AAPL"]["is_watchlist"] = True
        scan.positions["MSFT"]["is_watchlist"] = True

        plan = action_plan.build_fallback(scan)

        assert not plan["buckets"]["exit"]
        assert [i["ticker"] for i in plan["buckets"]["trim"]] == ["GOOG"]
        assert "AAPL" not in str(plan["buckets"])
        assert "MSFT" not in str(plan["buckets"])

    def test_a_research_only_book_is_not_described_as_invested(self):
        scan = _scan()
        for position in scan.positions.values():
            position["is_watchlist"] = True

        plan = action_plan.build_fallback(scan)

        assert plan["buckets"] == {"hold": [], "add": [], "trim": [], "exit": []}
        assert not plan["priority_moves"]
        assert "No invested positions yet" in plan["headline"]
        assert "does not affect P&L" in plan["thesis"]

    def test_an_empty_book_still_produces_a_plan(self):
        plan = action_plan.build_fallback(_scan(signals={}, allocation={}, positions={}))

        assert plan["buckets"] == {"hold": [], "add": [], "trim": [], "exit": []}
        assert isinstance(plan["priority_moves"], list) and not plan["priority_moves"]
        assert "build an invested portfolio" in plan["best_return_note"]

    def test_snapshot_excludes_research_ideas_from_claude(self, monkeypatch):
        _valuation(monkeypatch)
        scan = _scan()
        scan.positions["AAPL"]["is_watchlist"] = True

        snapshot = action_plan.build_snapshot(None, scan)

        assert [holding["t"] for holding in snapshot["holdings"]] == ["MSFT"]

    def test_no_snapshot_and_a_complete_snapshot_read_identically(self):
        scan = _scan()
        complete = {"valuation": {"data_quality": "complete", "missing_tickers": []}}

        bare = action_plan.build_fallback(scan)
        priced = action_plan.build_fallback(scan, complete)

        assert bare["source"] == priced["source"] == "local-fallback"
        assert bare["headline"] == priced["headline"]
        assert "data_quality" not in bare and "data_quality" not in priced

    def test_a_partly_priced_book_says_so_instead_of_quoting_totals(self):
        plan = action_plan.build_fallback(
            _scan(),
            {"valuation": {"data_quality": "partial", "missing_tickers": ["MSFT"]}},
        )

        assert plan["source"] == "partial-data"
        assert plan["data_quality"] == "partial"
        assert plan["missing_tickers"] == ["MSFT"]
        assert plan["headline"] == "Live Portfolio valuation is partial"
        assert "unpriced positions" in plan["thesis"]
        # The deterministic buckets survive the override — they need no prices.
        assert plan["buckets"]["hold"][0]["ticker"] == "AAPL"

    def test_a_snapshot_with_no_valuation_block_is_treated_as_unavailable(self):
        plan = action_plan.build_fallback(_scan(), {"holdings": []})

        assert plan["source"] == "data-unavailable"
        assert plan["data_quality"] == "unavailable"
        assert plan["missing_tickers"] == []
