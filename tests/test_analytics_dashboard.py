"""Tests for Analytics sub-tab dashboard wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_analytics_sub_tabs_present():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/analytics-charts.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

    assert 'id="analytics-zone-tabs"' in html
    assert 'id="analytics-insight-bar"' in html
    assert 'id="analytics-module-insight"' in html
    assert 'data-analytics-pane="performance"' in html
    assert 'data-analytics-pane="risk"' in html
    assert 'data-analytics-pane="exposure"' in html
    assert 'data-analytics-pane="signals"' in html
    assert 'data-analytics-pane="markets"' in html
    assert 'id="geo-exposure-list"' in html
    assert "geoCountryFlag" in js
    assert ".geo-bar-flag" in css
    assert ".portfolio-contrib-row" in css
    assert 'id="risk-reward-chart"' in html
    assert 'id="markets-portfolio-grid"' in html
    assert "/api/portfolio/market-context" in js
    assert "AnalyticsCharts" in js
    assert "/api/portfolio/risk-metrics" in js
    assert "/api/portfolio/correlation" in js
    assert "/api/portfolio/drawdown" in js
    assert "/api/portfolio/contribution" in js
    assert "/api/ai/analytics-insights" in js
    assert "loadModuleInsights" in js
    assert ".analytics-zone-tabs" in css
    assert ".analytics-insight-bar" in css
    assert "prefers-reduced-motion" in css


def test_portfolio_analytics_endpoints_registered():
    router = (ROOT / "app/routers/portfolio.py").read_text(encoding="utf-8")
    assert '"/risk-metrics"' in router
    assert '"/correlation"' in router
    assert '"/drawdown"' in router
    assert '"/contribution"' in router
    assert '"/market-context"' in router
    assert '"/benchmark-comparison"' in router
    assert '"/return-calendar"' in router
    assert '"/beta"' in router
    assert '"/rolling-volatility"' in router
    assert '"/sector-tilt"' in router
    assert '"/conviction-gaps"' in router
    assert '"/confidence-spectrum"' in router
    assert '"/macro-alignment"' in router


def test_analytics_new_widgets_present():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/analytics-charts.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    assert 'id="benchmark-tracker-card"' in html
    assert 'id="beta-dial-card"' in html
    assert 'id="rolling-vol-card"' in html
    assert 'id="sector-tilt-card"' in html
    assert 'id="conviction-gap-card"' in html
    assert 'id="confidence-spectrum-card"' in html
    assert 'id="macro-alignment-card"' in html
    assert 'data-widget-insight=' in html
    assert "applyWidgetInsights" in js
    assert "loadBenchmarkChart" in js
    assert "loadMacroAlignment" in js
    assert ".analytics-widget-insight" in css
