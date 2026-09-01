/** Pure request-contract helpers for truthful holding removal. */
(function exposeHoldingRemovalLogic(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    if (root) root.HoldingRemovalLogic = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
    "use strict";

    function buildPayload(details = {}) {
        const payload = {};
        if (details.sale_date) payload.sale_date = details.sale_date;
        const price = Number(details.sale_price);
        if (Number.isFinite(price) && price > 0) {
            payload.sale_price = price;
            payload.sale_currency = "USD";
            payload.sale_price_source = "manual_entry";
        }
        return payload;
    }

    function requiresExplicitPrice(status, body) {
        return status === 409 && body?.detail?.code === "sale_price_required";
    }

    return { buildPayload, requiresExplicitPrice };
}));
