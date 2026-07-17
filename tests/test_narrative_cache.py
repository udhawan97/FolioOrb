"""Interface tests for Portfolio narrative caching."""

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import AISummary, Base
from app.services.narrative_cache import NarrativeCache, portfolio_scope


def make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_portfolio_json_cache_is_isolated_validated_and_corruption_safe():
    db = make_db()
    cache = NarrativeCache(db, ttl=timedelta(hours=24))

    assert cache.store_json(portfolio_scope(1), "briefing", {"health": "one"}, "test")
    assert cache.store_json(portfolio_scope(2), "briefing", {"health": "two"}, "test")
    assert cache.get_json(portfolio_scope(1), "briefing") == {"health": "one"}
    assert cache.get_json(portfolio_scope(2), "briefing") == {"health": "two"}
    assert cache.get_json(
        portfolio_scope(1),
        "briefing",
        validator=lambda payload: payload.get("health") == "two",
    ) is None

    row = db.query(AISummary).filter_by(ticker="BOOK:1", summary_type="briefing").one()
    row.summary_text = "{not-json"
    row.generated_at = datetime.now().replace(microsecond=0) - timedelta(hours=25)
    db.commit()
    assert cache.get_json(portfolio_scope(1), "briefing") is None
