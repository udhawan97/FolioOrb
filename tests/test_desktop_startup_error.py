"""Packaged startup failures remain visible and actionable without a console."""
# pylint: disable=protected-access

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path


def _load_desktop_main():
    source = Path(__file__).resolve().parent.parent / "desktop" / "main.py"
    spec = importlib.util.spec_from_file_location("desktop_startup_under_test", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


desktop_main = _load_desktop_main()


def test_startup_error_document_escapes_local_failure_details():
    document = desktop_main._startup_error_document(
        "Could not <start>", "Ticker <SCRIPT>", "Use A&B"
    )

    assert "Could not &lt;start&gt;" in document
    assert "Ticker &lt;SCRIPT&gt;" in document
    assert "Use A&amp;B" in document
    assert "Ticker <SCRIPT>" not in document
    assert "default-src 'none'" in document


def test_frozen_startup_error_opens_a_native_webview(monkeypatch):
    calls = []
    fake_webview = types.SimpleNamespace(
        create_window=lambda *args, **kwargs: calls.append((args, kwargs)),
        start=lambda: calls.append(("start", {})),
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop_main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        desktop_main,
        "_surface_duplicate_recovery",
        lambda detail: calls.append(((detail,), {"recovery": True})) or True,
    )

    desktop_main._surface_server_startup_error(
        "DuplicateActiveHoldingsError: portfolio 1 / AAPL (2 rows)"
    )

    assert calls == [(("portfolio 1 / AAPL (2 rows)",), {"recovery": True})]


def test_duplicate_recovery_document_requires_a_keep_choice_and_names_safety():
    document = desktop_main._duplicate_recovery_document(
        [
            {
                "portfolio_id": 1,
                "ticker": "AAPL",
                "rows": [
                    {
                        "id": 7,
                        "stored_ticker": "<AAPL>",
                        "shares": 2,
                        "avg_cost": 100,
                        "is_watchlist": False,
                        "hold_class": "anchor",
                        "notes": "retirement & " + ("long " * 45),
                        "company_name": "Apple & Co",
                        "thesis_reviewed_at": "2026-08-01",
                        "thesis_review_interval_days": 30,
                        "target_weight_bps": 5500,
                        "added_at": "2025-03-04",
                    },
                    {
                        "id": 8,
                        "stored_ticker": "aapl",
                        "shares": 1,
                        "avg_cost": 120,
                        "is_watchlist": False,
                        "hold_class": "trade",
                        "notes": "",
                    },
                ],
            }
        ]
    )

    assert "Create backup and apply choices" in document
    assert "without\nrecording a sale" in document
    assert "&lt;AAPL&gt;" in document
    assert "Apple &amp; Co" in document
    assert "Target weight (basis points): 5500" in document
    assert "Thesis reviewed: 2026-08-01" in document
    assert "Thesis review interval (days): 30" in document
    assert "Added: 2025-03-04" in document
    assert "retirement &amp; " + ("long " * 44) + "long" in document
    assert "window.pywebview.api.resolve_duplicates" in document
    assert "script-src 'unsafe-inline' 'unsafe-eval'" in document
    assert not re.search(r'<input type="radio"[^>]*\schecked(?:\s|>)', document)
    assert "everyGroupChosen" in document
    assert "Choose one row to keep in every group." in document
    assert "No holdings were changed. Verified Backup Vault copy:" in document


def test_source_startup_error_stays_noninteractive(monkeypatch):
    monkeypatch.delattr(desktop_main.sys, "frozen", raising=False)
    fake_webview = types.SimpleNamespace(
        create_window=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("source diagnostics must not open a UI")
        )
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    desktop_main._surface_startup_error("Title", "Detail", "Recovery")


def test_profile_io_failure_is_surfaced_without_false_no_write_claim(monkeypatch):
    class FakeProfileConfigurationError(RuntimeError):
        pass

    def fail_to_prepare():
        raise PermissionError("profile is read-only")

    fake_paths = types.SimpleNamespace(
        ProfileConfigurationError=FakeProfileConfigurationError,
        prepare_runtime_profile=fail_to_prepare,
    )
    surfaced = []
    monkeypatch.setitem(sys.modules, "app.paths", fake_paths)
    monkeypatch.setattr(desktop_main.sys, "argv", ["desktop/main.py"])
    monkeypatch.setattr(
        desktop_main,
        "_surface_startup_error",
        lambda title, detail, recovery: surfaced.append((title, detail, recovery)),
    )

    assert desktop_main.main() == 1
    assert surfaced[0][0] == "FolioOrb profile could not be prepared"
    assert "PermissionError: profile is read-only" in surfaced[0][1]
    assert "No portfolio migration was started" in surfaced[0][2]
    assert "partial legacy copy" in surfaced[0][2]
