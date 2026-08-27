const test = require("node:test");
const assert = require("node:assert/strict");

const logic = require("../../static/js/holding-add-logic.js");

const request = { ticker: "VTI", shares: 0, avg_cost: null, is_watchlist: true };

test("reconciliation accepts only a row with the requested financial fields", () => {
    assert.equal(logic.resolveReconciliation({
        status: "confirmed",
        holding: { ticker: "VTI", shares: 0, avg_cost: 0, is_watchlist: true },
    }, request).status, "matching");

    for (const holding of [
        { ticker: "VTI", shares: 1, avg_cost: 0, is_watchlist: true },
        { ticker: "VTI", shares: 0, avg_cost: 1, is_watchlist: true },
        { ticker: "VTI", shares: 0, avg_cost: 0, is_watchlist: false },
        { ticker: "VOO", shares: 0, avg_cost: 0, is_watchlist: true },
    ]) {
        assert.equal(logic.resolveReconciliation({
            status: "confirmed",
            holding,
        }, request).status, "mismatch");
    }
});

test("absent and unknown reconciliation stay fail-closed", () => {
    assert.equal(logic.resolveReconciliation({ status: "absent" }, request).status, "absent");
    assert.equal(logic.resolveReconciliation({ status: "unknown" }, request).status, "unknown");
    assert.equal(logic.resolveReconciliation(null, request).status, "unknown");
});
