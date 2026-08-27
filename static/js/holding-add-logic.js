(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    if (root) root.HoldingAddLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    function finiteNumber(value) {
        const number = Number(value ?? 0);
        return Number.isFinite(number) ? number : null;
    }

    function holdingMatchesRequest(holding, request) {
        if (!holding || !request) return false;
        const actualShares = finiteNumber(holding.shares);
        const expectedShares = finiteNumber(request.shares);
        const actualCost = finiteNumber(holding.avg_cost);
        const expectedCost = finiteNumber(request.avg_cost);
        return String(holding.ticker || "").toUpperCase() === String(request.ticker || "").toUpperCase()
            && actualShares !== null
            && expectedShares !== null
            && Math.abs(actualShares - expectedShares) < 1e-9
            && actualCost !== null
            && expectedCost !== null
            && Math.abs(actualCost - expectedCost) < 1e-9
            && Boolean(holding.is_watchlist) === Boolean(request.is_watchlist);
    }

    function resolveReconciliation(lookup, request) {
        if (lookup?.status === "absent") return { status: "absent", holding: null };
        if (lookup?.status !== "confirmed") return { status: "unknown", holding: null };
        return {
            status: holdingMatchesRequest(lookup.holding, request) ? "matching" : "mismatch",
            holding: lookup.holding || null,
        };
    }

    return { holdingMatchesRequest, resolveReconciliation };
});
