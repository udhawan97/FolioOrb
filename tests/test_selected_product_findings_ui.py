"""UI contracts for the selected product findings."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates/index.html").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
ANALYTICS = (ROOT / "static/js/analytics-charts.js").read_text(encoding="utf-8")


def _function_body(source, name, next_name):
    start = source.index(f"function {name}(")
    return source[start:source.index(f"function {next_name}(", start)]


def test_holding_intel_copy_drops_only_the_false_ai_qualifiers():
    assert "Click any row to expand Holding Intel." in INDEX
    assert "Load Holding Intel</span>" in INDEX
    assert "AI-powered analysis" not in INDEX
    assert "Load Holding Intel (AI)" not in INDEX
    assert "Claude AI" in INDEX


def test_market_contract_loads_before_both_renderers():
    market_state = INDEX.index("/static/js/market-state.js")
    assert market_state < INDEX.index("/static/js/analytics-charts.js")
    assert market_state < INDEX.index("/static/js/dashboard.js")


def test_unavailable_overview_rows_use_neutral_copy_without_a_direction_icon():
    body = _function_body(DASHBOARD, "renderWorldMarkets", "loadWorldMarkets")
    assert '"is-unavailable"' in body
    assert '<span class="market-tile-unavailable">Unavailable</span>' in body
    assert "FolioMarketState.direction(m)" in body
    assert "_cachedWorldMarketsForAnalytics = FolioMarketState.availableRows(rows)" in body


def test_analytics_defensively_filters_unavailable_rows():
    tape = _function_body(ANALYTICS, "refreshMarketsTape", "corrBarColor")
    grid = _function_body(ANALYTICS, "renderMarketsPortfolioGrid", "renderMarketsContext")
    assert "FolioMarketState.availableRows(markets)" in tape
    assert "FolioMarketState.availableRows(markets)" in grid


def test_removal_uses_accessible_dialog_and_locked_retry_contract():
    body = _function_body(DASHBOARD, "removeHolding", "removeTrade")
    assert "confirm(" not in body
    assert "promptSaleDetails" in body
    assert "HoldingRemovalLogic.buildPayload" in body
    assert "HoldingRemovalLogic.requiresExplicitPrice" in body
    assert "requirePrice: true" in body


def test_sale_dialog_defaults_and_caps_at_the_local_calendar_date():
    body = _function_body(DASHBOARD, "promptSaleDetails", "updateHolding")
    assert "HoldingRemovalLogic.localCalendarDate()" in body
    assert 'max="${today}" value="${today}"' in body
    assert "toISOString" not in body
