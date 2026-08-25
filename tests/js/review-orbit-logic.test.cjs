const test = require("node:test");
const assert = require("node:assert/strict");

const logic = require("../../static/js/review-orbit-logic.js");

function memoryStorage(entries = {}) {
    const values = new Map(Object.entries(entries));
    return {
        getItem: key => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, String(value)),
        value: key => values.get(key),
    };
}

test("continuity restores only allowlisted values and persists valid changes", () => {
    const storage = memoryStorage({ tab: "trust", period: "year" });
    assert.equal(logic.readChoice(storage, "tab", new Set(["inbox", "trust"]), "inbox"), "trust");
    assert.equal(logic.readChoice(storage, "period", new Set(["month", "quarter"]), "month"), "month");

    logic.writeChoice(storage, "period", "quarter");
    assert.equal(storage.value("period"), "quarter");
});

test("continuity falls back when local storage is inaccessible", () => {
    const blocked = {
        getItem: () => { throw new Error("blocked"); },
        setItem: () => { throw new Error("blocked"); },
    };
    assert.equal(logic.readChoice(blocked, "tab", new Set(["inbox"]), "inbox"), "inbox");
    assert.doesNotThrow(() => logic.writeChoice(blocked, "tab", "inbox"));
});

test("inbox filtering changes visibility without changing the source list", () => {
    const items = [
        { id: "gap", tone: "urgent" },
        { id: "thesis", tone: "attention" },
        { id: "earnings", tone: "quiet" },
    ];
    assert.deepEqual(logic.filterInbox(items, "attention").map(item => item.id), ["thesis"]);
    assert.equal(logic.filterInbox(items, "all").length, 3);
    assert.equal(items.length, 3);
    assert.equal(logic.filterAnnouncement("attention"), "items needing review");
});

test("filter focus moves to the replacement button after rerender", () => {
    let focused = false;
    let selector = "";
    const replacement = { focus: () => { focused = true; } };
    const root = {
        querySelector: value => {
            selector = value;
            return replacement;
        },
    };

    assert.equal(logic.restoreFilterFocus(root, "attention"), replacement);
    assert.equal(selector, '[data-inbox-filter="attention"]');
    assert.equal(focused, true);
    assert.equal(logic.restoreFilterFocus(root, "invalid"), null);
});

test("review period labels match restored month and quarter state", () => {
    assert.equal(logic.reportTitle("month"), "Monthly review pack");
    assert.equal(logic.reportTitle("quarter"), "Quarterly review pack");
    assert.equal(logic.reportTitle("invalid"), "Monthly review pack");
});

test("plan export detects a visible draft and clears when values match saved targets", () => {
    const saved = [
        { holding_id: 1, target_weight_bps: 6000 },
        { holding_id: 2, target_weight_bps: null },
    ];
    assert.equal(logic.targetCourseDirty(saved, [
        { holdingId: "1", value: "6000" },
        { holdingId: "2", value: "" },
    ]), false);
    assert.equal(logic.targetCourseDirty(saved, [
        { holdingId: "1", value: "5500" },
        { holdingId: "2", value: "" },
    ]), true);
});
