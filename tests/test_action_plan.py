"""
Tests for GET /api/ai/action-plan.
No real network / API calls — Claude and signal pipeline are monkeypatched.
Mirrors the pattern established in tests/test_portfolio_briefing.py.
"""
import asyncio
import json
from types import SimpleNamespace
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
            is_watchlist=False,
        ))
    db.commit()
    return db


_ACTIVE_TICKERS = ["AAPL", "MSFT"]

_FAKE_SIGNAL = {
    "action": "hold",
    "label": "Hold",
    "confidence": 70,
    "market_mood": "warm",
    "reasons": ["Solid fundamentals"],
    "risks": ["Overvalued vs peers"],
    "data_quality": "high",
    "source_fields": [],
    "generated_at": "2026-06-27T00:00:00+00:00",
    "flip_triggers": None,
    "signal_mix": [],
    "freshness": None,
    "hold_class": "auto",
    "instrument_role": "core",
    "timing": None,
    "confidence_detail": None,
}

_CORE_RESULT = {
    "active_tickers": _ACTIVE_TICKERS,
    "signals": {
        "AAPL": {**_FAKE_SIGNAL, "ticker": "AAPL", "action": "hold"},
        "MSFT": {**_FAKE_SIGNAL, "ticker": "MSFT", "action": "add"},
    },
    "alloc_map": {"AAPL": 55.0, "MSFT": 45.0},
    "holding_meta": {
        "AAPL": {"shares": 10.0, "avg_cost": 100.0, "is_watchlist": False, "hold_class": "auto"},
        "MSFT": {"shares": 10.0, "avg_cost": 100.0, "is_watchlist": False, "hold_class": "auto"},
    },
    "portfolio_exposure": {
        "sectors": [{"sector": "Technology", "weight_pct": 80.0}],
        "countries": [{"country": "US", "weight_pct": 100.0}],
        "concentration_hhi": 0.50,
    },
    "regime": {"label": "Risk-on", "mood": "warm"},
    "quotes": {
        "AAPL": {"ticker": "AAPL", "current_price": 180.0},
        "MSFT": {"ticker": "MSFT", "current_price": 320.0},
    },
    "history_map": {},
}

_AI_ACTION_PLAN_RESPONSE = {
    "headline": "Book holds steady with MSFT as the growth lever.",
    "thesis": "Concentration at 0.50 HHI with regime warm; AAPL anchors, MSFT add signal unopened.",
    "buckets": {
        "hold": [{"ticker": "AAPL", "reason": "Solid anchor; fundamentals intact."}],
        "add":  [{"ticker": "MSFT", "reason": "Add signal with strong momentum."}],
        "trim": [],
        "exit": [],
    },
    "priority_moves": ["Add to MSFT to close the conviction gap."],
    "best_return_note": "Sizing into MSFT closes the gap to the optimal mix.",
}


def _patch_core(monkeypatch):
    monkeypatch.setattr(
        ai_router,
        "_collect_portfolio_signals_core",
        lambda db, portfolio_id=1: dict(_CORE_RESULT),
    )


def _patch_compute_portfolio(monkeypatch):
    monkeypatch.setattr(
        "app.services.portfolio_valuation.evaluate",
        lambda db, pid: SimpleNamespace(holdings=[], total_value=5000.0),
    )


def _patch_analytics(monkeypatch):
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
        lambda holdings: {"tilt": []},
    )
    monkeypatch.setattr(
        "app.services.portfolio_analytics.compute_conviction_gaps",
        lambda holdings, signals: {"gaps": []},
    )


def _patch_action_plan_ai(monkeypatch):
    monkeypatch.setattr(
        ai_router,
        "generate_action_plan",
        lambda snapshot: dict(_AI_ACTION_PLAN_RESPONSE),
    )


# ── Tests — shape of the AI response ──────────────────────────────────────────


class TestActionPlanShape:
    def test_returns_required_top_level_keys(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)
        _patch_action_plan_ai(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(db=db))
        for key in ("headline", "thesis", "buckets", "priority_moves", "best_return_note"):
            assert key in result, f"action plan missing key: {key}"

    def test_buckets_has_four_keys(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)
        _patch_action_plan_ai(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(db=db))
        buckets = result["buckets"]
        for key in ("hold", "add", "trim", "exit"):
            assert key in buckets, f"buckets missing key: {key}"

    def test_bucket_items_have_ticker_and_reason(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)
        _patch_action_plan_ai(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(db=db))
        for bucket_name, items in result["buckets"].items():
            for item in items:
                assert "ticker" in item, f"{bucket_name} item missing 'ticker'"
                assert "reason" in item, f"{bucket_name} item missing 'reason'"

    def test_priority_moves_is_list(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)
        _patch_action_plan_ai(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(db=db))
        assert isinstance(result["priority_moves"], list)
        assert len(result["priority_moves"]) <= 3

    def test_includes_disclaimer(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)
        _patch_action_plan_ai(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(db=db))
        assert "disclaimer" in result
        assert "not" in result["disclaimer"].lower() or "financial" in result["disclaimer"].lower()


# ── Tests — buckets contain only active tickers ───────────────────────────────


class TestActionPlanTickers:
    def test_ai_buckets_contain_only_active_tickers(self, monkeypatch):
        """Tickers returned by Claude must all belong to the active portfolio."""
        db = _make_db(tickers=("AAPL", "MSFT"))
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)
        _patch_action_plan_ai(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(db=db))
        buckets = result["buckets"]
        all_tickers_in_response = [
            item["ticker"]
            for items in buckets.values()
            for item in items
        ]
        active = set(_ACTIVE_TICKERS)
        for ticker in all_tickers_in_response:
            assert ticker in active, (
                f"Bucket ticker '{ticker}' not in active portfolio {active}"
            )

    def test_fallback_buckets_contain_only_active_tickers(self, monkeypatch):
        """Deterministic fallback must also only reference active tickers."""
        db = _make_db(tickers=("AAPL", "MSFT"))
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        monkeypatch.setattr(
            ai_router,
            "generate_action_plan",
            lambda snapshot: (_ for _ in ()).throw(Exception("Claude down")),
        )

        result = asyncio.run(ai_router.get_action_plan(db=db))
        buckets = result.get("buckets") or {}
        all_tickers_in_response = [
            item["ticker"]
            for items in buckets.values()
            for item in items
        ]
        active = set(_ACTIVE_TICKERS)
        for ticker in all_tickers_in_response:
            assert ticker in active, (
                f"Fallback ticker '{ticker}' not in active portfolio {active}"
            )


# ── Tests — deterministic fallback on model failure ───────────────────────────


class TestActionPlanFallback:
    def test_returns_fallback_on_claude_failure(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        monkeypatch.setattr(
            ai_router,
            "generate_action_plan",
            lambda snapshot: (_ for _ in ()).throw(Exception("Claude down")),
        )

        result = asyncio.run(ai_router.get_action_plan(db=db))
        # Must return a valid plan, not raise
        assert result is not None
        assert "buckets" in result

    def test_fallback_source_is_local_fallback(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        monkeypatch.setattr(
            ai_router,
            "generate_action_plan",
            lambda snapshot: (_ for _ in ()).throw(RuntimeError("Timeout")),
        )

        result = asyncio.run(ai_router.get_action_plan(db=db))
        assert result.get("source") == "local-fallback"

    def test_fallback_has_all_four_bucket_keys(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        monkeypatch.setattr(
            ai_router,
            "generate_action_plan",
            lambda snapshot: (_ for _ in ()).throw(Exception("Claude down")),
        )

        result = asyncio.run(ai_router.get_action_plan(db=db))
        for key in ("hold", "add", "trim", "exit"):
            assert key in result["buckets"], f"fallback buckets missing key: {key}"

    def test_fallback_never_raises(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        monkeypatch.setattr(
            ai_router,
            "generate_action_plan",
            lambda snapshot: (_ for _ in ()).throw(Exception("Claude down")),
        )

        # Should not raise even if snapshot building also partially fails
        try:
            result = asyncio.run(ai_router.get_action_plan(db=db))
            assert isinstance(result, dict)
        except Exception as exc:  # pylint: disable=broad-except
            pytest.fail(f"get_action_plan raised unexpectedly: {exc}")


# ── Tests — force_local (local intelligence mode) ─────────────────────────────


class TestActionPlanForceLocal:
    """Verify force_local=True skips Claude and returns a deterministic local plan."""

    def test_force_local_returns_local_source(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        # Claude must NOT be called at all
        claude_calls = []
        monkeypatch.setattr(
            ai_router,
            "generate_action_plan",
            lambda snapshot: (claude_calls.append(snapshot), _AI_ACTION_PLAN_RESPONSE)[1],
        )

        result = asyncio.run(ai_router.get_action_plan(force_local=True, db=db))
        assert result.get("source") == "local-fallback", (
            "force_local=True must return a local-fallback plan"
        )
        assert not claude_calls, "Claude was called despite force_local=True"

    def test_force_local_has_required_keys(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(force_local=True, db=db))
        for key in ("headline", "thesis", "buckets", "priority_moves", "best_return_note",
                    "regime", "disclaimer"):
            assert key in result, f"force_local plan missing key: {key}"

    def test_force_local_has_four_buckets(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(force_local=True, db=db))
        for key in ("hold", "add", "trim", "exit"):
            assert key in result["buckets"], f"force_local buckets missing key: {key}"

    def test_force_local_only_active_tickers(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(force_local=True, db=db))
        active = set(_ACTIVE_TICKERS)
        for bucket_name, items in result["buckets"].items():
            for item in items:
                ticker = item.get("ticker", "")
                assert ticker in active, (
                    f"force_local bucket '{bucket_name}' has ticker '{ticker}' "
                    f"not in active portfolio {active}"
                )

    def test_force_local_regime_included(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        result = asyncio.run(ai_router.get_action_plan(force_local=True, db=db))
        assert isinstance(result.get("regime"), dict), "regime must be a dict in local plan"


# ── Tests — caching ────────────────────────────────────────────────────────────


class TestActionPlanCache:
    def test_cache_hit_skips_claude_on_second_call(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        call_count = []

        def fake_generate(_snapshot):
            call_count.append(1)
            return dict(_AI_ACTION_PLAN_RESPONSE)

        monkeypatch.setattr(ai_router, "generate_action_plan", fake_generate)

        asyncio.run(ai_router.get_action_plan(db=db))
        assert len(call_count) == 1

        result2 = asyncio.run(ai_router.get_action_plan(db=db))
        assert len(call_count) == 1, "second call must reuse cache, not call Claude again"
        assert result2.get("from_cache") is True

    def test_force_refresh_bypasses_cache(self, monkeypatch):
        db = _make_db()
        _patch_core(monkeypatch)
        _patch_compute_portfolio(monkeypatch)

        call_count = []

        def fake_generate(_snapshot):
            call_count.append(1)
            return dict(_AI_ACTION_PLAN_RESPONSE)

        monkeypatch.setattr(ai_router, "generate_action_plan", fake_generate)

        asyncio.run(ai_router.get_action_plan(db=db))
        asyncio.run(ai_router.get_action_plan(force_refresh=True, db=db))
        assert len(call_count) == 2, "force_refresh=True must bypass cache"


# ── Tests — generate_action_plan unit ─────────────────────────────────────────


class TestGenerateActionPlan:
    def test_parses_valid_json(self):
        from app.services.ai_service import generate_action_plan

        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = json.dumps(_AI_ACTION_PLAN_RESPONSE)
        mock_msg.content = [mock_block]
        mock_msg.usage.input_tokens = 200
        mock_msg.usage.output_tokens = 300

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = generate_action_plan({"as_of": "2026-06-27"})

        assert result["headline"] == _AI_ACTION_PLAN_RESPONSE["headline"]
        assert isinstance(result["buckets"], dict)
        assert "hold" in result["buckets"]
        assert "add" in result["buckets"]
        assert isinstance(result["priority_moves"], list)

    def test_strips_markdown_fences(self):
        from app.services.ai_service import generate_action_plan

        fenced = f"```json\n{json.dumps(_AI_ACTION_PLAN_RESPONSE)}\n```"
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = fenced
        mock_msg.content = [mock_block]
        mock_msg.usage.input_tokens = 200
        mock_msg.usage.output_tokens = 300

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = generate_action_plan({"as_of": "2026-06-27"})

        assert result["headline"] == _AI_ACTION_PLAN_RESPONSE["headline"]

    def test_raises_on_api_error(self):
        from app.services.ai_service import generate_action_plan

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.side_effect = Exception("API down")
            with pytest.raises(Exception, match="API down"):
                generate_action_plan({"as_of": "2026-06-27"})

    def test_raises_on_missing_headline(self):
        from app.services.ai_service import generate_action_plan

        incomplete = {**_AI_ACTION_PLAN_RESPONSE, "headline": ""}
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = json.dumps(incomplete)
        mock_msg.content = [mock_block]
        mock_msg.usage.input_tokens = 100
        mock_msg.usage.output_tokens = 100

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            with pytest.raises(ValueError, match="missing 'headline'"):
                generate_action_plan({"as_of": "2026-06-27"})

    def test_bucket_tickers_are_uppercased(self):
        from app.services.ai_service import generate_action_plan

        lowered = {
            **_AI_ACTION_PLAN_RESPONSE,
            "buckets": {
                "hold": [{"ticker": "aapl", "reason": "test"}],
                "add":  [],
                "trim": [],
                "exit": [],
            },
        }
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = json.dumps(lowered)
        mock_msg.content = [mock_block]
        mock_msg.usage.input_tokens = 100
        mock_msg.usage.output_tokens = 100

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            result = generate_action_plan({"as_of": "2026-06-27"})

        assert result["buckets"]["hold"][0]["ticker"] == "AAPL"

    def test_uses_action_plan_model(self):
        """Endpoint must call Claude with ACTION_PLAN_MODEL, not the Haiku default."""
        from app.services.ai_service import generate_action_plan, ACTION_PLAN_MODEL

        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = json.dumps(_AI_ACTION_PLAN_RESPONSE)
        mock_msg.content = [mock_block]
        mock_msg.usage.input_tokens = 200
        mock_msg.usage.output_tokens = 300

        with patch("app.services.ai_service.client") as mock_client:
            mock_client.messages.create.return_value = mock_msg
            generate_action_plan({"as_of": "2026-06-27"})
            call_kwargs = mock_client.messages.create.call_args
            assert call_kwargs.kwargs.get("model") == ACTION_PLAN_MODEL
