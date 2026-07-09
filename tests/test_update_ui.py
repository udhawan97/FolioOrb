"""Presence and wiring of the in-app Software Update UI.

Follows the project convention of asserting on the shipped template/JS/CSS so a
refactor that drops a required hook is caught. Behavior of the underlying
endpoints is covered by test_system_router / test_update_service.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_update_markup_present():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    # Passive indicators.
    assert 'id="update-pill"' in html
    assert 'id="nav-update-dot"' in html
    assert 'id="nav-software-update"' in html
    assert 'onclick="FolioUpdates.open()"' in html

    # The sheet and its state regions.
    assert 'id="update-sheet"' in html
    assert 'role="dialog"' in html.split('id="update-sheet"')[1][:120]
    assert 'aria-modal="true"' in html.split('id="update-sheet"')[1][:160]
    for marker in (
        'id="update-sheet-title"', 'id="update-sub"', 'id="update-progress"',
        'id="update-notes"', 'id="update-trust"', 'id="update-primary"',
        'id="update-secondary"', 'id="update-skip"', 'id="update-restore"',
        'id="update-pref-auto"', 'id="update-pref-notify"',
    ):
        assert marker in html, marker

    # Script include.
    assert "/static/js/updates.js" in html


def test_updates_js_exposes_api_and_states():
    js = (ROOT / "static/js/updates.js").read_text(encoding="utf-8")

    assert "window.FolioUpdates" in js
    for fn in ("function open(", "function openAndCheck(", "function close("):
        assert fn in js, fn

    # Talks only to the system API.
    assert "/api/system/version" in js
    assert "/api/system/update/check" in js
    assert "/api/system/update/status" in js
    assert "/api/system/update/settings" in js
    assert "/api/system/update/skip" in js

    # Every lifecycle state has a render branch.
    for status in (
        '"checking"', '"up_to_date"', '"available"', '"downloading"',
        '"verifying"', '"backing_up"', '"ready"', '"offline"', '"error"',
    ):
        assert status in js, status

    # Notes are escaped before any limited formatting is applied (XSS guard).
    assert 'replace(/&/g, "&amp;")' in js
    # Accessibility: focus trap + Escape handling.
    assert "trapFocus" in js
    assert 'e.key === "Escape"' in js


def test_update_styles_present():
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    for selector in (
        ".fs-update-pill", ".fs-update-panel", ".fs-update-notes",
        ".fs-update-trust", ".fs-update-btn--primary", ".fs-switch",
        "prefers-reduced-motion",
    ):
        assert selector in css, selector
