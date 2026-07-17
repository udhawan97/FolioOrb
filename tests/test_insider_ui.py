"""Tests for the insider-activity section in each holding's expanded detail."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js() -> str:
    return (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")


def _render() -> str:
    js = _js()
    assert "function renderInsiderActivity" in js
    return js.split("function renderInsiderActivity")[1][:3500]


def test_expand_row_has_an_insider_section():
    assert "intel-insider-section" in _js()


def test_insider_data_is_fetched_from_the_lazy_endpoint():
    js = _js()
    assert "/api/ai/insider-activity/" in js
    assert "cachedInsider" in js


def test_insider_is_wired_into_every_render_site():
    # Coverage/move/verdict render at three sites; insider must ride along at
    # each or it renders stale or not at all.
    js = _js()
    assert js.count("renderInsiderActivity(") >= 3


def test_headline_is_open_market_conviction():
    render = _render()
    assert "buys" in render
    assert "sells" in render


def test_non_conviction_trades_are_labelled_not_counted():
    # Option exercises / grants (action:"other") appear with their code_label,
    # never folded into the buy/sell headline.
    render = _render()
    assert "code_label" in render or "action" in render


def test_empty_state_is_calm_not_an_error():
    # transactions:[] with data_quality:"live" is normal (funds, quiet stocks).
    render = _render()
    assert "transactions" in render
    assert "data_quality" in render


def test_links_are_guarded_to_sec_gov():
    render = _render()
    assert "sec.gov" in render


def test_render_escapes_untrusted_text():
    # Owner names and roles come from filings — escape them.
    render = _render()
    assert "escapeHtml" in render
