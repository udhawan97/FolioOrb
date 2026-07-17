"""Tests for multi-portfolio scoping of the AI endpoints.

Two concerns are covered:

(a) The portfolio-LEVEL AI cache (AISummary.ticker sentinel "BOOK") is namespaced
    per portfolio ("BOOK:<id>").  AISummary has no portfolio_id column, so without
    namespacing a second portfolio would read the first portfolio's cached BOOK
    narrative — a silent cross-portfolio data bleed.  We drive the briefing
    endpoint for two portfolios with different holdings and assert each gets its
    own cache row and its own narrative.

(b) Every portfolio-scoped endpoint accepts a ``portfolio_id`` query param that
    defaults to 1, while the global (non-portfolio) endpoints do not.

The endpoints are plain ``async def`` functions, so they're called directly with
``asyncio.run`` and an in-memory SQLite DB — the Anthropic/generate layer and the
quote/regime layers are monkeypatched, so no network and no real key.
"""
# pylint: disable=protected-access
import asyncio
import inspect

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import AISummary, Base, Holding, Portfolio
from app.routers import ai as ai_router
from app.services import analytics_insights, portfolio_valuation


def make_multi_portfolio_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(Portfolio(id=1, name="Portfolio One"))
    session.add(Portfolio(id=2, name="Portfolio Two"))
    session.commit()
    return session


def add_holding(db, portfolio_id, ticker, shares, avg_cost):
    db.add(
        Holding(
            portfolio_id=portfolio_id,
            ticker=ticker,
            shares=shares,
            avg_cost=avg_cost,
            is_active=True,
        )
    )
    db.commit()


def quote(ticker, price, day_change=0.0, day_change_pct=0.0):
    return {
        "ticker": ticker,
        "name": f"{ticker} Inc.",
        "current_price": price,
        "day_change": day_change,
        "day_change_pct": day_change_pct,
    }


def _param_default(fn, name):
    """Effective default of a param, unwrapping a FastAPI Query() wrapper."""
    param = inspect.signature(fn).parameters[name]
    default = param.default
    return getattr(default, "default", default)


# ── (a) BOOK cache is namespaced per portfolio (no cross-read) ────────────────

def test_book_cache_is_namespaced_per_portfolio(monkeypatch):
    db = make_multi_portfolio_db()
    add_holding(db, 1, "AAA", shares=10, avg_cost=100)
    add_holding(db, 2, "BBB", shares=5, avg_cost=50)

    quotes = {
        "AAA": quote("AAA", 110, day_change=1.0, day_change_pct=0.9),
        "BBB": quote("BBB", 60, day_change=0.5, day_change_pct=0.8),
    }
    monkeypatch.setattr(
        portfolio_valuation,
        "get_portfolio_quotes",
        lambda tickers: [quotes[t] for t in tickers if t in quotes],
    )
    monkeypatch.setattr(
        ai_router, "get_market_regime", lambda: {"label": "", "mood": ""}
    )

    # Stub Haiku: echo which portfolio's snapshot it saw so cross-reads are visible.
    generate_calls = []

    def stub_briefing(snapshot):
        best = (snapshot.get("best_today") or {}).get("ticker", "")
        generate_calls.append(best)
        return {
            "health": f"book:{best}",
            "drivers": [],
            "adjustments": [],
            "quote": "q",
            "seen_ticker": best,
            "seen_total_value": snapshot.get("total_value"),
        }

    monkeypatch.setattr(ai_router, "generate_portfolio_briefing", stub_briefing)

    # Portfolio 1 → generates + caches under BOOK:1
    r1 = asyncio.run(ai_router.get_portfolio_summary(portfolio_id=1, db=db))
    # Portfolio 2 → must NOT read BOOK:1; generates its own + caches under BOOK:2
    r2 = asyncio.run(ai_router.get_portfolio_summary(portfolio_id=2, db=db))

    assert r1["seen_ticker"] == "AAA"
    assert r1["seen_total_value"] == 1100.0
    # The bug this guards: without namespacing, r2 reads BOOK:1 and returns "AAA".
    assert r2["seen_ticker"] == "BBB"
    assert r2["seen_total_value"] == 300.0
    # Each portfolio triggered exactly one generation — no cross-portfolio shortcut.
    assert generate_calls == ["AAA", "BBB"]

    # Two distinct, namespaced cache rows exist.
    cached_tickers = {row.ticker for row in db.query(AISummary).all()}
    assert "BOOK:1" in cached_tickers
    assert "BOOK:2" in cached_tickers

    # Portfolio 1 re-read hits ITS OWN cache (proves the namespaced key is used on
    # read too, not just write) and does not re-generate.
    r1_again = asyncio.run(ai_router.get_portfolio_summary(portfolio_id=1, db=db))
    assert r1_again.get("from_cache") is True
    assert r1_again["seen_ticker"] == "AAA"
    assert generate_calls == ["AAA", "BBB"]


def test_portfolio_cache_ticker_helper():
    assert ai_router._portfolio_cache_ticker(1) == "BOOK:1"
    assert ai_router._portfolio_cache_ticker(2) == "BOOK:2"
    # Default keeps the single-portfolio case pointed at its own namespace.
    assert ai_router._portfolio_cache_ticker() == "BOOK:1"


# ── (b) Endpoints accept portfolio_id; global endpoints do not ────────────────

_SCOPED_ENDPOINTS = [
    ai_router.get_all_summaries,
    ai_router.get_all_move_explanations,
    ai_router.get_all_intelligence,
    ai_router.get_investment_signal_single,
    ai_router.get_all_investment_signals,
    ai_router.get_portfolio_exposure,
    ai_router.get_all_analyst_recommendations,
    ai_router.get_portfolio_summary,
    ai_router.get_analytics_insights,
    ai_router.get_action_plan,
    # Verdict history is now per-portfolio too (v5.4.1).
    ai_router.get_verdict_calibration,
    ai_router.get_verdict_report,
]

_GLOBAL_ENDPOINTS = [
    ai_router.get_ai_cache_stats,
    ai_router.get_claude_heartbeat,
    ai_router.configure_api_key,
    ai_router.remove_api_key,
    ai_router.get_stock_summary,
    ai_router.get_move_explanation,
    ai_router.get_holding_intelligence_single,
    ai_router.get_holding_intelligence_deep,
    ai_router.get_analyst_recommendation_single,
]


def test_scoped_endpoints_accept_portfolio_id_defaulting_to_one():
    for fn in _SCOPED_ENDPOINTS:
        params = inspect.signature(fn).parameters
        assert "portfolio_id" in params, f"{fn.__name__} missing portfolio_id"
        assert _param_default(fn, "portfolio_id") == 1, (
            f"{fn.__name__} portfolio_id must default to 1"
        )


def test_global_endpoints_have_no_portfolio_id():
    for fn in _GLOBAL_ENDPOINTS:
        params = inspect.signature(fn).parameters
        assert "portfolio_id" not in params, (
            f"{fn.__name__} must stay global (no portfolio_id)"
        )


def test_build_analytics_snapshot_accepts_portfolio_id():
    params = inspect.signature(analytics_insights.build_analytics_snapshot).parameters
    assert "portfolio_id" in params
    assert params["portfolio_id"].default == 1
