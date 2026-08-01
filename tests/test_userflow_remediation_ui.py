"""Regression contracts for the v5.9.3 user-flow remediation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates/index.html").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static/css/style.css").read_text(encoding="utf-8")


def test_holding_rows_expose_a_native_keyboard_disclosure():
    assert 'class="holding-disclosure-btn"' in DASHBOARD
    assert 'aria-expanded="false"' in DASHBOARD
    assert 'aria-controls="${holdingDetailsId(h.ticker)}"' in DASHBOARD
    assert "function setHoldingSummaryExpanded" in DASHBOARD
    assert 'expandRow.setAttribute("aria-hidden", String(!expanded))' in DASHBOARD
    assert "expandRow.hidden = true" in DASHBOARD
    assert ".holding-disclosure-btn:focus-visible" in STYLE


def test_holding_intelligence_queries_are_scoped_to_the_holdings_table():
    assert "function holdingTableRow" in DASHBOARD
    assert 'getElementById("holdings-table")' in DASHBOARD
    assert "const mainRow = holdingTableRow(ticker)" in DASHBOARD
    assert "const row = holdingTableRow(normalized)" in DASHBOARD


def test_news_failure_is_retryable_without_a_page_reload():
    assert 'id="news-retry-btn"' in INDEX
    assert 'id="news-retry-status"' in INDEX
    assert "function retryNewsZone" in DASHBOARD
    assert "let feedLoaded = false" in DASHBOARD
    assert "_newsLoaded = feedLoaded" in DASHBOARD
    assert "ensureNewsLoaded({ force: true })" in DASHBOARD
    assert ".news-retry-btn" in STYLE


def test_portfolio_manager_focus_return_rejects_hidden_openers():
    assert 'aria-label="Manage portfolios"' in INDEX
    assert "function isRestorableFocusTarget" in DASHBOARD
    assert "[hidden], [aria-hidden='true'], [inert]" in DASHBOARD
    assert 'getElementById("portfolio-manager-trigger")' in DASHBOARD
    close = DASHBOARD.split("function closePortfolioManager", 1)[1][:1200]
    assert "isRestorableFocusTarget(previousFocus)" in close
    assert "fallbackFocus" in close


def test_shared_tip_pattern_names_icon_only_controls_and_dynamic_triggers():
    assert "function applyTipTriggerA11y" in DASHBOARD
    assert "`About ${title}`" in DASHBOARD
    assert 'icon.setAttribute("aria-hidden", "true")' in DASHBOARD
    assert "new MutationObserver" in DASHBOARD
    assert "applyTipTriggerA11y(document.body)" in DASHBOARD


def test_action_plan_header_stacks_on_phone_widths():
    phone = STYLE.split("@media (max-width: 520px)", 1)[1].split("}", 3)
    combined = "}".join(phone)
    assert ".ap-header" in combined
    assert "flex-direction: column" in combined
    assert ".ap-meta-stack" in combined
    assert "flex-direction: row" in combined
    assert "width: 100%" in combined


def test_phone_nav_controls_keep_names_when_visible_labels_hide():
    assert 'aria-label="Open Review Orbit"' in INDEX
    assert 'aria-label="Manage portfolios"' in INDEX
