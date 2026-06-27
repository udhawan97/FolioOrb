"""Tests for growth projection dashboard wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_analytics_section_has_projection_chart():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

    assert 'data-zone-pane="analytics"' in html
    assert 'id="projection-chart"' in html
    assert 'id="projection-horizon-tabs"' in html
    assert 'data-horizon="30d"' in html
    assert 'data-horizon="10y"' in html
    assert "Growth projection" in html
    assert "/api/portfolio/projection" in js
    assert "function renderProjectionChart" in js
    assert "function loadProjection" in js
    assert "updateChartChrome(projectionChart)" in js
    assert ".projection-chart-shell" in css
    assert ".projection-summary-row" in css
