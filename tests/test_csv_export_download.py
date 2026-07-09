# pylint: disable=protected-access
"""CSV export/template must DOWNLOAD, never render inline in the desktop WebView.

The WebView has no download chrome, so an ``<a download>`` or blob-URL click just
navigates and shows the CSV as a text page with no back button. The fix routes
saves through a native "Save As…" dialog (desktop/main.py's _NativeBridge) while
browsers keep their normal download. The GUI dialog can't run headlessly, so the
pure file-writing/sanitizing helpers are tested directly and the JS/HTML wiring is
asserted at the source level (the pattern used by tests/test_desktop_exit.py).
"""
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_desktop_main():
    """Import desktop/main.py under a non-__main__ name (skips the _hard_exit run)."""
    src = _ROOT / "desktop" / "main.py"
    spec = importlib.util.spec_from_file_location("desktop_main_under_test", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


desktop_main = _load_desktop_main()


# ── _safe_download_name: strip any directory traversal from a page-supplied name ─


def test_safe_name_strips_directories():
    assert desktop_main._safe_download_name("../../etc/passwd") == "passwd"
    assert desktop_main._safe_download_name("/tmp/holdings.csv") == "holdings.csv"


def test_safe_name_defaults_when_empty():
    assert desktop_main._safe_download_name("") == "export.csv"
    assert desktop_main._safe_download_name(None) == "export.csv"


# ── _write_text_file: exactly one BOM so Excel opens exported CSVs cleanly ──────


def test_write_adds_bom_when_missing(tmp_path):
    dest = tmp_path / "out.csv"
    desktop_main._write_text_file(str(dest), "ticker,shares\nVOO,10\n")
    assert dest.read_bytes().startswith(b"\xef\xbb\xbf")


def test_write_does_not_double_bom(tmp_path):
    dest = tmp_path / "out.csv"
    desktop_main._write_text_file(str(dest), "﻿ticker,shares\nVOO,10\n")
    raw = dest.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert not raw[3:].startswith(b"\xef\xbb\xbf")


# ── Desktop wiring: the native Save bridge is actually mounted on the window ─────


def test_desktop_exposes_save_bridge():
    src = (_ROOT / "desktop" / "main.py").read_text(encoding="utf-8")
    assert "class _NativeBridge" in src
    assert "def save_file(" in src
    assert "SAVE_DIALOG" in src
    # The bridge is useless unless it's actually handed to the window.
    assert "js_api=_NativeBridge()" in src


# ── Frontend wiring: export intercepts in the app, template routes through saveCsv ─


def test_dashboard_js_routes_through_native_save():
    js = (_ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    assert "function desktopSaveBridge()" in js
    assert "async function saveCsv(" in js
    assert "function handleExportClick(" in js
    # Template download must go through saveCsv, not a raw blob click.
    template = js[js.index("function downloadHoldingsTemplate("):]
    template = template[: template.index("}") + 1]
    assert "saveCsv(" in template


def test_export_anchor_intercepts_in_app():
    html = (_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'onclick="return handleExportClick(event)"' in html
    # Keep the href+download so a real browser still downloads with no JS help.
    assert 'href="/api/portfolio/holdings/export?portfolio_id=1" download' in html
