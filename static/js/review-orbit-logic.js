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

    function reviewBundleFilename(period, periodEnd, portfolioId) {
        const safePeriod = period === "quarter" ? "quarter" : "month";
        const safeDate = /^\d{4}-\d{2}-\d{2}$/.test(String(periodEnd || ""))
            ? periodEnd
            : "current";
        const numericId = Number(portfolioId);
        const safeId = Number.isInteger(numericId) && numericId > 0 ? numericId : 1;
        return `folioorb-${safePeriod}-review-bundle-${safeDate}-p${safeId}.zip`;
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

    function refreshOutcome(name, succeeded, total = 1) {
        const safeTotal = Math.max(1, Number(total) || 1);
        const safeSucceeded = Math.max(0, Math.min(safeTotal, Number(succeeded) || 0));
        const status = safeSucceeded === safeTotal
            ? "complete"
            : safeSucceeded > 0 ? "partial" : "failed";
        return { name, status, succeeded: safeSucceeded, total: safeTotal };
    }

    function summarizeRefresh(outcomes) {
        const results = Array.isArray(outcomes) ? outcomes : [];
        const total = results.reduce((sum, outcome) => sum + (Number(outcome?.total) || 0), 0);
        const succeeded = results.reduce(
            (sum, outcome) => sum + (Number(outcome?.succeeded) || 0),
            0,
        );
        if (total > 0 && succeeded === total) {
            return { status: "complete", message: "Review Orbit refresh complete." };
        }
        if (succeeded > 0) {
            return {
                status: "partial",
                message: "Review Orbit refresh partially complete. Unavailable updates remain retryable.",
            };
        }
        return {
            status: "failed",
            message: "Review Orbit refresh failed. Last successful data is marked stale where available.",
        };
    }

    function planStaleDetail({ hadUnsavedDraft = false, savedDraftAwaitingRefresh = false } = {}) {
        if (savedDraftAwaitingRefresh) {
            return "Target edits were saved locally, but the saved Plan could not be read back. The visible edits are saved but unrefreshed.";
        }
        if (hadUnsavedDraft) {
            return "The last saved Plan remains visible. Unsaved target edits are still local and have not been saved or refreshed.";
        }
        return "Showing the last saved Plan snapshot.";
    }

    return {
        readChoice,
        writeChoice,
        filterInbox,
        filterAnnouncement,
        restoreFilterFocus,
        reportTitle,
        reviewBundleFilename,
        targetCourseDirty,
        refreshOutcome,
        summarizeRefresh,
        planStaleDetail,
    };
});
