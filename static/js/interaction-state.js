/**
 * Small, testable interaction-state seams shared by dashboard disclosures and
 * Review Orbit's restore confirmation.
 */
(function exposeInteractionState(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    if (root) root.FolioInteractionState = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
    "use strict";

    function setDisclosureState(trigger, panel, open, openClass) {
        if (!panel) return;
        panel.classList.toggle(openClass, open);
        panel.inert = !open;
        panel.setAttribute("aria-hidden", String(!open));
        trigger?.setAttribute("aria-expanded", String(open));
    }

    function restoreDisclosureFocus(focusTarget, {
        parentTrigger = null,
        parentPanel = null,
        parentOpenClass = "is-visible",
    } = {}) {
        if (parentPanel && (
            parentPanel.inert || !parentPanel.classList.contains(parentOpenClass)
        )) {
            setDisclosureState(parentTrigger, parentPanel, true, parentOpenClass);
        }
        if (!focusTarget?.focus) return false;
        focusTarget.focus();
        return true;
    }

    function closeDisclosureForEscape(event, {
        panel,
        openClass,
        close,
        focusTarget,
        parentTrigger = null,
        parentPanel = null,
        parentOpenClass = "is-visible",
    }) {
        if (event.key !== "Escape" || !panel?.classList.contains(openClass)) return false;
        event.preventDefault();
        event.stopImmediatePropagation();
        close();
        restoreDisclosureFocus(focusTarget, {
            parentTrigger,
            parentPanel,
            parentOpenClass,
        });
        return true;
    }

    function createPendingConfirmation() {
        let selection = null;
        let pending = false;

        return {
            select(value) {
                selection = value || null;
                pending = false;
                return selection;
            },
            start() {
                if (!selection || pending) return null;
                pending = true;
                return selection;
            },
            cancel() {
                if (pending) return false;
                selection = null;
                return true;
            },
            fail() {
                pending = false;
            },
            clear() {
                selection = null;
                pending = false;
            },
            get selection() { return selection; },
            get pending() { return pending; },
        };
    }

    return {
        closeDisclosureForEscape,
        createPendingConfirmation,
        restoreDisclosureFocus,
        setDisclosureState,
    };
}));
