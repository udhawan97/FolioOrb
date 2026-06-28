"""
Tests for app/services/news_service.py — normalization, dedup, and
feed-route integration.  No real network calls: yfinance is monkeypatched.
"""
# pylint: disable=protected-access
import asyncio
import time
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Holding, Portfolio
from app.routers import news as news_router
from app.services import news_service
from app.services.news_service import (
    _normalize_item,
    _thumbnail_url,
    _article_url,
    build_themes_snapshot,
    fetch_portfolio_news,
    fetch_ticker_news,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_raw_item(
    title="AAPL Surges on Earnings",
    article_id="art-001",
    pub_date="2026-06-27T14:00:00Z",
    *,
    summary="Apple reported strong quarterly results.",
    source_name="Reuters",
    url="https://example.com/aapl-surge",
    thumbnail_url="https://cdn.example.com/thumb.jpg",
):
    """Build a minimal yfinance-shaped news item dict."""
    return {
        "content": {
            "id": article_id,
            "title": title,
            "summary": summary,
            "pubDate": pub_date,
            "provider": {"displayName": source_name},
            "canonicalUrl": {"url": url},
            "thumbnail": {
                "resolutions": [{"url": thumbnail_url, "width": 640, "height": 360}]
            },
        }
    }


def _make_db(tickers=("AAPL", "MSFT")):
    """Return an in-memory SQLite session with a minimal portfolio."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)  # pylint: disable=invalid-name
    db = Session()
    db.add(Portfolio(id=1, name="Test"))
    for i, ticker in enumerate(tickers):
        db.add(Holding(
            portfolio_id=1,
            ticker=ticker,
            shares=10.0,
            avg_cost=100.0,
            is_active=True,
            is_watchlist=(i == len(tickers) - 1),  # last ticker is watchlist
        ))
    db.commit()
    return db


# ── _normalize_item ────────────────────────────────────────────────────────────

class TestNormalizeItem:
    def test_extracts_title(self):
        item = _normalize_item(_make_raw_item(), "AAPL")
        assert item["title"] == "AAPL Surges on Earnings"

    def test_extracts_source(self):
        item = _normalize_item(_make_raw_item(), "AAPL")
        assert item["source"] == "Reuters"

    def test_extracts_published_at(self):
        item = _normalize_item(_make_raw_item(), "AAPL")
        assert item["published_at"] == "2026-06-27T14:00:00Z"

    def test_extracts_url(self):
        item = _normalize_item(_make_raw_item(), "AAPL")
        assert item["url"] == "https://example.com/aapl-surge"

    def test_extracts_thumbnail(self):
        item = _normalize_item(_make_raw_item(), "AAPL")
        assert item["thumbnail_url"] == "https://cdn.example.com/thumb.jpg"

    def test_returns_none_for_missing_title(self):
        raw = _make_raw_item(title="")
        assert _normalize_item(raw, "AAPL") is None

    def test_sets_ticker(self):
        item = _normalize_item(_make_raw_item(), "MSFT")
        assert item["ticker"] == "MSFT"

    def test_dedup_key_falls_back_to_url(self):
        raw = _make_raw_item(article_id="")
        item = _normalize_item(raw, "AAPL")
        assert item["dedup_key"] == "https://example.com/aapl-surge"

    def test_dedup_key_falls_back_to_title(self):
        raw = _make_raw_item(article_id="", url="")
        # patch canonicalUrl to return empty
        raw["content"]["canonicalUrl"] = {"url": ""}
        raw["content"]["clickThroughUrl"] = {"url": ""}
        item = _normalize_item(raw, "AAPL")
        assert item["dedup_key"] == "AAPL Surges on Earnings"

    def test_fallback_source_name(self):
        raw = _make_raw_item()
        raw["content"]["provider"] = {}
        item = _normalize_item(raw, "AAPL")
        assert item["source"] == "Yahoo Finance"

    def test_handles_flat_item_shape(self):
        """Some yfinance versions don't nest under 'content'."""
        raw = {
            "id": "flat-001",
            "title": "Flat Title",
            "pubDate": "2026-06-27T10:00:00Z",
            "provider": {"displayName": "Bloomberg"},
            "canonicalUrl": {"url": "https://example.com/flat"},
        }
        item = _normalize_item(raw, "AAPL")
        assert item is not None
        assert item["title"] == "Flat Title"


# ── _thumbnail_url ─────────────────────────────────────────────────────────────

class TestThumbnailUrl:
    def test_picks_highest_width(self):
        content = {
            "thumbnail": {
                "resolutions": [
                    {"url": "https://small.jpg", "width": 320},
                    {"url": "https://large.jpg", "width": 960},
                ]
            }
        }
        assert _thumbnail_url(content) == "https://large.jpg"

    def test_returns_none_when_absent(self):
        assert _thumbnail_url({}) is None

    def test_returns_none_for_empty_resolutions(self):
        content = {"thumbnail": {"resolutions": []}}
        assert _thumbnail_url(content) is None

    def test_falls_back_to_plain_url(self):
        content = {"thumbnail": {"url": "https://plain.jpg"}}
        assert _thumbnail_url(content) == "https://plain.jpg"


# ── _article_url ───────────────────────────────────────────────────────────────

class TestArticleUrl:
    def test_prefers_canonical_url(self):
        content = {
            "canonicalUrl": {"url": "https://canonical.com"},
            "clickThroughUrl": {"url": "https://click.com"},
        }
        assert _article_url(content) == "https://canonical.com"

    def test_falls_back_to_clickthrough(self):
        content = {
            "canonicalUrl": {"url": ""},
            "clickThroughUrl": {"url": "https://click.com"},
        }
        assert _article_url(content) == "https://click.com"

    def test_returns_empty_when_both_missing(self):
        assert _article_url({}) == ""


# ── fetch_ticker_news ──────────────────────────────────────────────────────────

class TestFetchTickerNews:
    def test_rejects_unsafe_ticker(self):
        result = fetch_ticker_news("../../etc/passwd")
        assert result == []

    def test_returns_empty_list_on_yfinance_failure(self, monkeypatch):
        # Clear the cache so this test hits the real fetch path.
        news_service._NEWS_CACHE.clear()

        def boom(_ticker):
            raise RuntimeError("yfinance down")

        monkeypatch.setattr("app.services.news_service.yf.Ticker", boom)
        result = fetch_ticker_news("AAPL")
        assert result == []

    def test_normalizes_and_sorts_newest_first(self, monkeypatch):
        news_service._NEWS_CACHE.clear()

        older = _make_raw_item(
            title="Old news", article_id="old", pub_date="2026-06-25T08:00:00Z"
        )
        newer = _make_raw_item(
            title="New news", article_id="new", pub_date="2026-06-27T14:00:00Z"
        )

        mock_ticker = MagicMock()
        mock_ticker.news = [older, newer]
        monkeypatch.setattr(
            "app.services.news_service.yf.Ticker", lambda _: mock_ticker
        )

        result = fetch_ticker_news("AAPL")
        assert len(result) == 2
        assert result[0]["title"] == "New news"
        assert result[1]["title"] == "Old news"

    def test_cache_is_populated(self, monkeypatch):
        news_service._NEWS_CACHE.clear()

        mock_ticker = MagicMock()
        mock_ticker.news = [_make_raw_item()]
        monkeypatch.setattr(
            "app.services.news_service.yf.Ticker", lambda _: mock_ticker
        )

        fetch_ticker_news("MSFT")
        assert "MSFT" in news_service._NEWS_CACHE

    def test_cache_hit_skips_network(self, monkeypatch):
        # Pre-populate the cache with a future expiry.
        news_service._NEWS_CACHE["GOOG"] = (
            time.monotonic() + 9999,
            [{"ticker": "GOOG", "title": "Cached"}],
        )
        called = []
        monkeypatch.setattr(
            "app.services.news_service.yf.Ticker",
            lambda _: called.append(True) or MagicMock(news=[]),
        )
        result = fetch_ticker_news("GOOG")
        assert not called
        assert result[0]["title"] == "Cached"
        # Cleanup
        del news_service._NEWS_CACHE["GOOG"]


# ── fetch_portfolio_news ──────────────────────────────────────────────────────

class TestFetchPortfolioNews:
    def test_empty_tickers_returns_empty(self):
        result = fetch_portfolio_news([])
        assert not result

    def test_dedup_across_tickers(self, monkeypatch):
        """An article returned under two tickers should appear only once."""
        news_service._NEWS_CACHE.clear()

        shared_item = _make_raw_item(title="Shared story", article_id="shared-001")

        def fake_ticker(_):
            mock = MagicMock()
            mock.news = [shared_item]  # same article for both tickers
            return mock

        monkeypatch.setattr("app.services.news_service.yf.Ticker", fake_ticker)

        result = fetch_portfolio_news(["AAPL", "MSFT"])
        # Shared article must appear under exactly one ticker.
        all_titles = [
            item["title"]
            for items in result.values()
            for item in items
        ]
        assert all_titles.count("Shared story") == 1

    def test_one_bad_ticker_doesnt_break_others(self, monkeypatch):
        news_service._NEWS_CACHE.clear()

        good_item = _make_raw_item(title="Good news", article_id="good-001")

        def fake_ticker(t):
            if t == "BAD":
                raise RuntimeError("yfinance exploded")
            mock = MagicMock()
            mock.news = [good_item]
            return mock

        monkeypatch.setattr("app.services.news_service.yf.Ticker", fake_ticker)

        result = fetch_portfolio_news(["GOOD", "BAD"])
        assert "GOOD" in result
        assert len(result["GOOD"]) == 1
        assert result.get("BAD", []) == []

    def test_all_tickers_present_in_result(self, monkeypatch):
        news_service._NEWS_CACHE.clear()

        mock_ticker = MagicMock()
        mock_ticker.news = []
        monkeypatch.setattr("app.services.news_service.yf.Ticker", lambda _: mock_ticker)

        result = fetch_portfolio_news(["AAPL", "MSFT", "GOOG"])
        for t in ("AAPL", "MSFT", "GOOG"):
            assert t in result


# ── build_themes_snapshot ─────────────────────────────────────────────────────

class TestBuildThemesSnapshot:
    def test_includes_all_tickers(self):
        meta = {
            "AAPL": {"is_watchlist": False, "weight_pct": 40.0},
            "MSFT": {"is_watchlist": False, "weight_pct": 30.0},
        }
        news = {
            "AAPL": [{"title": "Apple news"}, {"title": "More Apple"}],
            "MSFT": [],
        }
        snap = build_themes_snapshot(meta, news)
        tickers = [h["ticker"] for h in snap["holdings"]]
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_caps_headlines_at_three(self):
        meta = {"AAPL": {"is_watchlist": False}}
        news = {"AAPL": [{"title": f"Story {i}"} for i in range(10)]}
        snap = build_themes_snapshot(meta, news)
        aapl = next(h for h in snap["holdings"] if h["ticker"] == "AAPL")
        assert len(aapl["headlines"]) <= 3

    def test_watchlist_flag_preserved(self):
        meta = {"TSLA": {"is_watchlist": True}}
        news = {"TSLA": []}
        snap = build_themes_snapshot(meta, news)
        tsla = snap["holdings"][0]
        assert tsla["is_watchlist"] is True

    def test_weight_pct_included_when_present(self):
        meta = {"AAPL": {"is_watchlist": False, "weight_pct": 55.5}}
        snap = build_themes_snapshot(meta, {"AAPL": []})
        aapl = snap["holdings"][0]
        assert "weight_pct" in aapl
        assert aapl["weight_pct"] == 55.5

    def test_missing_ticker_in_news_gives_empty_headlines(self):
        meta = {"NVDA": {"is_watchlist": False}}
        snap = build_themes_snapshot(meta, {})
        nvda = snap["holdings"][0]
        assert nvda["headlines"] == []


# ── GET /api/news/feed ─────────────────────────────────────────────────────────


class TestNewsFeedEndpoint:
    def test_returns_holdings_key(self, monkeypatch):
        db = _make_db(("AAPL",))
        monkeypatch.setattr(
            news_router, "fetch_portfolio_news", lambda _tickers: {"AAPL": []}
        )
        monkeypatch.setattr(
            news_router, "_holding_info_brief",
            lambda _: {"company_name": "Apple Inc.", "sector": "Technology"},
        )
        result = asyncio.run(news_router.get_news_feed(portfolio_id=1, db=db))
        assert "holdings" in result
        assert isinstance(result["holdings"], list)

    def test_holding_has_required_fields(self, monkeypatch):
        db = _make_db(("AAPL",))
        monkeypatch.setattr(
            news_router, "fetch_portfolio_news", lambda _: {"AAPL": []}
        )
        monkeypatch.setattr(
            news_router, "_holding_info_brief",
            lambda _: {"company_name": "Apple Inc.", "sector": "Technology"},
        )
        result = asyncio.run(news_router.get_news_feed(portfolio_id=1, db=db))
        h = result["holdings"][0]
        for key in ("ticker", "company_name", "sector", "is_watchlist", "items"):
            assert key in h, f"holding missing key: {key}"

    def test_returns_generated_at(self, monkeypatch):
        db = _make_db(("AAPL",))
        monkeypatch.setattr(news_router, "fetch_portfolio_news", lambda _: {})
        monkeypatch.setattr(
            news_router, "_holding_info_brief", lambda _: {"company_name": "", "sector": ""}
        )
        result = asyncio.run(news_router.get_news_feed(portfolio_id=1, db=db))
        assert "generated_at" in result

    def test_empty_portfolio_returns_empty_holdings(self, monkeypatch):
        db = _make_db(())  # no holdings
        monkeypatch.setattr(news_router, "fetch_portfolio_news", lambda _: {})
        result = asyncio.run(news_router.get_news_feed(portfolio_id=1, db=db))
        assert result["holdings"] == []

    def test_holdings_sorted_by_sector_then_ticker(self, monkeypatch):
        db = _make_db(("MSFT", "AAPL", "VOO"))
        monkeypatch.setattr(news_router, "fetch_portfolio_news", lambda _: {
            "MSFT": [], "AAPL": [], "VOO": [],
        })

        sectors = {"AAPL": "Technology", "MSFT": "Technology", "VOO": "ETF"}

        def fake_brief(t):
            return {"company_name": t, "sector": sectors.get(t, "")}

        monkeypatch.setattr(news_router, "_holding_info_brief", fake_brief)
        result = asyncio.run(news_router.get_news_feed(portfolio_id=1, db=db))

        tickers = [h["ticker"] for h in result["holdings"]]
        # ETF sorts before Technology (E < T), and within Technology AAPL < MSFT
        etf_idx  = tickers.index("VOO")
        aapl_idx = tickers.index("AAPL")
        msft_idx = tickers.index("MSFT")
        assert etf_idx < aapl_idx
        assert aapl_idx < msft_idx

    def test_news_items_attached_to_correct_ticker(self, monkeypatch):
        db = _make_db(("AAPL",))
        fake_article = {
            "ticker": "AAPL",
            "title": "Big Apple day",
            "summary": "...",
            "url": "https://example.com",
            "source": "Reuters",
            "published_at": "2026-06-27T12:00:00Z",
            "thumbnail_url": None,
        }
        monkeypatch.setattr(
            news_router, "fetch_portfolio_news", lambda _: {"AAPL": [fake_article]}
        )
        monkeypatch.setattr(
            news_router, "_holding_info_brief",
            lambda _: {"company_name": "Apple Inc.", "sector": "Technology"},
        )
        result = asyncio.run(news_router.get_news_feed(portfolio_id=1, db=db))
        aapl = next(h for h in result["holdings"] if h["ticker"] == "AAPL")
        assert len(aapl["items"]) == 1
        assert aapl["items"][0]["title"] == "Big Apple day"
