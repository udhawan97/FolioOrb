# pylint: disable=redefined-outer-name
"""
Tests for app/services/holdings_repository.py — the one place that decides what
"an active holding in this portfolio" means.
Pure DB tests against in-memory SQLite; no network and no app wiring.
Mirrors the in-memory session setup used by tests/test_action_plan.py.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Holding, Portfolio
from app.services import holdings_repository as repo


# ── In-memory DB helpers ───────────────────────────────────────────────────────


@pytest.fixture
def db():
    """A session holding two portfolios, so cross-portfolio leaks are visible."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(Portfolio(id=1, name="Main"))
    session.add(Portfolio(id=2, name="Other"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _add(session, ticker, *, portfolio_id=1, is_active=True, **kwargs):
    """Insert one holding; rows get ascending ids in call order."""
    holding = Holding(
        portfolio_id=portfolio_id,
        ticker=ticker,
        shares=kwargs.pop("shares", 10.0),
        avg_cost=kwargs.pop("avg_cost", 100.0),
        is_active=is_active,
        **kwargs,
    )
    session.add(holding)
    session.commit()
    return holding


# ── active() ───────────────────────────────────────────────────────────────────


def test_active_returns_only_this_portfolio(db):
    _add(db, "AAPL", portfolio_id=1)
    _add(db, "MSFT", portfolio_id=2)
    assert [h.ticker for h in repo.active(db, 1)] == ["AAPL"]
    assert [h.ticker for h in repo.active(db, 2)] == ["MSFT"]


def test_active_excludes_soft_deleted(db):
    _add(db, "AAPL")
    _add(db, "GONE", is_active=False)
    assert [h.ticker for h in repo.active(db, 1)] == ["AAPL"]


def test_active_excludes_null_is_active(db):
    """A NULL flag is not True, so the row is not active."""
    _add(db, "AAPL")
    ghost = _add(db, "NULLY")
    db.execute(text("UPDATE holdings SET is_active = NULL WHERE id = :i"), {"i": ghost.id})
    db.commit()
    db.expire_all()
    assert [h.ticker for h in repo.active(db, 1)] == ["AAPL"]


def test_active_is_oldest_first(db):
    for ticker in ("ZZZ", "AAPL", "MMM"):
        _add(db, ticker)
    holdings = repo.active(db, 1)
    assert [h.ticker for h in holdings] == ["ZZZ", "AAPL", "MMM"]
    assert [h.id for h in holdings] == sorted(h.id for h in holdings)


def test_active_empty_portfolio(db):
    assert repo.active(db, 1) == []


def test_active_unknown_portfolio_is_empty_not_an_error(db):
    _add(db, "AAPL")
    assert repo.active(db, 999) == []


# ── active_by_ticker() ─────────────────────────────────────────────────────────


def test_active_by_ticker_finds_the_row(db):
    _add(db, "AAPL")
    found = repo.active_by_ticker(db, 1, "AAPL")
    assert found is not None and found.ticker == "AAPL"


def test_active_by_ticker_normalises_the_argument(db):
    _add(db, "AAPL")
    assert repo.active_by_ticker(db, 1, "  aapl ") is not None


def test_active_by_ticker_finds_one_legacy_formatted_stored_symbol(db):
    holding = _add(db, "AAPL")
    db.execute(
        text("UPDATE holdings SET ticker = ' aapl ' WHERE id = :holding_id"),
        {"holding_id": holding.id},
    )
    db.commit()
    db.expire_all()

    found = repo.active_by_ticker(db, 1, "AAPL")

    assert found is not None
    assert found.id == holding.id
    assert found.ticker == " aapl "


def test_active_by_ticker_misses_are_none(db):
    _add(db, "AAPL")
    assert repo.active_by_ticker(db, 1, "MSFT") is None
    assert repo.active_by_ticker(db, 1, "") is None


def test_active_by_ticker_ignores_inactive_and_other_portfolios(db):
    _add(db, "AAPL", is_active=False)
    _add(db, "MSFT", portfolio_id=2)
    assert repo.active_by_ticker(db, 1, "AAPL") is None
    assert repo.active_by_ticker(db, 1, "MSFT") is None


def test_add_active_rejects_a_duplicate_and_keeps_the_original(db):
    first = _add(db, "AAPL")
    duplicate = Holding(portfolio_id=1, ticker="AAPL", shares=99, avg_cost=100)
    assert repo.add_active(db, duplicate) is None
    found = repo.active_by_ticker(db, 1, "AAPL")
    assert found is not None and found.id == first.id


def test_add_active_enforces_normalized_ticker_identity(db):
    first = _add(db, "AAPL")
    duplicate = Holding(portfolio_id=1, ticker=" aapl ", shares=99, avg_cost=100)

    assert repo.add_active(db, duplicate) is None
    assert repo.active_by_ticker(db, 1, "AAPL").id == first.id


# ── active_tickers() ───────────────────────────────────────────────────────────


def test_active_tickers_normalises_case_and_whitespace(db):
    _add(db, " aapl ")
    _add(db, "Msft")
    assert repo.active_tickers(db, 1) == ["AAPL", "MSFT"]


def test_active_tickers_dedupes_keeping_first_seen(db):
    # Defensive read behavior for a pre-v7 or externally edited database. A
    # migrated production database prevents this state at the write boundary.
    db.execute(text("DROP INDEX ux_holdings_active_portfolio_ticker"))
    _add(db, "AAPL")
    _add(db, "MSFT")
    _add(db, "aapl")
    assert repo.active_tickers(db, 1) == ["AAPL", "MSFT"]


def test_active_tickers_keeps_insertion_order(db):
    for ticker in ("ZZZ", "AAPL", "MMM"):
        _add(db, ticker)
    assert repo.active_tickers(db, 1) == ["ZZZ", "AAPL", "MMM"]


def test_active_tickers_drops_blanks(db):
    _add(db, "AAPL")
    _add(db, "   ")
    assert repo.active_tickers(db, 1) == ["AAPL"]


def test_active_tickers_scopes_and_filters_like_active(db):
    _add(db, "AAPL")
    _add(db, "GONE", is_active=False)
    _add(db, "MSFT", portfolio_id=2)
    assert repo.active_tickers(db, 1) == ["AAPL"]


def test_active_tickers_empty_portfolio_has_no_fallback(db, monkeypatch):
    """The DEFAULT_HOLDINGS starter list must never leak in through here."""
    monkeypatch.setattr(repo, "DEFAULT_HOLDINGS", ["VOO", "QQQ"])
    assert not repo.active_tickers(db, 1)


# ── active_tickers_or_default() ────────────────────────────────────────────────


def test_or_default_falls_back_only_when_empty(db, monkeypatch):
    monkeypatch.setattr(repo, "DEFAULT_HOLDINGS", ["VOO", "QQQ"])
    assert repo.active_tickers_or_default(db, 1) == ["VOO", "QQQ"]
    _add(db, "AAPL")
    assert repo.active_tickers_or_default(db, 1) == ["AAPL"]


def test_or_default_returns_a_copy_callers_cannot_corrupt(db, monkeypatch):
    shared = ["VOO", "QQQ"]
    monkeypatch.setattr(repo, "DEFAULT_HOLDINGS", shared)
    returned = repo.active_tickers_or_default(db, 1)
    returned.append("OOPS")
    assert shared == ["VOO", "QQQ"]


# ── meta_map() ─────────────────────────────────────────────────────────────────


def test_meta_map_shape(db):
    _add(db, "AAPL", shares=3.0, avg_cost=150.0, is_watchlist=True, hold_class="anchor")
    assert repo.meta_map(db, 1) == {
        "AAPL": {
            "shares": 3.0,
            "avg_cost": 150.0,
            "is_watchlist": True,
            "hold_class": "anchor",
        }
    }


def test_meta_map_normalises_keys(db):
    _add(db, " aapl ")
    assert list(repo.meta_map(db, 1)) == ["AAPL"]


def test_meta_map_of_a_bare_holding_is_zeroed_not_missing(db):
    """Callers never guard: an untouched position reads as 0 / False / auto."""
    _add(db, "AAPL", shares=None, avg_cost=None, is_watchlist=None, hold_class=None)
    assert repo.meta_map(db, 1) == {
        "AAPL": {
            "shares": 0.0,
            "avg_cost": 0.0,
            "is_watchlist": False,
            "hold_class": "auto",
        }
    }


def test_meta_map_treats_a_null_watchlist_flag_as_false(db):
    """is_watchlist is nullable, so NULL must read as 'not watchlisted'."""
    holding = _add(db, "AAPL", is_watchlist=True)
    db.execute(text("UPDATE holdings SET is_watchlist = NULL WHERE id = :i"), {"i": holding.id})
    db.commit()
    assert repo.meta_map(db, 1)["AAPL"]["is_watchlist"] is False


def test_meta_map_treats_a_blank_hold_class_as_auto(db):
    """hold_class is NOT NULL but may still be empty; 'auto' is the floor."""
    holding = _add(db, "AAPL", hold_class="anchor")
    db.execute(text("UPDATE holdings SET hold_class = '' WHERE id = :i"), {"i": holding.id})
    db.commit()
    assert repo.meta_map(db, 1)["AAPL"]["hold_class"] == "auto"


def test_meta_map_scopes_and_filters_like_active(db):
    _add(db, "AAPL")
    _add(db, "GONE", is_active=False)
    _add(db, "MSFT", portfolio_id=2)
    assert list(repo.meta_map(db, 1)) == ["AAPL"]


def test_meta_map_keeps_the_original_after_duplicate_conflict(db):
    _add(db, "AAPL", shares=1.0)
    duplicate = Holding(portfolio_id=1, ticker="AAPL", shares=99.0, avg_cost=100)
    assert repo.add_active(db, duplicate) is None
    assert repo.meta_map(db, 1)["AAPL"]["shares"] == 1.0


def test_meta_map_keys_match_active_tickers_exactly(db):
    # Exercise the defensive legacy-state contract without weakening the v7
    # write invariant used by every normal database.
    db.execute(text("DROP INDEX ux_holdings_active_portfolio_ticker"))
    for ticker in ("ZZZ", "aapl", "MMM", "AAPL"):
        _add(db, ticker)
    _add(db, "GONE", is_active=False)
    assert list(repo.meta_map(db, 1)) == repo.active_tickers(db, 1)


def test_meta_map_empty_portfolio(db):
    assert not repo.meta_map(db, 1)
