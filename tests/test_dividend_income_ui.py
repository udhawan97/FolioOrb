"""Tests for the dividend-income card in the Analytics zone."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js() -> str:
    return (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")


def _html() -> str:
    return (ROOT / "templates/index.html").read_text(encoding="utf-8")


def _render() -> str:
    js = _js()
    assert "function renderIncome" in js
    return js.split("function renderIncome")[1][:3000]


def test_card_and_states_exist_in_markup():
    html = _html()
    assert 'id="income-card"' in html
    assert 'id="income-body"' in html
    assert 'id="income-empty"' in html
    assert 'id="income-loading"' in html


def test_income_loaded_from_the_portfolio_endpoint():
    js = _js()
    assert "/api/portfolio/income" in js
    assert "ensureIncomeLoaded" in js


def test_income_loads_in_the_analytics_zone():
    # The card must be triggered wherever fee-drag is, or it never loads.
    js = _js()
    assert js.count("ensureIncomeLoaded()") >= 1


def test_income_cache_invalidates_when_holdings_change():
    # Same staleness trap as fee-drag: a ticker change must drop the cache.
    js = _js()
    assert "_incomeLoaded = false" in js


def test_headline_is_annual_income_and_yield():
    render = _render()
    assert "total_annual_income" in render
    assert "portfolio_yield" in render


def test_non_payers_are_named_not_counted_as_zero():
    render = _render()
    assert "non_payers" in render or "non_payer" in render


def test_empty_state_when_nothing_pays():
    render = _render()
    assert "has_data" in render


def test_render_escapes_untrusted_text():
    render = _render()
    assert "escapeHtml" in render


def test_payer_rows_can_show_an_ex_dividend_chip():
    js = _js()
    # renderIncome hands each payer's ex-date to the chip helper...
    assert "_exDivChip(p.ex_dividend_date)" in js
    # ...which highlights a near cutoff (proximity computed, past dates dropped).
    chip = js.split("function _exDivChip")[1][:700]
    assert "income-exdiv" in chip
    assert "income-exdiv--soon" in chip
