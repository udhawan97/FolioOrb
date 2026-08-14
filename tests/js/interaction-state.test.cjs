const test = require("node:test");
const assert = require("node:assert/strict");

const {
  closeDisclosureForEscape,
  createPendingConfirmation,
  setDisclosureState,
} = require("../../static/js/interaction-state.js");

function fakeElement(classes = []) {
  const values = new Set(classes);
  const attrs = new Map();
  return {
    inert: false,
    focused: false,
    classList: {
      contains: value => values.has(value),
      toggle(value, force) {
        if (force) values.add(value);
        else values.delete(value);
      },
    },
    focus() { this.focused = true; },
    getAttribute(name) { return attrs.get(name); },
    setAttribute(name, value) { attrs.set(name, String(value)); },
  };
}

function escapeEvent() {
  return {
    key: "Escape",
    prevented: false,
    stopped: false,
    preventDefault() { this.prevented = true; },
    stopImmediatePropagation() { this.stopped = true; },
  };
}

test("closed disclosures synchronize visual, inert, and ARIA state", () => {
  const trigger = fakeElement();
  const panel = fakeElement(["is-visible"]);

  setDisclosureState(trigger, panel, false, "is-visible");

  assert.equal(panel.classList.contains("is-visible"), false);
  assert.equal(panel.inert, true);
  assert.equal(panel.getAttribute("aria-hidden"), "true");
  assert.equal(trigger.getAttribute("aria-expanded"), "false");
});

test("Escape closes AI Cost only and focuses its trigger in the open parent menu", () => {
  const event = escapeEvent();
  const menuTrigger = fakeElement();
  const menu = fakeElement(["is-visible"]);
  const costTrigger = fakeElement();
  const cost = fakeElement(["is-visible"]);

  const handled = closeDisclosureForEscape(event, {
    panel: cost,
    openClass: "is-visible",
    close: () => setDisclosureState(costTrigger, cost, false, "is-visible"),
    focusTarget: costTrigger,
    parentTrigger: menuTrigger,
    parentPanel: menu,
  });

  assert.equal(handled, true);
  assert.equal(event.prevented, true);
  assert.equal(event.stopped, true);
  assert.equal(cost.inert, true);
  assert.equal(menu.inert, false);
  assert.equal(menu.classList.contains("is-visible"), true);
  assert.equal(costTrigger.focused, true);
});

test("Escape from mobile Live Feed reopens More before focusing the nested trigger", () => {
  const event = escapeEvent();
  const menuTrigger = fakeElement();
  const menu = fakeElement();
  const liveFeedTrigger = fakeElement();
  const liveFeed = fakeElement(["is-visible"]);
  menu.inert = true;

  closeDisclosureForEscape(event, {
    panel: liveFeed,
    openClass: "is-visible",
    close: () => setDisclosureState(null, liveFeed, false, "is-visible"),
    focusTarget: liveFeedTrigger,
    parentTrigger: menuTrigger,
    parentPanel: menu,
  });

  assert.equal(menu.classList.contains("is-visible"), true);
  assert.equal(menu.inert, false);
  assert.equal(menuTrigger.getAttribute("aria-expanded"), "true");
  assert.equal(liveFeedTrigger.focused, true);
});

test("a pending restore cannot be cancelled but a failed request can", () => {
  const confirmation = createPendingConfirmation();
  confirmation.select("folioorb-backup.db");

  assert.equal(confirmation.start(), "folioorb-backup.db");
  assert.equal(confirmation.pending, true);
  assert.equal(confirmation.cancel(), false);
  assert.equal(confirmation.selection, "folioorb-backup.db");

  confirmation.fail();
  assert.equal(confirmation.pending, false);
  assert.equal(confirmation.cancel(), true);
  assert.equal(confirmation.selection, null);
});
