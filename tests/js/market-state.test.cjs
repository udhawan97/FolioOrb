const test = require("node:test");
const assert = require("node:assert/strict");

const state = require("../../static/js/market-state.js");

function row(overrides = {}) {
  return {
    ticker: "^GSPC",
    name: "S&P 500",
    region: "US",
    available: true,
    price: 100,
    day_change: 0,
    day_change_pct: 0,
    ...overrides,
  };
}

test("a genuine flat quote remains available and neutral", () => {
  const flat = row();
  assert.equal(state.isAvailable(flat), true);
  assert.equal(state.direction(flat), "flat");
  assert.deepEqual(state.availableRows([flat]), [flat]);
});

test("an unavailable row has no direction and is excluded independently", () => {
  const unavailable = row({
    ticker: "^N225",
    available: false,
    price: null,
    day_change: null,
    day_change_pct: null,
  });
  const down = row({ ticker: "^GSPC", day_change: -1, day_change_pct: -1 });

  assert.equal(state.direction(unavailable), null);
  assert.equal(state.direction(down), "down");
  assert.deepEqual(state.availableRows([unavailable, down]), [down]);
});

test("cache validation accepts the explicit mixed contract and rejects old sentinels", () => {
  const unavailable = row({
    available: false,
    price: null,
    day_change: null,
    day_change_pct: null,
  });
  assert.equal(state.cachePayloadIsUsable([unavailable, row()]), true);
  assert.equal(state.cachePayloadIsUsable([{
    ...unavailable,
    available: undefined,
    price: 0,
    day_change: 0,
    day_change_pct: 0,
  }]), false);
});
