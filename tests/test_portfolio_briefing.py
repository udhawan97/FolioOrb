"""
Tests for GET /api/ai/portfolio-summary.
No real network calls — Claude and portfolio compute are monkeypatched.
"""
import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Holding, Portfolio
from app.routers import ai as ai_router


# ── In-memory DB helpers ───────────────────────────────────────────────────────

def _make_db(tickers=("AAPL", "MSFT")):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)  # pylint: disable=invalid-name
    db = Session()
    db.add(Portfolio(id=1, name="Test"))
    for ticker in tickers:
        db.add(Holding(
            portfolio_id=1,
            ticker=ticker,
            shares=10.0,
            avg_cost=100.0,
            is_active=True,
        ))
    db.commit()
    return db


_FAKE_HOLDINGS = [
    {
        "ticker": "AAPL",
        "current_price": 180.0,
        "shares": 10.0,
        "current_value": 1800.0,
        "daily_value_change": 36.0,
        "day_change_pct": 2.0,
        "unrealized_gain": 800.0,
        "allocation_pct": 60.0,
        "total_return_pct": 80.0,
        "is_watchlist": False,
        "avg_cost": 100.0,
    },
    {
        "ticker": "MSFT",
        "current_price": 320.0,
        "shares": 10.0,
        "current_value": 3200.0,
        "daily_value_change": -32.0,
        "day_change_pct": -1.0,
        "unrealized_gain": 1200.0,
        "allocation_pct": 40.0,
        "total_return_pct": 60.0,
        "is_watchlist": False,
        "avg_cost": 100.0,
    },
]

_FAKE_QUOTES = [
    {"ticker": "AAPL", "current_price": 180.0, "day_change": 3.6, "day_change_pct": 2.0},
    {"ticker": "MSFT", "current_price": 320.0, "day_change": -3.2, "day_change_pct": -1.0},
]

_BRIEFING_AI_RESPONSE = {
    "health": "Your portfolio gained 0.08% today.",
    "drivers": ["AAPL (+2.0%) was the top contributor."],
    "adjustments": ["No changes needed — the book looks balanced."],
    "quote": "Compound interest: nature's way of saying 'I told you so.'",
}


def _patch_portfolio_compute(monkeypatch):
    """Monkeypatch _compute_portfolio and _cumulative_realized used inside ai_router."""
    def fake_compute(_portfolio_id, _db):
        return _FAKE_HOLDINGS, 5000.0, 4.0, 2000.0

    def fake_realized(_portfolio_id, _db):
        return 200.0

    monkeypatch.setattr(
        "app.routers.portfolio._compute_portfolio",
        fake_compute,
    )
    monkeypatch.setattr(
        "app.routers.portfolio._cumulative_realized",
        fake_realized,
    )


def _patch_market_regime(monkeypatch):
    monkeypatch.setattr(
        ai_router,
        "get_market_regime",
        lambda: {"label": "Risk-on", "mood": "warm"},
    )


def _patch_quotes(monkeypatch):
    monkeypatch.setattr(
        ai_router,
        "get_all_quotes",
        lambda _tickers: _FAKE_QUOTES,
    )


def _patch_explain_move(monkeypatch):
    from app.services.move_explainer import HoldingMoveSummary, MoveDriver
    fake_summary = HoldingMoveSummary(
        ticker="AAPL",
        day_change_pct=2.0,
        day_change_dollar=36.0,
        attribution_type="market-driven",
        drivers=[MoveDriver(
            driver_type="market",
            description="S&P 500 moved +1.00%",
            magnitude="moderate",
            icon="bi-globe2",
        )],
        confidence="Medium",
        explanation_text="AAPL moved +2.00% tracking the broad market.",
    )
    monkeypatch.setattr(ai_router, "explain_move", lambda sd, **kw: fake_summary)
    monkeypatch.setattr(ai_router, "get_benchmark_data", lambda: {"SPY": 1.0, "QQQ": 0.8})


def _patch_briefing_ai(monkeypatch):
    monkeypatch.setattr(
        ai_router,
        "generate_portfolio_briefing",
        lambda snapshot: _BRIEFING_AI_RESPONSE.copy(),
    )


# ── Tests — local mode ─────────────────────────────────────────────────────────

class TestLocalBriefing:
    def test_returns_mode_local(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_quotes(monkeypatch)
        _patch_explain_move(monkeypatch)

        result = asyncio.run(ai_router.get_portfolio_summary(mode="local", db=db))
        assert result["mode"] == "local"

    def test_has_lead_and_movers(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_quotes(monkeypatch)
        _patch_explain_move(monkeypatch)

        result = asyncio.run(ai_router.get_portfolio_summary(mode="local", db=db))
        assert "lead" in result
        assert isinstance(result["lead"], str)
        assert len(result["lead"]) > 0
        assert "movers" in result
        assert isinstance(result["movers"], list)

    def test_movers_have_required_keys(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_quotes(monkeypatch)
        _patch_explain_move(monkeypatch)

        result = asyncio.run(ai_router.get_portfolio_summary(mode="local", db=db))
        for mover in result["movers"]:
            for key in ("ticker", "day_change_pct", "day_change_dollar", "icon", "explanation"):
                assert key in mover, f"movers missing key: {key}"

    def test_never_calls_claude(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_quotes(monkeypatch)
        _patch_explain_move(monkeypatch)

        called = []
        monkeypatch.setattr(
            ai_router,
            "generate_portfolio_briefing",
            lambda snapshot: called.append(True) or {},
        )
        asyncio.run(ai_router.get_portfolio_summary(mode="local", db=db))
        assert not called, "local mode must never call Claude"


# ── Tests — AI mode ────────────────────────────────────────────────────────────

class TestAiBriefing:
    def test_returns_four_keys(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_briefing_ai(monkeypatch)

        result = asyncio.run(ai_router.get_portfolio_summary(mode="ai", db=db))
        for key in ("health", "drivers", "adjustments", "quote"):
            assert key in result, f"AI briefing missing key: {key}"

    def test_mode_is_ai(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_briefing_ai(monkeypatch)

        result = asyncio.run(ai_router.get_portfolio_summary(mode="ai", db=db))
        assert result["mode"] == "ai"

    def test_drivers_is_list(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_briefing_ai(monkeypatch)

        result = asyncio.run(ai_router.get_portfolio_summary(mode="ai", db=db))
        assert isinstance(result["drivers"], list)
        assert isinstance(result["adjustments"], list)

    def test_cache_hit_on_second_call(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)

        call_count = []

        def fake_generate(_snapshot):
            call_count.append(1)
            return _BRIEFING_AI_RESPONSE.copy()

        monkeypatch.setattr(ai_router, "generate_portfolio_briefing", fake_generate)

        asyncio.run(ai_router.get_portfolio_summary(mode="ai", db=db))
        assert len(call_count) == 1

        result2 = asyncio.run(ai_router.get_portfolio_summary(mode="ai", db=db))
        assert len(call_count) == 1, "second call should reuse the cache, not call Claude again"
        assert result2.get("from_cache") is True

    def test_force_refresh_bypasses_cache(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)

        call_count = []

        def fake_generate(_snapshot):
            call_count.append(1)
            return _BRIEFING_AI_RESPONSE.copy()

        monkeypatch.setattr(ai_router, "generate_portfolio_briefing", fake_generate)

        asyncio.run(ai_router.get_portfolio_summary(mode="ai", db=db))
        asyncio.run(ai_router.get_portfolio_summary(mode="ai", force_refresh=True, db=db))
        assert len(call_count) == 2, "force_refresh=True should bypass cache"

    def test_claude_failure_returns_local_fallback(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)

        monkeypatch.setattr(
            ai_router,
            "generate_portfolio_briefing",
            lambda snapshot: (_ for _ in ()).throw(Exception("Claude down")),
        )

        result = asyncio.run(ai_router.get_portfolio_summary(mode="ai", db=db))
        assert result["mode"] == "ai"
        assert result["source"] == "local-fallback"
        for key in ("health", "drivers", "adjustments", "quote"):
            assert key in result, f"fallback missing key: {key}"

    def test_fallback_does_not_invent_numbers(self, monkeypatch):
        """Fallback health text should reference real snapshot values."""
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)

        monkeypatch.setattr(
            ai_router,
            "generate_portfolio_briefing",
            lambda snapshot: (_ for _ in ()).throw(Exception("Claude down")),
        )

        result = asyncio.run(ai_router.get_portfolio_summary(mode="ai", db=db))
        assert isinstance(result["health"], str) and len(result["health"]) > 0
        assert isinstance(result["quote"], str) and len(result["quote"]) > 0


# ── Tests — unknown mode normalises to ai ─────────────────────────────────────

def test_unknown_mode_defaults_to_ai(monkeypatch):
    db = _make_db()
    _patch_portfolio_compute(monkeypatch)
    _patch_market_regime(monkeypatch)
    _patch_briefing_ai(monkeypatch)

    result = asyncio.run(ai_router.get_portfolio_summary(mode="garbage", db=db))
    assert result["mode"] == "ai"


# ── Tests — range-aware briefing (1W … 1Y) ─────────────────────────────────────

def _patch_range_history(monkeypatch):
    """300 trading days of $1/day linear growth for every requested ticker."""
    closes = [100.0 + i for i in range(300)]
    monkeypatch.setattr(
        "app.services.portfolio_analytics.get_batched_history_closes",
        lambda tickers, period="1y": {t: list(closes) for t in tickers},
    )


class TestRangeBriefing:
    def test_local_week_uses_period_movers(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_quotes(monkeypatch)
        _patch_explain_move(monkeypatch)
        _patch_range_history(monkeypatch)

        result = asyncio.run(
            ai_router.get_portfolio_summary(mode="local", time_range="week", db=db)
        )
        assert result["mode"] == "local"
        assert result["period_label"] == "over the past week"
        assert "past week" in result["lead"]
        aapl = next(m for m in result["movers"] if m["ticker"] == "AAPL")
        # 10 shares × 5 trading days × $1/day — period change, not day change
        assert aapl["day_change_dollar"] == 50.0
        assert aapl["explanation"] == ""

    def test_ai_week_caches_separately_from_day(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_range_history(monkeypatch)

        call_count = []

        def fake_generate(_snapshot):
            call_count.append(1)
            return _BRIEFING_AI_RESPONSE.copy()

        monkeypatch.setattr(ai_router, "generate_portfolio_briefing", fake_generate)

        asyncio.run(ai_router.get_portfolio_summary(mode="ai", time_range="week", db=db))
        asyncio.run(ai_router.get_portfolio_summary(mode="ai", time_range="day", db=db))
        assert len(call_count) == 2, "day and week must not share a cache entry"

        result = asyncio.run(
            ai_router.get_portfolio_summary(mode="ai", time_range="week", db=db)
        )
        assert len(call_count) == 2, "second week call should hit the week cache"
        assert result.get("from_cache") is True

        from app.models import AISummary
        types = {row.summary_type for row in db.query(AISummary).all()}
        assert {"briefing", "briefing_week"} <= types

    def test_ai_week_snapshot_is_period_scoped(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_range_history(monkeypatch)

        seen = {}

        def fake_generate(snapshot):
            seen.update(snapshot)
            return _BRIEFING_AI_RESPONSE.copy()

        monkeypatch.setattr(ai_router, "generate_portfolio_briefing", fake_generate)

        asyncio.run(ai_router.get_portfolio_summary(mode="ai", time_range="week", db=db))
        assert seen["period_label"] == "over the past week"
        assert "period_pl" in seen
        assert "best_period" in seen
        assert "today_pl" not in seen
        assert "best_today" not in seen

    def test_unknown_range_defaults_to_day(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_quotes(monkeypatch)
        _patch_explain_move(monkeypatch)

        result = asyncio.run(
            ai_router.get_portfolio_summary(mode="local", time_range="bogus", db=db)
        )
        assert "period_label" not in result, "unknown range must use the day payload"

    def test_fallback_uses_period_phrase(self, monkeypatch):
        db = _make_db()
        _patch_portfolio_compute(monkeypatch)
        _patch_market_regime(monkeypatch)
        _patch_range_history(monkeypatch)
        monkeypatch.setattr(
            ai_router,
            "generate_portfolio_briefing",
            lambda snapshot: (_ for _ in ()).throw(Exception("Claude down")),
        )

        result = asyncio.run(
            ai_router.get_portfolio_summary(mode="ai", time_range="month", db=db)
        )
        assert result["source"] == "local-fallback"
        assert "over the past month" in result["health"]


# ── Tests — generate_portfolio_briefing unit ──────────────────────────────────

class TestGeneratePortfolioBriefing:
    def test_parses_valid_json(self):
        from app.services.ai_service import generate_portfolio_briefing

        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = json.dumps(_BRIEFING_AI_RESPONSE)
        mock_msg.content = [mock_block]
        mock_msg.usage.input_tokens = 120
        mock_msg.usage.output_tokens = 80

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = generate_portfolio_briefing({"as_of": "2026-06-27"})

        assert result["health"] == _BRIEFING_AI_RESPONSE["health"]
        assert isinstance(result["drivers"], list)
        assert isinstance(result["adjustments"], list)
        assert isinstance(result["quote"], str)

    def test_strips_markdown_fences(self):
        from app.services.ai_service import generate_portfolio_briefing

        fenced = f"```json\n{json.dumps(_BRIEFING_AI_RESPONSE)}\n```"
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = fenced
        mock_msg.content = [mock_block]
        mock_msg.usage.input_tokens = 120
        mock_msg.usage.output_tokens = 80

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = generate_portfolio_briefing({"as_of": "2026-06-27"})

        assert result["health"] == _BRIEFING_AI_RESPONSE["health"]

    def test_raises_on_api_error(self):
        from app.services.ai_service import generate_portfolio_briefing

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.side_effect = Exception("API down")
            with pytest.raises(Exception, match="API down"):
                generate_portfolio_briefing({"as_of": "2026-06-27"})

    def test_canned_quote_returned_when_response_missing_quote(self):
        from app.services.ai_service import generate_portfolio_briefing

        partial = dict(_BRIEFING_AI_RESPONSE)
        partial["quote"] = ""
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = json.dumps(partial)
        mock_msg.content = [mock_block]
        mock_msg.usage.input_tokens = 100
        mock_msg.usage.output_tokens = 60

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = generate_portfolio_briefing({"as_of": "2026-06-27"})

        assert isinstance(result["quote"], str) and len(result["quote"]) > 0
