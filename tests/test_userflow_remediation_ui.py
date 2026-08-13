"""Regression contracts for the v5.9.3 through v5.10.2 user-flow remediations."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates/index.html").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
DCA = (ROOT / "static/js/dca-workflow.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
REVIEW_STYLE = (ROOT / "static/css/review-orbit.css").read_text(encoding="utf-8")


def _function(name: str, next_name: str, source: str = DASHBOARD) -> str:
    start = source.index(f"function {name}(")
    end = source.index(f"function {next_name}(", start)
    return source[start:end]


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


def test_mobile_holdings_toolbar_does_not_keep_desktop_flex_basis():
    mobile = STYLE[STYLE.index("@media (max-width: 575.98px)"):]
    toolbar = mobile[mobile.index(".holdings-card-toolbar"):]
    toolbar = toolbar[:toolbar.index("}")]
    assert "flex: 0 1 auto" in toolbar


def test_mobile_review_tabs_wrap_so_every_destination_is_visible():
    mobile = REVIEW_STYLE[REVIEW_STYLE.index("@media (max-width: 575.98px)"):]
    tabs = mobile[mobile.index(".review-orbit-tabs"):]
    tabs = tabs[:tabs.index("}")]
    assert "flex-wrap: wrap" in tabs
    assert "overflow-x: visible" in tabs


def test_welcome_guide_opens_at_the_top_with_close_focused():
    show = DASHBOARD[DASHBOARD.index("function maybeShowSenpaiWelcomeGuide"):]
    show = show[:show.index("\n}\n")]
    assert "body.scrollTop = 0" in show
    assert 'document.getElementById("senpai-welcome-dismiss")' in show
    assert 'document.getElementById("senpai-welcome-add-holding")' not in show


def test_dca_bulk_and_plan_actions_use_the_in_app_dialog():
    for marker in (
        'id="dca-action-dialog"',
        'id="dca-action-form"',
        'id="dca-action-input"',
        'id="dca-action-cancel"',
        'id="dca-action-submit"',
        'role="dialog"',
        'aria-modal="true"',
    ):
        assert marker in INDEX

    for action in ("apply-all", "undo-all", "skip-all", "edit-plan", "delete-plan"):
        assert f'action === "{action}"' in DCA
    body = _function("handleAction", "hideBackfillConfirm", DCA)
    assert "openDialog" in body
    assert "window.confirm" not in body
    assert "window.prompt" not in body
    assert 'data-dca-action="apply-all"' in DCA


def test_dca_action_dialog_traps_focus_and_restores_the_manager():
    assert "function handleDialogKeydown" in DCA
    assert 'event.key === "Escape"' in _function(
        "handleDialogKeydown", "initDialog", DCA
    )
    assert "event.shiftKey && document.activeElement === first" in DCA
    assert "!event.shiftKey && document.activeElement === last" in DCA
    assert 'setAttribute("inert", "")' in DCA
    assert 'removeAttribute("inert")' in DCA
    assert "state.previousFocus.focus()" in DCA


def test_dca_delete_explains_and_surfaces_applied_buy_conflicts():
    delete = _function("handleAction", "hideBackfillConfirm", DCA)
    assert "Undo every applied buy before deleting this plan" in delete
    assert 'typeof data.detail === "string" ? data.detail' in delete
    assert "if (!response.ok)" in delete
    assert 'notify(`${ticker} plan deleted`, "success")' in delete
