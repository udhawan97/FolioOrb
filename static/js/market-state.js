/**
 * World-market availability is a data contract, not a truthiness guess.
 */
(function exposeMarketState(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    if (root) root.FolioMarketState = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
    "use strict";

    function isAvailable(row) {
        return row?.available === true
            && Number.isFinite(row.price)
            && row.price > 0
            && Number.isFinite(row.day_change)
            && Number.isFinite(row.day_change_pct);
    }

    function direction(row) {
        if (!isAvailable(row)) return null;
        if (row.day_change_pct > 0) return "up";
        if (row.day_change_pct < 0) return "down";
        return "flat";
    }

    function availableRows(rows) {
        return Array.isArray(rows) ? rows.filter(isAvailable) : [];
    }

    function cachePayloadIsUsable(rows) {
        if (!Array.isArray(rows) || !rows.length) return false;
        return rows.every(row => {
            const metadataIsPresent = row
                && typeof row.ticker === "string"
                && typeof row.region === "string"
                && typeof row.name === "string"
                && typeof row.available === "boolean";
            if (!metadataIsPresent) return false;
            if (row.available) return isAvailable(row);
            return row.price === null
                && row.day_change === null
                && row.day_change_pct === null;
        });
    }

    return { availableRows, cachePayloadIsUsable, direction, isAvailable };
}));
