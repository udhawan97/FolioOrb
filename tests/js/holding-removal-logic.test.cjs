const test = require("node:test");
const assert = require("node:assert/strict");

const logic = require("../../static/js/holding-removal-logic.js");

test("an automatic removal request carries no invented price provenance", () => {
  assert.deepEqual(logic.buildPayload({ sale_price: null, sale_date: "2026-01-15" }), {
    sale_date: "2026-01-15",
  });
});

test("an entered price always emits the locked USD manual provenance trio", () => {
  assert.deepEqual(logic.buildPayload({ sale_price: "123.45", sale_date: "2026-01-15" }), {
    sale_date: "2026-01-15",
    sale_price: 123.45,
    sale_currency: "USD",
    sale_price_source: "manual_entry",
  });
});

test("only the structured pricing conflict requests an explicit retry", () => {
  const body = { detail: { code: "sale_price_required" } };
  assert.equal(logic.requiresExplicitPrice(409, body), true);
  assert.equal(logic.requiresExplicitPrice(500, body), false);
  assert.equal(logic.requiresExplicitPrice(409, { detail: "failed" }), false);
});
