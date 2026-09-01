const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const logic = require("../../static/js/holding-removal-logic.js");

function localDateIn(timeZone, instant) {
  const modulePath = path.resolve(__dirname, "../../static/js/holding-removal-logic.js");
  const script = `
    const logic = require(${JSON.stringify(modulePath)});
    process.stdout.write(logic.localCalendarDate(new Date(${JSON.stringify(instant)})));
  `;
  const result = spawnSync(process.execPath, ["-e", script], {
    encoding: "utf8",
    env: { ...process.env, TZ: timeZone },
  });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
}

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

test("sale dates follow the local calendar on both sides of UTC rollover", () => {
  const earlyUtc = "2026-09-01T01:30:00.000Z";
  assert.equal(localDateIn("America/Chicago", earlyUtc), "2026-08-31");
  assert.equal(localDateIn("UTC", earlyUtc), "2026-09-01");

  const lateUtc = "2026-08-31T23:30:00.000Z";
  assert.equal(localDateIn("Asia/Tokyo", lateUtc), "2026-09-01");
  assert.equal(localDateIn("UTC", lateUtc), "2026-08-31");
});
