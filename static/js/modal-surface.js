/**
 * One definition of "modal" for every dialog FolioOrb paints.
 *
 * Eight surfaces declare `aria-modal="true"`, and before this module each had
 * answered the question "what does modal mean" differently. Measured on the
 * rendered dashboard, eight Tab presses from the rename dialog put six of them
 * on the page behind it, seven of eight from the *delete-portfolio*
 * confirmation, and two of eight from the record-a-sale dialog — a destructive
 * confirmation the keyboard could walk away from while it still stood open.
 *
 * A modal surface owns five things, and owning four of them is not a modal:
 *
 *   1. Tab containment — wrapping at both ends *and* pulling focus back when it
 *      starts outside, which is the case a naive first/last trap misses.
 *   2. An inert background, so assistive technology and the pointer agree with
 *      the keyboard about what is reachable.
 *   3. Escape, delegated to the caller's own close (each surface has its own
 *      idea of what closing means — see Review Orbit's pending restore).
 *   4. A focus return that is *checked*. `previousFocus.focus()` is a silent
 *      no-op once the element is gone, and the element is usually gone: the
 *      rename and delete flows both re-render the switcher row that owned the
 *      trigger, so the honest answer was `<body>` — focus lost at the top of
 *      the document, measured on both dialogs.
 *   5. A stack. Snapshotting `body > *` writes `inert` onto every *other*
 *      dialog's markup, so a modal opened over one already open would arrive
 *      unfocusable. `open()` skips surfaces below it on the stack and restores
 *      the one underneath when the top closes.
 *
 * Kept dependency-free and node-requireable, like interaction-state.js, so
 * tests/js/modal-surface.test.cjs can exercise the seam directly rather than
 * asserting on strings in a 14k-line file.
 */
(function exposeModalSurface(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    if (root) root.FolioModalSurface = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
    "use strict";

    const FOCUSABLE = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex='-1'])",
    ].join(", ");

    // Surfaces currently open, outermost first. The last entry owns the keyboard.
    const stack = [];

    /**
     * Visible, connected, and not buried in a subtree the user cannot reach.
     *
     * `getClientRects()` is the load-bearing check: `display: none`,
     * `visibility: hidden` and a detached node all report zero rects, and
     * v5.13.0 made `visibility: hidden` the way closed overlays leave the tab
     * order — so this one call covers every way a target can go stale.
     */
    function isRestorable(element) {
        if (!element || typeof element.focus !== "function") return false;
        if (element.isConnected === false) return false;
        if (element.disabled) return false;
        if (typeof element.closest === "function"
            && element.closest("[hidden], [aria-hidden='true'], [inert]")) return false;
        if (typeof element.getClientRects !== "function") return true;
        return element.getClientRects().length > 0;
    }

    /**
     * Focusable descendants of `root`, in document order, skipping hidden ones.
     *
     * `tabindex="-1"` is excluded whatever the tag, and that exclusion is what
     * makes the wrap fire at the right element. Every hand-rolled trap here
     * selected `button:not([disabled])` and so counted the *roving* tabs a
     * tablist parks at -1 — Review Orbit's six inactive tabs among them. The
     * browser skips those, so the trap's idea of "last" sat behind the real
     * one, the wrap never triggered, and one Tab per cycle fell out of the
     * surface onto <body>: a keyboard press that goes nowhere.
     */
    function focusableWithin(root) {
        if (!root || typeof root.querySelectorAll !== "function") return [];
        return Array.from(root.querySelectorAll(FOCUSABLE)).filter(element => (
            !element.hidden
            && element.getAttribute?.("tabindex") !== "-1"
            && (typeof element.closest !== "function" || !element.closest("[hidden]"))
            && (typeof element.getClientRects !== "function"
                || element.getClientRects().length > 0)
        ));
    }

    /**
     * Contain Tab inside `root`. Returns true when the event was handled.
     *
     * The third branch is the one hand-rolled traps kept omitting: focus can sit
     * outside the surface without ever having passed through `last` — a click on
     * the page behind, or a surface opened while the page had no focus at all —
     * and wrapping alone never brings it back.
     */
    function containTab(event, root, { getActive } = {}) {
        if (!event || event.key !== "Tab" || !root) return false;
        const active = (getActive || (() => root.ownerDocument?.activeElement))();
        const items = focusableWithin(root);
        if (!items.length) {
            event.preventDefault();
            root.focus?.();
            return true;
        }
        const first = items[0];
        const last = items[items.length - 1];
        const inside = typeof root.contains === "function" ? root.contains(active) : false;
        if (!inside) {
            event.preventDefault();
            (event.shiftKey ? last : first).focus();
            return true;
        }
        if (event.shiftKey && active === first) {
            event.preventDefault();
            last.focus();
            return true;
        }
        if (!event.shiftKey && active === last) {
            event.preventDefault();
            first.focus();
            return true;
        }
        return false;
    }

    /**
     * Mark everything outside `root` inert, remembering what it was before.
     *
     * `skip` carries the surfaces already open underneath, so their markup keeps
     * whatever `inert` their own open() gave it instead of being frozen at true
     * and left that way when this surface closes.
     */
    function setBackgroundInert(root, { document: doc, skip = [] } = {}) {
        const owner = doc || root?.ownerDocument;
        if (!owner || !root) return new Map();
        const previous = new Map();
        owner.querySelectorAll("body > *").forEach(element => {
            if (element === root || element.tagName === "SCRIPT") return;
            if (element.contains?.(root)) return;      // an ancestor of this surface
            if (skip.some(other => other === element || element.contains?.(other))) return;
            previous.set(element, element.inert);
            element.inert = true;
        });
        return previous;
    }

    function restoreBackgroundInert(previous) {
        previous?.forEach((wasInert, element) => { element.inert = wasInert; });
        previous?.clear?.();
    }

    /**
     * Thaw the branch this surface lives on, remembering what to freeze back.
     *
     * A surface already open has written `inert` across every *other* dialog's
     * markup, this one included — they were all just background at the time. So
     * a modal opened second arrives frozen: measured on the welcome guide, the
     * rename dialog opened over it could not be focused at all, and the guide's
     * own trap went on answering the keyboard. Skipping the surfaces below on
     * the stack is not enough, because that freeze already happened.
     */
    function thawBranch(root, doc) {
        const frozen = new Map();
        let node = root;
        while (node && node.parentElement && node.parentElement !== doc.body) {
            node = node.parentElement;
        }
        for (const element of new Set([root, node])) {
            if (element && element.inert) {
                frozen.set(element, true);
                element.inert = false;
            }
        }
        return frozen;
    }

    /**
     * Focus the first restorable candidate. Returns the element focused, or null.
     *
     * Callers pass the trigger first and a durable landmark after it — the nav
     * button that opens the surface, the tab that owns the pane — so a torn-down
     * trigger costs the user a short hop, never the whole document.
     *
     * Every candidate is confirmed *after* the call, because `focus()` reports
     * nothing when it fails and the most common stale trigger passes every
     * static check: `document.body` is connected, visible, and has a `focus`
     * method that does nothing. Taking its word for it left the keyboard at the
     * top of the document — the exact failure this function exists to prevent.
     */
    function restoreFocus(candidates) {
        for (const candidate of [].concat(candidates)) {
            const element = typeof candidate === "function" ? candidate() : candidate;
            if (!isRestorable(element)) continue;
            const owner = element.ownerDocument;
            if (owner && (element === owner.body || element === owner.documentElement)) continue;
            element.focus();
            if (!owner || owner.activeElement === element) return element;
        }
        return null;
    }

    /**
     * Open `root` as a modal surface and return a handle that closes it.
     *
     * `onEscape` runs instead of the default close when supplied — surfaces that
     * unwind an inner step first (Review Orbit's restore confirmation) return
     * false from it to keep the surface open.
     */
    function open(root, {
        document: doc,
        previousFocus,
        fallbackFocus = [],
        onEscape,
        initialFocus,
    } = {}) {
        const owner = doc || root?.ownerDocument;
        if (!root || !owner) return null;
        const existing = stack.find(entry => entry.root === root);
        if (existing) return existing.handle;

        const entry = {
            root,
            previousFocus: previousFocus === undefined
                ? owner.activeElement
                : previousFocus,
            fallbackFocus,
            background: setBackgroundInert(root, {
                document: owner,
                skip: stack.map(other => other.root),
            }),
            thawed: thawBranch(root, owner),
        };

        function onKeydown(event) {
            if (stack[stack.length - 1] !== entry) return;      // an inner surface owns it
            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                if (typeof onEscape === "function") {
                    if (onEscape(event) === false) return;
                    return;
                }
                entry.handle.close();
                return;
            }
            containTab(event, root, { getActive: () => owner.activeElement });
        }

        entry.onKeydown = onKeydown;
        entry.handle = {
            get isOpen() { return stack.includes(entry); },
            close() {
                const index = stack.indexOf(entry);
                if (index === -1) return null;
                stack.splice(index, 1);
                owner.removeEventListener("keydown", onKeydown, true);
                restoreBackgroundInert(entry.background);
                // Re-freeze last: the surface underneath still wants this one
                // out of the way, and its own close() will thaw it again.
                restoreBackgroundInert(entry.thawed);
                return restoreFocus([entry.previousFocus].concat(entry.fallbackFocus));
            },
        };

        stack.push(entry);
        owner.addEventListener("keydown", onKeydown, true);
        if (initialFocus) {
            const target = typeof initialFocus === "function" ? initialFocus() : initialFocus;
            target?.focus?.();
        }
        return entry.handle;
    }

    /** The surface that currently owns the keyboard, or null. */
    function top() {
        return stack.length ? stack[stack.length - 1].root : null;
    }

    return {
        FOCUSABLE,
        containTab,
        focusableWithin,
        isRestorable,
        open,
        restoreBackgroundInert,
        restoreFocus,
        setBackgroundInert,
        top,
        get depth() { return stack.length; },
    };
}));
