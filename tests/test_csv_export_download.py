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
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import database as app_database
from app.services import review_bundle

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


def test_write_keeps_html_plain_utf8(tmp_path):
    dest = tmp_path / "review.html"
    desktop_main._write_text_file(str(dest), "<!doctype html><title>Review</title>")
    assert dest.read_bytes().startswith(b"<!doctype html>")


def test_binary_write_is_atomic_and_preserves_existing_file_on_swap_failure(
    tmp_path, monkeypatch
):
    dest = tmp_path / "records.zip"
    dest.write_bytes(b"existing-complete-file")

    def fail_swap(_source, _target):
        raise OSError("simulated swap failure")

    monkeypatch.setattr(desktop_main.os, "replace", fail_swap)
    with pytest.raises(OSError, match="swap failure"):
        desktop_main._write_binary_file(str(dest), b"replacement")

    assert dest.read_bytes() == b"existing-complete-file"
    assert not list(tmp_path.glob(".records.zip-*.tmp"))


def test_binary_write_reports_success_after_parent_fsync_failure(tmp_path, monkeypatch):
    dest = tmp_path / "records.zip"
    dest.write_bytes(b"existing-complete-file")
    monkeypatch.setattr(
        desktop_main,
        "_fsync_parent",
        lambda _path: (_ for _ in ()).throw(OSError("directory fsync failed")),
    )

    result = desktop_main._write_binary_file(str(dest), b"replacement-complete-file")

    assert result == str(dest)
    assert dest.read_bytes() == b"replacement-complete-file"


def test_smoke_environment_uses_an_isolated_data_root(tmp_path, monkeypatch):
    smoke_root = tmp_path / "smoke-root"
    monkeypatch.setenv("DATABASE_URL", "sqlite:////real/user/portfolio.db")
    monkeypatch.setenv("FOLIOORB_DATA_DIR", "/real/user/data")
    monkeypatch.setenv("FOLIOORB_SMOKE_TEST", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-survive-smoke")
    monkeypatch.setattr(desktop_main.tempfile, "mkdtemp", lambda **_kwargs: str(smoke_root))

    selected = desktop_main._configure_smoke_environment()

    assert selected == str(smoke_root)
    assert os.environ["FOLIOORB_DATA_DIR"] == str(smoke_root)
    assert os.environ["DATABASE_URL"] == f"sqlite:///{smoke_root / 'portfolio.db'}"


# ── Desktop wiring: the native Save bridge is actually mounted on the window ─────


def test_desktop_exposes_save_bridge():
    src = (_ROOT / "desktop" / "main.py").read_text(encoding="utf-8")
    assert "class _NativeBridge" in src
    assert "def save_file(" in src
    assert "def export_backup(" in src
    assert "def export_portable_records(" in src
    assert "def export_review_bundle(" in src
    assert "SAVE_DIALOG" in src
    # The bridge is useless unless it's actually handed to the window.
    assert "js_api=_NativeBridge()" in src


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


def _install_bundle_bridge_fakes(monkeypatch, window, builder):
    session = object()
    monkeypatch.setattr(
        app_database,
        "SessionLocal",
        lambda: _FakeSessionContext(session),
    )
    monkeypatch.setattr(review_bundle, "build_review_bundle", builder)
    monkeypatch.setattr(
        review_bundle,
        "bundle_filename",
        lambda portfolio_id, period: f"bundle-{portfolio_id}-{period}.zip",
    )
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(
            SAVE_DIALOG="save",
            active_window=lambda: window,
        ),
    )
    return session


def test_desktop_review_bundle_saves_exact_binary_bytes(tmp_path, monkeypatch):
    destination = tmp_path / "chosen.zip"
    calls = []

    class Window:
        @staticmethod
        def create_file_dialog(dialog_type, *, save_filename):
            calls.append((dialog_type, save_filename))
            return str(destination)

    def build(session, portfolio_id, period):
        calls.append((session, portfolio_id, period))
        return b"PK\x03\x04exact-zip-bytes"

    session = _install_bundle_bridge_fakes(monkeypatch, Window(), build)
    result = desktop_main._NativeBridge().export_review_bundle(7, "quarter")

    assert result == {"saved": True, "path": str(destination)}
    assert destination.read_bytes() == b"PK\x03\x04exact-zip-bytes"
    assert calls == [
        (session, 7, "quarter"),
        ("save", "bundle-7-quarter.zip"),
    ]


def test_desktop_review_bundle_cancel_writes_nothing(tmp_path, monkeypatch):
    def build(_session, _portfolio_id, _period):
        return b"complete-zip"

    class Window:
        @staticmethod
        def create_file_dialog(_dialog_type, *, save_filename):
            assert save_filename == "bundle-1-month.zip"

    _install_bundle_bridge_fakes(monkeypatch, Window(), build)
    result = desktop_main._NativeBridge().export_review_bundle(1, "month")

    assert result == {"saved": False, "path": None}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("failure_stage", ["build", "write"])
def test_desktop_review_bundle_failure_reports_no_success(
    tmp_path,
    monkeypatch,
    failure_stage,
):
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"existing-complete-file")

    class Window:
        @staticmethod
        def create_file_dialog(_dialog_type, *, save_filename):
            assert save_filename == "bundle-1-month.zip"
            return str(destination)

    def build(_session, _portfolio_id, _period):
        if failure_stage == "build":
            raise RuntimeError("simulated build failure")
        return b"replacement"

    _install_bundle_bridge_fakes(monkeypatch, Window(), build)
    if failure_stage == "write":
        monkeypatch.setattr(
            desktop_main,
            "_write_binary_file",
            lambda _path, _payload: (_ for _ in ()).throw(OSError("write failure")),
        )

    result = desktop_main._NativeBridge().export_review_bundle(1, "month")

    expected_error = "RuntimeError" if failure_stage == "build" else "OSError"
    assert result == {"saved": False, "path": None, "error": expected_error}
    assert destination.read_bytes() == b"existing-complete-file"


# ── Frontend wiring: every text export routes through the shared adapter ──────


def test_dashboard_js_routes_through_native_save():
    js = (_ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    assert "function handleExportClick(" in js
    assert "function desktopSaveBridge()" not in js
    template = js[js.index("function downloadHoldingsTemplate("):]
    template = template[: template.index("}") + 1]
    assert "LocalTextExport.saveText(" in template
    assert "LocalTextExport.saveResponse(" in js


def test_export_anchor_intercepts_in_app():
    html = (_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'onclick="return handleExportClick(event)"' in html
    # Keep the href+download as progressive fallback if the bundle cannot boot.
    assert 'href="/api/portfolio/holdings/export?portfolio_id=1" download' in html
    assert 'src="/static/js/local-text-export.js?v=0"' in html
