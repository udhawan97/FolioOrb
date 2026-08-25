"use strict";

(function exposeReviewOrbitLogic(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    if (root) root.ReviewOrbitLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
    const INBOX_FILTERS = new Set(["all", "urgent", "attention", "quiet"]);

    function readChoice(storage, key, allowed, fallback) {
        try {
            const value = storage.getItem(key);
            return allowed.has(value) ? value : fallback;
        } catch (_) {
            return fallback;
        }
    }

    function writeChoice(storage, key, value) {
        try {
            storage.setItem(key, value);
        } catch (_) {
            // Continuity is best-effort; the workflow remains usable without storage.
        }
    }

    function filterInbox(items, tone) {
        const source = Array.isArray(items) ? items : [];
        if (tone === "all" || !INBOX_FILTERS.has(tone)) return source;
        return source.filter(item => item.tone === tone);
    }

    function filterAnnouncement(tone) {
        return {
            all: "all items",
            urgent: "data gaps",
            attention: "items needing review",
            quiet: "items on the radar",
        }[tone] || "all items";
    }

    function restoreFilterFocus(root, tone) {
        if (!root || !INBOX_FILTERS.has(tone)) return null;
        const button = root.querySelector(`[data-inbox-filter="${tone}"]`);
        if (!button || typeof button.focus !== "function") return null;
        button.focus();
        return button;
    }

    function reportTitle(period) {
        return period === "quarter" ? "Quarterly review pack" : "Monthly review pack";
    }

    function targetCourseDirty(savedItems, currentInputs) {
        const saved = new Map((savedItems || []).map(item => [
            String(item.holding_id),
            item.target_weight_bps === null || item.target_weight_bps === undefined
                ? ""
                : String(item.target_weight_bps),
        ]));
        return (currentInputs || []).some(input => (
            String(input.value ?? "").trim()
                !== (saved.get(String(input.holdingId)) ?? "")
        ));
    }

    return {
        readChoice,
        writeChoice,
        filterInbox,
        filterAnnouncement,
        restoreFilterFocus,
        reportTitle,
        targetCourseDirty,
    };
});
