"""Wiring tests for the CSV import/export UI — assert the strings/ids that tie
the frontend, endpoints, and dependency together actually exist.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_js_wires_csv():
    js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
    # Import is a fetch POST from JS; export is a plain <a download> in the HTML.
    assert "/api/portfolio/holdings/import" in js
    assert "handleImportFile" in js
    assert "renderImportResult" in js
    assert "downloadHoldingsTemplate" in js
    assert "updateImportPanelMode" in js
    assert "initCsvImport" in js


def test_index_html_has_import_panel():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    assert 'id="import-csv-panel"' in html
    assert 'id="import-csv-input"' in html
    assert 'id="export-csv-btn"' in html
    assert "/api/portfolio/holdings/export" in html  # export anchor target
    # The two mode copy blocks carry the engine-scoped attributes so they flip live.
    assert 'id="import-copy-local"' in html and "data-engine-local-only" in html
    assert 'id="import-copy-claude"' in html and "data-engine-claude-only" in html


def test_css_has_import_styles():
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    assert ".manage-import-card" in css
    assert ".import-senpai-note" in css
    assert ".import-mode-pill--claude" in css
    assert ".import-mode-pill--local" in css


def test_requirements_pins_multipart():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "python-multipart==" in reqs


def test_router_registers_csv_endpoints():
    router = (ROOT / "app/routers/portfolio.py").read_text(encoding="utf-8")
    assert '"/holdings/export"' in router
    assert '"/holdings/import"' in router
