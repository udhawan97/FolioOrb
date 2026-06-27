from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tip_system_uses_delegation_for_dynamic_verdict_triggers():
    js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")

    assert 'closest(".tip-trigger")' in js
    assert 'addEventListener("focusin"' in js
    assert 'addEventListener("mouseover"' in js
    assert 'querySelectorAll(".tip-trigger").forEach' not in js
    assert 'event.stopPropagation();\n    }, true)' not in js
    assert 'if (event.target.closest(".tip-trigger")) return;' in js
    assert "data-tip-title" in js
    assert "FolioSense's take" in js
    assert "Anchor hold" in js
    assert "Time horizon" in js
    assert "How Folio Sense decides" in js
    assert "It blends the signals that fit each holding" in js


def test_injected_anchor_tip_uses_dataset_attributes():
    js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")

    assert "function _anchorTipAttrs()" in js
    assert 'data-tip-title="Anchor hold"' in js
    assert "dataset.tipTitle" in js
    assert "toggleAnchorHold(event" in js


def test_existing_column_header_tooltips_still_use_shared_markup():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert 'class="tip-trigger target-tip-trigger"' in html
    assert 'data-tip-title="Trend Sense"' in html
    assert 'data-tip-title="Rating"' in html
    assert 'id="tip-popover"' in html


def test_nav_overflow_menu_holds_settings_and_ai_cost():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")

    assert 'id="nav-overflow-menu"' in html
    assert 'id="nav-overflow-trigger"' in html
    assert 'role="menu"' in html
    assert ".nav-overflow-menu" in css
    assert 'getElementById("nav-overflow-trigger")' in js
    assert 'getElementById("nav-overflow-menu")' in js


def test_semantic_color_tokens_defined_in_css():
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

    for token in ("--color-gain", "--color-loss", "--color-neutral", "--color-state", "--color-brand"):
        assert token in css
