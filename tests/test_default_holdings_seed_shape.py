"""`DEFAULT_HOLDINGS` seeds holdings without passing through the request schemas.

Every other way a holding is created runs the ticker-shape rule: the API bodies
validate it in ``app/schemas.py``, and CSV import goes through the same schema.
The ``DEFAULT_HOLDINGS`` env var does not — ``portfolio_lifecycle`` seeds straight
from it when the default portfolio is created — so a typo there used to plant a
row that every later quote and history request has to reject, with nothing
pointing at the cause.

``_seed_tickers`` filters the list and names what it dropped, so the entry is
gone from the seed *and* diagnosable in the log.
"""

import logging

from app.config import _seed_tickers


def test_valid_symbols_are_kept_and_uppercased(monkeypatch):
    monkeypatch.setenv("DEFAULT_HOLDINGS", "aapl, msft ,BRK.B")
    assert _seed_tickers("DEFAULT_HOLDINGS") == ["AAPL", "MSFT", "BRK.B"]


def test_malformed_symbols_are_dropped(monkeypatch):
    monkeypatch.setenv("DEFAULT_HOLDINGS", "AAPL,../x,MSFT,<script>,TOOLONGSYMBOL")
    assert _seed_tickers("DEFAULT_HOLDINGS") == ["AAPL", "MSFT"]


def test_dropped_symbols_are_named_in_the_log(monkeypatch, caplog):
    monkeypatch.setenv("DEFAULT_HOLDINGS", "AAPL,../x")
    with caplog.at_level(logging.WARNING, logger="app.config"):
        _seed_tickers("DEFAULT_HOLDINGS")
    # The point of the warning is that the user can tell *which* entry was bad.
    assert "../X" in caplog.text


def test_an_unset_variable_seeds_nothing(monkeypatch):
    monkeypatch.delenv("DEFAULT_HOLDINGS", raising=False)
    # A list, not just something falsey: the caller iterates the result.
    seeded = _seed_tickers("DEFAULT_HOLDINGS")
    assert isinstance(seeded, list)
    assert not seeded
