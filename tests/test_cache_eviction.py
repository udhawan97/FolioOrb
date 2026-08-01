# pylint: disable=protected-access
"""The two hand-rolled caches must drop entries they can never read again.

``ttl_cache`` prunes on every write, for a reason its own source states: without
it "a long-running desktop process accumulates one dead entry per key per TTL
window". These two caches predate that decorator and never adopted it — the news
themes cache keys on a headline signature computed inside the endpoint, and the
analytics cache is read and written at twenty separate call sites — so neither
fits the decorator's shape without restructuring. They still have to evict.

Both are keyed by content, not by ticker: the analytics cache hashes the sorted
ticker set, and the themes cache hashes the headline set. So the key space is not
bounded by how many holdings a user has. Every edit to a portfolio, and every
time a news feed changes, mints a key that is never looked up again.
"""
import time

from app.routers import news
from app.services import portfolio_analytics


def test_analytics_cache_drops_expired_entries_on_write(monkeypatch):
    portfolio_analytics._cache.clear()
    clock = {"now": 1000.0}
    monkeypatch.setattr(time, "time", lambda: clock["now"])

    for i in range(50):
        portfolio_analytics._cache_set(f"key-{i}", {"payload": i})
        clock["now"] += portfolio_analytics._CACHE_TTL_SEC + 1

    # Every entry but the newest has aged out and must be gone, not merely unread.
    assert len(portfolio_analytics._cache) == 1


def test_analytics_cache_keeps_live_entries(monkeypatch):
    portfolio_analytics._cache.clear()
    clock = {"now": 1000.0}
    monkeypatch.setattr(time, "time", lambda: clock["now"])

    for i in range(10):
        portfolio_analytics._cache_set(f"key-{i}", {"payload": i})

    assert len(portfolio_analytics._cache) == 10
    assert portfolio_analytics._cache_get("key-0") == {"payload": 0}


def test_analytics_cache_still_expires_reads(monkeypatch):
    """Pruning must not change what a caller sees — a stale read is still a miss."""
    portfolio_analytics._cache.clear()
    clock = {"now": 1000.0}
    monkeypatch.setattr(time, "time", lambda: clock["now"])

    portfolio_analytics._cache_set("k", {"payload": 1})
    assert portfolio_analytics._cache_get("k") == {"payload": 1}
    clock["now"] += portfolio_analytics._CACHE_TTL_SEC + 1
    assert portfolio_analytics._cache_get("k") is None


def test_themes_cache_drops_expired_entries_on_write(monkeypatch):
    news._THEMES_CACHE.clear()
    clock = {"now": 1000.0}
    monkeypatch.setattr(news.time, "monotonic", lambda: clock["now"])

    for i in range(50):
        news._remember_themes(f"sig-{i}", {"briefing": i})
        clock["now"] += news._THEMES_TTL + 1

    assert len(news._THEMES_CACHE) == 1


def test_themes_cache_keeps_live_entries(monkeypatch):
    news._THEMES_CACHE.clear()
    clock = {"now": 1000.0}
    monkeypatch.setattr(news.time, "monotonic", lambda: clock["now"])

    for i in range(10):
        news._remember_themes(f"sig-{i}", {"briefing": i})

    assert len(news._THEMES_CACHE) == 10
