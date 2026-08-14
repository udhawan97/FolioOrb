"""Regression contracts for the five verified user-flow audit gaps."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INTERACTION = (ROOT / "static" / "js" / "interaction-state.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
REVIEW = (ROOT / "static" / "js" / "review-orbit.js").read_text(encoding="utf-8")
REVIEW_STYLE = (ROOT / "static" / "css" / "review-orbit.css").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
API_KEY_STORE = (ROOT / "app" / "services" / "api_key_store.py").read_text(
    encoding="utf-8"
)
CAPTURE = (ROOT / "docs-site" / "scripts" / "capture.sh").read_text(encoding="utf-8")
CAPTURE_SHOTS = (ROOT / "docs-site" / "scripts" / "capture_shots.mjs").read_text(
    encoding="utf-8"
)
CAPTURE_HERO = (ROOT / "docs-site" / "scripts" / "capture_v3.mjs").read_text(
    encoding="utf-8"
)
ARCHITECTURE = (
    ROOT / "docs-site" / "src" / "content" / "docs" / "architecture.mdx"
).read_text(encoding="utf-8")
LANDING = (ROOT / "docs-site" / "src" / "pages" / "index.astro").read_text(
    encoding="utf-8"
)
PRIVACY = (ROOT / "docs-site" / "src" / "content" / "docs" / "privacy.md").read_text(
    encoding="utf-8"
)
CLAUDE_SETUP = (
    ROOT / "docs-site" / "src" / "content" / "docs" / "get-started" / "claude-setup.md"
).read_text(encoding="utf-8")


def _tag(element_id: str) -> str:
    match = re.search(rf"<[^>]+\bid=\"{re.escape(element_id)}\"[^>]*>", INDEX, re.S)
    assert match, f"#{element_id} is missing"
    return match.group(0)


def test_closed_header_popovers_start_inert_and_hidden_from_accessibility_tree():
    for element_id in (
        "brand-intro-callout",
        "api-key-panel",
        "hud-popover",
        "nav-overflow-menu",
        "brand-cost-callout",
    ):
        tag = _tag(element_id)
        assert " inert" in tag, f"#{element_id} can still receive focus while closed"
        assert 'aria-hidden="true"' in tag


def test_header_popovers_share_one_focus_exclusion_contract():
    helper = INTERACTION[INTERACTION.index("function setDisclosureState"):]
    helper = helper[:helper.index("\n    }")]
    assert "panel.inert = !open" in helper
    assert 'panel.setAttribute("aria-hidden", String(!open))' in helper
    assert 'trigger?.setAttribute("aria-expanded", String(open))' in helper
    assert INDEX.index("/static/js/interaction-state.js") < INDEX.index("/static/js/dashboard.js")
    assert "closeDisclosureForEscape" in DASHBOARD
    for fragment in (
        'setHeaderPopoverState(trigger, callout, true, "is-visible")',
        'setHeaderPopoverState(trigger, menu, true, "is-visible")',
        'setHeaderPopoverState(pill, popover, true, "is-visible")',
        'setHeaderPopoverState(trigger, panel, true, "is-open")',
    ):
        assert fragment in DASHBOARD
    brand_intro = DASHBOARD[
        DASHBOARD.index("function initBrandIntro"):DASHBOARD.index(
            'document.addEventListener("DOMContentLoaded"'
        )
    ]
    assert "hideIntro({ restoreFocus: true })" in brand_intro
    api_panel = DASHBOARD[
        DASHBOARD.index("function initApiKeyPanel"):
        DASHBOARD.index("function renderSenpaiWelcomeHoldModes")
    ]
    assert "if (restoreFocus) trigger.focus();" in api_panel
    assert "setTimeout(() => closePanel({ restoreFocus: true }), 1400)" in api_panel


def test_mobile_senpai_reflows_after_content_and_auto_activity_stays_compact():
    assert "Mobile: Senpai joins the document flow" in STYLE
    assert "body > .dashboard-senpai.is-expanded .dashboard-senpai-bubble" in STYLE
    assert "position: relative" in STYLE[STYLE.index("Mobile: Senpai joins the document flow"):]
    assert (
        "body > .dashboard-senpai.is-texting:not(.is-hidden) .dashboard-senpai-bubble"
        not in STYLE
    )
    assert "syncSenpaiDisclosure()" in DASHBOARD
    assert '"Collapse Senpai message"' in DASHBOARD


def test_mobile_plan_contains_its_minimum_width_inside_the_table_scroller():
    plan = REVIEW_STYLE[REVIEW_STYLE.index(".review-plan-grid"):]
    plan = plan[:plan.index(".review-course-summary")]
    assert "min-width: 0" in plan
    cards = REVIEW_STYLE[REVIEW_STYLE.index(".review-course-card,"):]
    assert "min-width: 0" in cards[:cards.index(".review-course-summary")]
    table_scroll = REVIEW_STYLE[REVIEW_STYLE.index(".review-table-scroll"):]
    assert "min-width: 0" in table_scroll[:table_scroll.index("}")]


def test_escape_cancels_restore_confirmation_before_closing_review_orbit():
    keydown = REVIEW[REVIEW.index("function onKeydown"):REVIEW.index("function setBackgroundInert")]
    assert keydown.index("restoreConfirmation.selection") < keydown.index("close();")
    assert keydown.index("restoreConfirmation.pending") < keydown.index("cancelRestore();")
    assert "cancelRestore();" in keydown
    close = REVIEW[REVIEW.index("function close()"):REVIEW.index("function activateTab")]
    assert "clearRestoreConfirmation({ restoreFocus: false })" in close


def test_pending_restore_disables_cancel_and_close_until_the_request_finishes():
    accept = REVIEW[
        REVIEW.index("async function acceptRestore"):REVIEW.index("function openThesisEditor")
    ]
    assert accept.index("restoreConfirmation.start()") < accept.index("await PortfolioWorkspace")
    assert "setRestorePendingUi(true, name)" in accept
    assert "restoreConfirmation.fail()" in accept
    assert "Number.isInteger(error?.status)" in accept
    assert "reconcileRestoreAfterUnknownResponse(name)" in accept
    assert 'cancel.disabled = pending' in REVIEW
    assert 'button.disabled = pending' in REVIEW
    assert 'confirm?.setAttribute("aria-busy", String(pending && !unknown))' in REVIEW


def test_interrupted_restore_response_never_claims_cancellation_without_status():
    reconcile = REVIEW[
        REVIEW.index("async function reconcileRestoreAfterUnknownResponse"):
        REVIEW.index("async function acceptRestore")
    ]
    assert 'PortfolioWorkspace.json("/api/review/backups")' in reconcile
    assert "backups.pending_restore?.name === name" in reconcile
    assert "Restore was not queued; the status check found no pending restore." in reconcile
    assert "Could not confirm whether the restore was queued." in reconcile
    assert 'setRestorePendingUi(true, name, { unknown: true })' in reconcile
    assert "Status unknown" in REVIEW
    assert "Reload FolioOrb, reopen Backup Vault" in REVIEW
    assert "pending_restore" in REVIEW[REVIEW.index("function renderBackups"):]


def test_public_privacy_and_claude_setup_copy_names_real_outbound_paths():
    assert "key icon beside the FolioOrb brand" in CLAUDE_SETUP
    assert "Click the brand mark" not in CLAUDE_SETUP
    assert "credentialed model-list request" in PRIVACY
    assert "News thumbnail hosts" in PRIVACY
    assert "ETF profile fallback" in PRIVACY
    assert "completion narration" in PRIVACY
    assert "requires an app restart" in PRIVACY
    assert "restart FolioOrb" in CLAUDE_SETUP
    assert 'referrerpolicy="no-referrer"' in DASHBOARD
    assert "reports to nobody" not in README
    release_notes = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert re.search(r"reports\s+to\s+nobody", release_notes, re.I) is None
    assert (
        re.search(
            r"all\s+local\s+intelligence\s+works\s+offline", release_notes, re.I
        )
        is None
    )
    assert "fully offline" not in ARCHITECTURE
    assert "against the live API before it is persisted" not in ARCHITECTURE
    assert "reports connected only after a live heartbeat succeeds" in ARCHITECTURE
    assert "No cloud calls" not in DASHBOARD
    assert "Your data never left the building" not in LANDING
    assert "computed on-device" not in LANDING
    assert "computed and cached locally" not in LANDING
    assert "Public quotes, history, headlines, and indices are fetched on demand" in LANDING
    assert "key never leaves the user's machine" not in API_KEY_STORE


def test_canonical_capture_owns_its_process_and_uses_only_disposable_data():
    assert 'mktemp -d "$TMP_PARENT/folioorb-shots.XXXXXX"' in CAPTURE
    assert 'export FOLIOORB_DATA_DIR="$TMP_DIR/data"' in CAPTURE
    assert 'FOLIOORB_CAPTURE_TOKEN=' in CAPTURE
    assert "export FOLIOORB_CAPTURE_TOKEN" in CAPTURE
    assert 'kill -0 "$APP_PID"' in CAPTURE
    assert '"$OBSERVED_TOKEN" == "$FOLIOORB_CAPTURE_TOKEN"' in CAPTURE
    assert "refusing to use another process" in CAPTURE
    assert 'os.getenv("FOLIOORB_CAPTURE_TOKEN"' in MAIN
    assert "#dashboard-senpai { display: none !important; }" in CAPTURE_SHOTS
    assert "dashboard-senpai" in CAPTURE_HERO


def test_rehearsal_preview_is_bound_to_inputs_and_ignores_stale_responses():
    assert "function currentRehearsalSnapshot" in REVIEW
    assert "state.rehearsalRequestId" in REVIEW
    assert "requestId !== state.rehearsalRequestId" in REVIEW
    run_rehearsal = REVIEW[
        REVIEW.index("async function runRehearsal"):REVIEW.index("async function saveRecap")
    ]
    assert run_rehearsal.index("requestId !== state.rehearsalRequestId") < run_rehearsal.index(
        "!sameRehearsalSnapshot(snapshot, currentRehearsalSnapshot())"
    )
    assert 'rehearsalForm?.addEventListener("input", invalidateRehearsal)' in REVIEW
    assert 'rehearsalForm?.addEventListener("change", invalidateRehearsal)' in REVIEW
    assert "Preview outdated" in REVIEW
    assert ".review-rehearsal-outdated" in REVIEW_STYLE
