"""Tests for app/services/verdict_pipeline.py — the verdict scan itself.

These drive the module's own interface rather than an HTTP handler: that seam is
the point of the module, and it is the only way to assert on the deterministic
stage independently of the narrated one.  Every outward-facing fetch (quotes,
history, analyst rating, market regime, Claude) is monkeypatched, so nothing
here touches the network.
"""
# pylint: disable=protected-access

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import AISummary, Base, Holding, Portfolio, VerdictSnapshot
from app.routers import ai as ai_router
from app.services import verdict_pipeline
from app.services.analyst_recommendation import AnalystRec


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_db(tickers=("NOW",), shares=10, portfolio_id=1):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    db.add(Portfolio(id=portfolio_id, name="Test Portfolio"))
    for ticker in tickers:
        db.add(
            Holding(
                portfolio_id=portfolio_id,
                ticker=ticker,
                shares=shares,
                avg_cost=100,
                is_active=True,
            )
        )
    db.commit()
    return db


def _quote(ticker="NOW", price=100.0, low=50.0, high=120.0, day_change_pct=0.2):
    return {
        "ticker": ticker,
        "current_price": price,
        "day_change_pct": day_change_pct,
        "fifty_two_week_low": low,
        "fifty_two_week_high": high,
        "error": None,
    }


def _rec(ticker="NOW", action="hold", mean=3.0, upside=1.0):
    return AnalystRec(
        ticker=ticker,
        action=action,
        label={"buy": "Buy", "hold": "Hold", "sell": "Sell"}.get(action, "Unavailable"),
        analyst_count=15,
        recommendation_mean=mean,
        target_price=120.0,
        target_upside_pct=upside,
        fcf_yield=None,
        subtext="test",
        source="yfinance",
        security_type="STOCK",
        rating_type="analyst",
    )


def _stub_market(monkeypatch, *, quotes=None, recs=None, bundles=None):
    """Cut every outward fetch the pipeline makes; return the Claude call log."""
    quote_list = quotes if quotes is not None else [_quote()]
    monkeypatch.setattr(verdict_pipeline, "get_all_quotes", lambda _tickers: list(quote_list))
    monkeypatch.setattr(verdict_pipeline, "get_batched_history_closes", lambda _tickers: {})
    monkeypatch.setattr(verdict_pipeline, "get_cached_history_closes", lambda _ticker: [])
    monkeypatch.setattr(
        verdict_pipeline,
        "get_analyst_recommendation",
        lambda ticker, closes=None: (recs or {}).get(ticker) or _rec(ticker),
    )
    monkeypatch.setattr(
        verdict_pipeline, "get_market_regime", lambda: {"label": "Risk-on", "mood": "warm"}
    )
    monkeypatch.setattr(
        verdict_pipeline,
        "get_stock_data",
        lambda ticker: next((q for q in quote_list if q["ticker"] == ticker), _quote(ticker)),
    )

    calls = []

    def fake_bundles(inputs):
        calls.append(inputs)
        return {item["ticker"]: dict(bundles[item["ticker"]]) for item in inputs
                if item["ticker"] in (bundles or {})}

    monkeypatch.setattr(verdict_pipeline, "generate_verdict_ai_bundles", fake_bundles)
    return calls


# ── The deterministic stage ───────────────────────────────────────────────────


class TestCollectStage:
    def test_scores_every_active_holding(self, monkeypatch):
        db = _make_db(("AAA", "BBB"))
        _stub_market(monkeypatch, quotes=[_quote("AAA"), _quote("BBB")])

        scan = verdict_pipeline.scan_portfolio(db, narrate=False)

        assert scan.tickers == ["AAA", "BBB"]
        assert set(scan.signals) == {"AAA", "BBB"}
        assert scan.count == 2
        assert scan.portfolio_id == 1
        assert all(sig["action"] for sig in scan.signals.values())

    def test_un_narrated_scan_stays_silent(self, monkeypatch):
        """No quip, no brand, no Claude, no cache row, no scan history."""
        db = _make_db(("AAA",))
        calls = _stub_market(monkeypatch, quotes=[_quote("AAA")])

        scan = verdict_pipeline.scan_portfolio(db, narrate=False)

        assert not calls, "narrate=False must never reach Claude"
        assert scan.health is None
        assert scan.calibration is None
        assert scan.claude_live is None
        assert "quip" not in scan.signals["AAA"]
        assert "brand" not in scan.signals["AAA"]
        assert db.query(AISummary).count() == 0
        assert db.query(VerdictSnapshot).count() == 0

    def test_state_signature_is_ready_for_a_cache_key(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(monkeypatch, quotes=[_quote("AAA")], recs={"AAA": _rec("AAA", "buy", 1.8, 12)})

        scan = verdict_pipeline.scan_portfolio(db, narrate=False)

        assert scan.state["dominant_action"] == "add"
        assert scan.state["summary_type"].startswith("vp:")
        assert scan.state["concentration_band"] in ("low", "medium", "high")

    def test_allocation_is_portfolio_relative(self, monkeypatch):
        db = _make_db(("AAA", "BBB"))
        _stub_market(
            monkeypatch,
            quotes=[_quote("AAA", price=300.0), _quote("BBB", price=100.0)],
        )

        scan = verdict_pipeline.scan_portfolio(db, narrate=False)

        assert scan.allocation_pct == {"AAA": 75.0, "BBB": 25.0}

    def test_empty_book_falls_back_to_the_default_holdings(self, monkeypatch):
        db = _make_db(tickers=())
        _stub_market(monkeypatch, quotes=[_quote("SPY")])
        monkeypatch.setattr(verdict_pipeline, "DEFAULT_HOLDINGS", ["SPY"])

        scan = verdict_pipeline.scan_portfolio(db, narrate=False)

        assert scan.tickers == ["SPY"], "an empty book still gets something to talk about"
        assert not scan.positions
        assert not scan.allocation_pct

    def test_one_broken_ticker_does_not_sink_the_scan(self, monkeypatch):
        db = _make_db(("AAA", "BBB"))
        _stub_market(monkeypatch, quotes=[_quote("AAA"), _quote("BBB")])

        def explode(ticker, closes=None):  # pylint: disable=unused-argument
            if ticker == "BBB":
                raise RuntimeError("rating source down")
            return _rec(ticker)

        monkeypatch.setattr(verdict_pipeline, "get_analyst_recommendation", explode)

        scan = verdict_pipeline.scan_portfolio(db, narrate=False)

        assert scan.signals["AAA"]["action"] == "hold"
        assert scan.signals["BBB"]["action"] == "needs-data"
        assert scan.signals["BBB"]["_signal_error"] is True


# ── The narration stage ───────────────────────────────────────────────────────


class TestNarrateStage:
    def test_narrated_scan_is_reader_ready(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(
            monkeypatch,
            quotes=[_quote("AAA")],
            bundles={"AAA": {"quip": "Steady as she goes.", "ai": None}},
        )

        scan = verdict_pipeline.scan_portfolio(db)

        sig = scan.signals["AAA"]
        assert sig["quip"] == "Steady as she goes."
        assert sig["disclaimer"] == verdict_pipeline.VERDICT_DISCLAIMER
        assert sig["brand"]["feels_prefix"] == verdict_pipeline.VERDICT_FEELS_PREFIX
        assert scan.health["quip"]
        assert scan.health["signature"] == scan.state["summary_type"]
        assert scan.calibration is not None
        assert scan.claude_live is True

    def test_narration_records_the_scan(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(monkeypatch, quotes=[_quote("AAA")])

        verdict_pipeline.scan_portfolio(db)

        snapshots = db.query(VerdictSnapshot).all()
        assert len(snapshots) == 1
        assert snapshots[0].ticker == "AAA"

    def test_quip_is_reused_while_the_verdict_holds(self, monkeypatch):
        db = _make_db(("AAA",))
        calls = _stub_market(
            monkeypatch,
            quotes=[_quote("AAA")],
            bundles={"AAA": {"quip": "Steady as she goes.", "ai": None}},
        )

        first = verdict_pipeline.scan_portfolio(db)
        second = verdict_pipeline.scan_portfolio(db)

        assert first.signals["AAA"]["quip"] == second.signals["AAA"]["quip"]
        assert len(calls) == 1, "an unchanged verdict must reuse its cached quip"

    def test_book_quip_is_cached_under_the_portfolio_scope(self, monkeypatch):
        db = _make_db(("AAA",), portfolio_id=2)
        _stub_market(monkeypatch, quotes=[_quote("AAA")])

        verdict_pipeline.scan_portfolio(db, 2)

        scopes = {row.ticker for row in db.query(AISummary).all()}
        assert "BOOK:2" in scopes, "the book narrative must stay namespaced per portfolio"

    def test_force_local_skips_claude_and_stays_locally_branded(self, monkeypatch):
        db = _make_db(("AAA",))
        calls = _stub_market(
            monkeypatch,
            quotes=[_quote("AAA")],
            bundles={"AAA": {"quip": "Never asked for.", "ai": None}},
        )

        scan = verdict_pipeline.scan_portfolio(db, force_local=True)

        assert not calls, "force_local=True must never reach Claude"
        assert scan.claude_live is None
        assert scan.signals["AAA"]["quip"]
        assert scan.signals["AAA"]["quip"] != "Never asked for."
        assert scan.signals["AAA"]["ai_enhanced"] is False
        assert scan.signals["AAA"]["brand"]["kicker"] == (
            verdict_pipeline.VERDICT_BRAND_KICKER_LOCAL
        )
        assert scan.health["brand"]["kicker"] == verdict_pipeline.VERDICT_BRAND_KICKER_LOCAL

    def test_a_dead_claude_falls_back_without_claiming_ai(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(monkeypatch, quotes=[_quote("AAA")], bundles={})

        scan = verdict_pipeline.scan_portfolio(db)

        assert scan.claude_live is False
        assert scan.signals["AAA"]["quip"], "a fallback quip still has to be served"
        assert scan.signals["AAA"]["ai_enhanced"] is False
        assert scan.signals["AAA"]["brand"]["kicker"] == (
            verdict_pipeline.VERDICT_BRAND_KICKER_LOCAL
        )

    def test_ai_bundle_enhances_and_rebrands_the_verdict(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(
            monkeypatch,
            quotes=[_quote("AAA")],
            bundles={
                "AAA": {
                    "quip": "Claude had thoughts.",
                    "ai": {"n": 4, "cn": [0, 0, 0, 0], "h": "Tension", "tension": "Mixed reads"},
                }
            },
        )

        scan = verdict_pipeline.scan_portfolio(db)

        sig = scan.signals["AAA"]
        assert sig["ai_enhanced"] is True
        assert sig["ai_enhancement"]["headline"] == "Tension"
        assert sig["brand"]["kicker"] == verdict_pipeline.VERDICT_BRAND_KICKER

    def test_broken_ticker_is_served_as_needs_data(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(monkeypatch, quotes=[_quote("AAA")])
        monkeypatch.setattr(
            verdict_pipeline,
            "get_analyst_recommendation",
            lambda ticker, closes=None: (_ for _ in ()).throw(RuntimeError("down")),
        )

        scan = verdict_pipeline.scan_portfolio(db)

        sig = scan.signals["AAA"]
        assert sig["action"] == "needs-data"
        assert sig["quip"], "a failed verdict still needs a line to show"
        assert sig["ai_enhanced"] is False
        assert "_signal_error" not in sig, "internal flags must not reach a reader"


# ── The cache schema ──────────────────────────────────────────────────────────


class TestCacheKey:
    def test_every_dimension_changes_the_key(self):
        key = verdict_pipeline._verdict_summary_type
        base = key("hold", "neutral", "auto", "trend_intact")

        assert base != key("add", "neutral", "auto", "trend_intact")
        assert base != key("hold", "cold", "auto", "trend_intact")
        assert base != key("hold", "neutral", "anchor", "trend_intact")
        assert base != key("hold", "neutral", "auto", "death-recent")

    def test_unknown_values_fall_back_instead_of_raising(self):
        assert verdict_pipeline._verdict_summary_type("wat", "wat", "wat", "none") == (
            "v:n:neut:auto:none"
        )

    def test_action_codes_have_one_owner(self):
        """The book key and the ticker key must not drift apart."""
        from app.services import portfolio_state

        assert verdict_pipeline._ACTION_CACHE_CODE is portfolio_state._ACTION_CACHE_CODE


# ── Single-ticker read ────────────────────────────────────────────────────────


class TestScanTicker:
    def test_returns_a_reader_ready_verdict(self, monkeypatch):
        db = _make_db(("AAA",))
        calls = _stub_market(monkeypatch, quotes=[_quote("AAA")])

        sig = verdict_pipeline.scan_ticker(db, "aaa")

        assert sig["ticker"] == "AAA"
        assert sig["quip"], "the single read always carries a deterministic quip"
        assert sig["disclaimer"] == verdict_pipeline.VERDICT_DISCLAIMER
        assert sig["brand"]["kicker"] == verdict_pipeline.VERDICT_BRAND_KICKER_LOCAL
        assert not calls, "the single read never spends a Claude call"

    def test_unpriced_ticker_leaves_allocation_unknown(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(monkeypatch, quotes=[_quote("AAA")])
        monkeypatch.setattr(
            verdict_pipeline, "get_stock_data", lambda _t: {"ticker": "AAA", "error": "no quote"}
        )

        sig = verdict_pipeline.scan_ticker(db, "AAA")

        assert sig["action"]
        assert not sig.get("allocation_pct")

    def test_records_scan_history(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(monkeypatch, quotes=[_quote("AAA")])

        verdict_pipeline.scan_ticker(db, "AAA")

        assert db.query(AISummary).filter(AISummary.ticker == "AAA").count() == 1


# ── Book exposure ─────────────────────────────────────────────────────────────


class TestBookExposure:
    def test_returns_look_through_exposure(self, monkeypatch):
        db = _make_db(("AAA", "BBB"))
        _stub_market(monkeypatch, quotes=[_quote("AAA"), _quote("BBB")])

        exposure = verdict_pipeline.book_exposure(db)

        assert isinstance(exposure, dict)
        assert "sector_exposure" in exposure
        assert "concentration_hhi" in exposure

    def test_matches_the_exposure_a_scan_computes(self, monkeypatch):
        db = _make_db(("AAA", "BBB"))
        _stub_market(monkeypatch, quotes=[_quote("AAA"), _quote("BBB")])

        assert verdict_pipeline.book_exposure(db) == (
            verdict_pipeline.scan_portfolio(db, narrate=False).exposure
        )


# ── The router is now a pass-through ──────────────────────────────────────────


class TestRouterDelegates:
    def test_all_signals_endpoint_serves_the_scan_verbatim(self, monkeypatch):
        db = _make_db(("AAA",))
        _stub_market(monkeypatch, quotes=[_quote("AAA")])

        payload = ai_router.get_all_investment_signals(db)

        assert set(payload) == {
            "signals", "count", "portfolio_exposure", "portfolio_health",
            "calibration_summary", "regime", "claude_live",
        }
        assert payload["count"] == 1
        assert payload["signals"]["AAA"]["quip"]
        assert payload["portfolio_health"]["dominant_action"]
        assert payload["regime"]["mood"] == "warm"
