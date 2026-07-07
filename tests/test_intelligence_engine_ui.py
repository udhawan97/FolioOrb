"""Tests for intelligence engine dropdown UI consistency across pages."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_engine_scoped_markup_present():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    dash_js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

    assert 'data-engine-claude-only' in html
    assert 'data-engine-local-only' in html
    assert 'id="holdings-intel-hub"' in html
    assert 'id="btn-holdings-refresh"' in html
    assert 'onclick="refreshHoldingsTable()"' in html
    assert 'onclick="onHoldingsIntelHubClick()"' in html
    assert 'hub-line--claude' in html
    assert 'Claude Summaries' in html
    assert 'id="local-intel-guide"' in html
    assert 'data-engine-local-only' in html.split('id="local-intel-guide"')[1][:120]
    assert 'id="brand-cost-trigger"' in html
    assert 'id="hud-claude-row"' in html
    assert 'id="briefing-seg"' in html
    assert 'hidden' in html.split('id="briefing-seg"')[1][:80]

    assert "onHoldingsIntelHubClick" in dash_js
    assert "refreshHoldingsTable" in dash_js
    assert "updateHoldingsIntelHub" in dash_js
    assert "setEngineScopedVisibility" in dash_js
    assert "validateIntelligenceEngineUi" in dash_js
    assert "getIntelligenceEngineMode" in dash_js
    assert "intelligenceSignalsUrl" in dash_js
    assert 'dataset.intelligenceEngine' in dash_js

    assert '[data-intelligence-engine="local"] [data-engine-claude-only]' in css
    assert '[data-intelligence-engine="claude"] [data-engine-local-only]' in css
    assert '.holdings-intel-hub' in css
    assert '.btn-holdings-refresh' in css


def test_briefing_follows_global_engine():
    dash_js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")

    assert "function _briefingDefaultMode()" in dash_js
    assert 'return isLocalIntelligenceMode() ? "local" : "ai"' in dash_js
    assert "loadPortfolioBriefing(null, true)" in dash_js
    assert "seg.hidden = true" in dash_js


def test_hold_mode_strip_ui():
    dash_js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

    assert "function _renderHoldModeStrip(" in dash_js
    assert "function _renderManageHoldModeSection(" in dash_js
    assert "function _syncManageHoldModeCard(" in dash_js
    assert "function setHoldMode(" in dash_js
    assert "function _syncHoldModeStrip(" in dash_js
    assert "_HOLD_MODE_META" in dash_js
    assert "_VERDICT_PILL_TIPS" in dash_js
    assert 'role="radiogroup"' in dash_js
    assert "manage-hold-mode-detail" in dash_js
    assert "tipBody:" in dash_js.split("_HOLD_MODE_META")[1][:1200]
    assert ".hold-mode-strip" in css
    assert ".hold-mode-seg.is-active" in css
    assert ".manage-hold-mode-grid" in css
    assert ".manage-hold-mode-detail" in css
    assert ".briefing-verdict-pill.tip-trigger" in css


def test_analytics_signals_respect_engine_mode():
    js = (ROOT / "static/js/analytics-charts.js").read_text(encoding="utf-8")

    assert "analyticsSignalsUrl" in js
    assert "isLocalIntelligenceMode" in js
    assert 'force_local=true' in js


def test_enable_claude_ai_button_persists_mode():
    """Regression: enabling Claude AI via the banner button must survive a page reload.

    enableClaudeAiAndReload() saves SENPAI_MODE_KEY="0" to localStorage before
    reloading.  initDashboardSenpai() must read that value back — not hardcode
    _forcedLocalMode = true — otherwise the mode resets on every load.
    """
    dash_js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")

    # The init block must NOT unconditionally set _forcedLocalMode to true
    assert "_forcedLocalMode = true;\n    applyForcedLocalMode" not in dash_js, (
        "_forcedLocalMode is hardcoded to true on init — it ignores localStorage, "
        "so enableClaudeAiAndReload() has no effect after reload"
    )

    # localStorage key must be read inside initDashboardSenpai() to restore the saved preference.
    # The function contains nested function declarations so we can't simply split on "function ";
    # instead grab everything from the function start up to the closing of the outer function.
    init_start = dash_js.index("function initDashboardSenpai()")
    init_block = dash_js[init_start:init_start + 12_000]
    assert "localStorage.getItem(SENPAI_MODE_KEY)" in init_block, (
        "initDashboardSenpai() must read SENPAI_MODE_KEY from localStorage "
        "to restore the mode after reload"
    )

    # The restored value must gate _forcedLocalMode (not "0" means claude mode)
    assert '!== "0"' in init_block, (
        "initDashboardSenpai() must set _forcedLocalMode = false "
        "when SENPAI_MODE_KEY is '0'"
    )

    # enableClaudeAiAndReload() must still write "0" to persist the claude preference
    enable_fn = dash_js.split("function enableClaudeAiAndReload()")[1].split("function ")[0]
    assert 'localStorage.setItem(SENPAI_MODE_KEY, "0")' in enable_fn, (
        "enableClaudeAiAndReload() must persist SENPAI_MODE_KEY='0' "
        "so the next load starts in Claude mode"
    )

    # applyForcedLocalMode must still write back when the user switches modes
    apply_fn = dash_js.split("function applyForcedLocalMode(")[1].split("function ")[0]
    assert "localStorage.setItem(SENPAI_MODE_KEY" in apply_fn, (
        "applyForcedLocalMode() must persist the new mode so it survives reload"
    )


def test_mode_toggle_button_structure():
    """The senpai-mode-toggle button and the local-intel-guide Enable button must both exist."""
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    dash_js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")

    # Nav toggle button — aria-pressed lives on the same element as the id
    assert 'id="senpai-mode-toggle"' in html
    # aria-pressed may appear before or after the id attribute within the same tag
    tag_end = html.index(">", html.index('id="senpai-mode-toggle"'))
    toggle_full = html[html.rindex("<button", 0, html.index('id="senpai-mode-toggle"')):tag_end]
    assert 'aria-pressed=' in toggle_full

    # Banner enable button
    assert 'id="local-intel-guide-enable"' in html

    # Both wired up in JS
    assert 'getElementById("senpai-mode-toggle")' in dash_js or '"senpai-mode-toggle"' in dash_js
    assert 'getElementById("local-intel-guide-enable")' in dash_js
