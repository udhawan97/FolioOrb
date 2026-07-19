"""
Tests for AI cache accounting.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.models import AISummary, Base
from app.routers.ai import get_ai_cache_stats
from app.services import ai_service
from app.services.ai_service import claude_api_heartbeat


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_ai_cache_stats_excludes_local_fallback_rows_from_token_cost(monkeypatch):
    db = _make_db()
    db.add_all([
        AISummary(
            ticker="NOW",
            summary_type="verdict",
            summary_text="Local fallback note.",
            model_used="fallback",
        ),
        AISummary(
            ticker="VOO",
            summary_type="scan",
            summary_text="Deterministic scan note.",
            model_used="deterministic",
        ),
        AISummary(
            ticker="AAPL",
            summary_type="stock",
            summary_text="Claude-backed cached summary.",
            model_used="claude-haiku-4-5-20251001",
        ),
    ])
    db.commit()
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")

    stats = get_ai_cache_stats(db)

    assert stats["cached_summaries"] == 3
    assert stats["claude_cached_summaries"] == 1
    assert stats["local_cached_summaries"] == 2
    assert stats["estimated_input_tokens"] > 0
    assert stats["estimated_output_tokens"] > 0
    assert stats["estimated_total_tokens"] == (
        stats["estimated_input_tokens"] + stats["estimated_output_tokens"]
    )


def test_ai_cache_stats_marks_billing_paused_without_api_key(monkeypatch):
    db = _make_db()
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

    stats = get_ai_cache_stats(db)

    assert stats["claude_configured"] is False
    assert stats["billing_active"] is False
    assert "paused" in stats["note"]


def test_claude_heartbeat_reports_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

    result = claude_api_heartbeat()

    assert result["live"] is False
    assert result["status"] == "missing_key"


def test_claude_heartbeat_reports_live_api(monkeypatch):
    class _Messages:
        @staticmethod
        def count_tokens(**_kwargs):
            raise AssertionError("heartbeat must not call token-counting APIs")

    class _Models:
        @staticmethod
        def list(**_kwargs):
            return []

    class _Client:
        messages = _Messages()
        models = _Models()

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "client", _Client())

    result = claude_api_heartbeat()

    assert result["live"] is True
    assert result["status"] == "ok"
    assert "input_tokens" not in result
