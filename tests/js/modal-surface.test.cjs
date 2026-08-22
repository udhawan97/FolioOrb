/**
 * Behaviour tests for the shared modal seam.
 *
 * The static guards in tests/test_modal_surface_contract.py can only prove that
 * every dialog *opts in*. What "in" means is decided here, against a small fake
 * DOM: enough of a tree to model containment, inert, and where focus lands, and
 * no more.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const modals = require("../../static/js/modal-surface.js");

// ── A fake DOM, small enough to read ─────────────────────────────────────────

function makeDocument() {
  const doc = {
    body: null,
    documentElement: null,
    activeElement: null,
    listeners: [],
    addEventListener(type, handler, capture) {
      this.listeners.push({ type, handler, capture });
    },
    removeEventListener(type, handler) {
      this.listeners = this.listeners.filter(l => l.handler !== handler);
    },
    querySelectorAll(selector) {
      // The seam asks for exactly one document-level selector.
      assert.equal(selector, "body > *");
      return doc.body.children;
    },
    dispatch(event) {
      // Capture-phase order, which is registration order here.
      for (const l of [...this.listeners]) l.handler(event);
      return event;
    },
  };
  doc.body = element("body", { doc });
  doc.documentElement = element("html", { doc });
  return doc;
}

function element(name, { doc, focusable = false, tabindex = null, hidden = false,
                         visible = true, disabled = false } = {}) {
  const node = {
    tagName: name.toUpperCase(),
    id: name,
    ownerDocument: doc,
    parentElement: null,
    children: [],
    inert: false,
    hidden,
    disabled,
    isConnected: true,
    _focusable: focusable,
    _attrs: tabindex === null ? {} : { tabindex: String(tabindex) },
    getAttribute(key) { return this._attrs[key] ?? null; },
    getClientRects() { return visible ? [{}] : []; },
    contains(other) {
      if (!other) return false;
      if (other === node) return true;
      return node.children.some(child => child.contains(other));
    },
    closest(selector) {
      // Only the one selector the seam uses, read as a set of flags.
      const wants = {
        hidden: selector.includes("[hidden]"),
        ariaHidden: selector.includes("aria-hidden"),
        inert: selector.includes("[inert]"),
      };
      let cursor = node;
      while (cursor) {
        if ((wants.hidden && cursor.hidden)
          || (wants.ariaHidden && cursor._attrs["aria-hidden"] === "true")
          || (wants.inert && cursor.inert)) return cursor;
        cursor = cursor.parentElement;
      }
      return null;
    },
    querySelectorAll() {
      const out = [];
      (function walk(current) {
        for (const child of current.children) {
          if (child._focusable) out.push(child);
          walk(child);
        }
      }(node));
      return out;
    },
    focus() {
      // Mirrors the browser: focus() on something unfocusable is a silent no-op.
      if (!node._focusable || node.disabled || node.hidden) return;
      if (node.closest("[inert]")) return;
      if (!visible) return;
      doc.activeElement = node;
    },
    append(...kids) {
      for (const kid of kids) { kid.parentElement = node; node.children.push(kid); }
      return node;
    },
  };
  return node;
}

function keydown(key, { shiftKey = false } = {}) {
  return {
    key,
    shiftKey,
    defaultPrevented: false,
    propagationStopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.propagationStopped = true; },
    stopImmediatePropagation() { this.propagationStopped = true; },
  };
}

/** A document with one dialog of `n` focusable controls plus a page behind it. */
function scene({ controls = 2 } = {}) {
  const doc = makeDocument();
  const page = element("page", { doc });
  const pageButton = element("page-button", { doc, focusable: true });
  page.append(pageButton);

  const dialog = element("dialog", { doc });
  const items = [];
  for (let i = 0; i < controls; i++) {
    const control = element(`control-${i}`, { doc, focusable: true });
    items.push(control);
    dialog.append(control);
  }
  doc.body.append(page, dialog);
  return { doc, page, pageButton, dialog, items };
}

// ── isRestorable ─────────────────────────────────────────────────────────────

test("a focus target must be connected, enabled, visible and reachable", () => {
  const doc = makeDocument();
  const ok = element("ok", { doc, focusable: true });
  doc.body.append(ok);
  assert.equal(modals.isRestorable(ok), true);

  assert.equal(modals.isRestorable(null), false);
  assert.equal(modals.isRestorable({}), false, "no focus method");

  const detached = element("detached", { doc, focusable: true });
  detached.isConnected = false;
  assert.equal(modals.isRestorable(detached), false);

  const invisible = element("invisible", { doc, focusable: true, visible: false });
  doc.body.append(invisible);
  assert.equal(modals.isRestorable(invisible), false, "visibility: hidden leaves no rects");

  const off = element("off", { doc, focusable: true, disabled: true });
  doc.body.append(off);
  assert.equal(modals.isRestorable(off), false);

  const frozen = element("frozen-parent", { doc });
  const inside = element("inside", { doc, focusable: true });
  frozen.append(inside);
  doc.body.append(frozen);
  frozen.inert = true;
  assert.equal(modals.isRestorable(inside), false, "an inert ancestor hides the whole subtree");
});

// ── focusableWithin ──────────────────────────────────────────────────────────

test("roving tabindex=-1 controls are not tab stops", () => {
  const doc = makeDocument();
  const root = element("root", { doc });
  const real = element("real", { doc, focusable: true });
  const roving = element("roving", { doc, focusable: true, tabindex: -1 });
  const buried = element("buried", { doc, focusable: true, hidden: true });
  root.append(real, roving, buried);
  doc.body.append(root);

  assert.deepEqual(modals.focusableWithin(root).map(n => n.id), ["real"]);
});

test("focusableWithin on nothing is empty rather than a throw", () => {
  assert.deepEqual(modals.focusableWithin(null), []);
  assert.deepEqual(modals.focusableWithin({}), []);
});

// ── containTab ───────────────────────────────────────────────────────────────

test("Tab wraps at the end and Shift+Tab wraps at the start", () => {
  const { doc, dialog, items } = scene({ controls: 3 });

  doc.activeElement = items[2];
  const forward = keydown("Tab");
  assert.equal(modals.containTab(forward, dialog, { getActive: () => doc.activeElement }), true);
  assert.equal(forward.defaultPrevented, true);
  assert.equal(doc.activeElement, items[0]);

  doc.activeElement = items[0];
  const back = keydown("Tab", { shiftKey: true });
  assert.equal(modals.containTab(back, dialog, { getActive: () => doc.activeElement }), true);
  assert.equal(doc.activeElement, items[2]);
});

test("Tab in the middle of the surface is left to the browser", () => {
  const { doc, dialog, items } = scene({ controls: 3 });
  doc.activeElement = items[1];
  const event = keydown("Tab");
  assert.equal(modals.containTab(event, dialog, { getActive: () => doc.activeElement }), false);
  assert.equal(event.defaultPrevented, false);
  assert.equal(doc.activeElement, items[1], "focus is not moved for us");
});

test("focus that starts outside the surface is pulled back in", () => {
  const { doc, dialog, items, pageButton } = scene({ controls: 3 });

  doc.activeElement = pageButton;
  const forward = keydown("Tab");
  assert.equal(modals.containTab(forward, dialog, { getActive: () => doc.activeElement }), true);
  assert.equal(doc.activeElement, items[0], "forward re-entry lands on the first control");

  doc.activeElement = pageButton;
  const back = keydown("Tab", { shiftKey: true });
  modals.containTab(back, dialog, { getActive: () => doc.activeElement });
  assert.equal(doc.activeElement, items[2], "backward re-entry lands on the last");
});

test("a surface with no controls keeps the key rather than letting it escape", () => {
  const { doc, dialog } = scene({ controls: 0 });
  let focused = false;
  dialog.focus = () => { focused = true; };
  const event = keydown("Tab");
  assert.equal(modals.containTab(event, dialog, { getActive: () => doc.activeElement }), true);
  assert.equal(event.defaultPrevented, true);
  assert.equal(focused, true);
});

test("containTab ignores keys that are not Tab", () => {
  const { doc, dialog } = scene();
  assert.equal(modals.containTab(keydown("a"), dialog, { getActive: () => doc.activeElement }), false);
});

// ── restoreFocus ─────────────────────────────────────────────────────────────

test("a trigger that no longer takes focus falls through to the fallback", () => {
  const doc = makeDocument();
  const stale = element("stale", { doc, focusable: true });
  const landmark = element("landmark", { doc, focusable: true });
  doc.body.append(stale, landmark);
  stale.isConnected = false;                      // re-rendered away

  assert.equal(modals.restoreFocus([stale, landmark]), landmark);
  assert.equal(doc.activeElement, landmark);
});

test("document.body is never accepted as a focus target", () => {
  const doc = makeDocument();
  const landmark = element("landmark", { doc, focusable: true });
  doc.body.append(landmark);
  doc.body._focusable = true;                     // body passes every static check

  assert.equal(modals.restoreFocus([doc.body, landmark]), landmark,
    "restoring to <body> is losing focus, not returning it");
});

test("a candidate whose focus() silently fails is not reported as focused", () => {
  const doc = makeDocument();
  const refuses = element("refuses", { doc, focusable: true });
  refuses.focus = () => {};                       // accepts the call, moves nothing
  const landmark = element("landmark", { doc, focusable: true });
  doc.body.append(refuses, landmark);

  assert.equal(modals.restoreFocus([refuses, landmark]), landmark);
});

test("restoreFocus resolves thunks and returns null when nothing is left", () => {
  const doc = makeDocument();
  const landmark = element("landmark", { doc, focusable: true });
  doc.body.append(landmark);
  assert.equal(modals.restoreFocus([() => landmark]), landmark);
  assert.equal(modals.restoreFocus([() => null]), null);
});

// ── open / close ─────────────────────────────────────────────────────────────

test("opening freezes the page behind and closing thaws exactly what it froze", () => {
  const { doc, page, dialog, items, pageButton } = scene();
  doc.activeElement = pageButton;

  const handle = modals.open(dialog, { document: doc });
  assert.equal(page.inert, true, "the page behind is inert");
  assert.equal(dialog.inert, false, "the surface itself is not");

  handle.close();
  assert.equal(page.inert, false);
  assert.equal(modals.depth, 0);
  assert.equal(doc.activeElement, pageButton, "focus goes back to the opener");
  void items;
});

test("a page element that was already inert stays inert after close", () => {
  const { doc, page, dialog } = scene();
  page.inert = true;

  modals.open(dialog, { document: doc }).close();
  assert.equal(page.inert, true, "close restores the previous value, it does not clear it");
});

test("Escape closes the surface and returns focus", () => {
  const { doc, dialog, pageButton } = scene();
  doc.activeElement = pageButton;

  const handle = modals.open(dialog, { document: doc });
  const event = doc.dispatch(keydown("Escape"));

  assert.equal(event.defaultPrevented, true);
  assert.equal(handle.isOpen, false);
  assert.equal(doc.activeElement, pageButton);
});

test("onEscape returning false unwinds a step without closing the surface", () => {
  const { doc, dialog } = scene();
  let unwound = 0;

  const handle = modals.open(dialog, { document: doc, onEscape: () => { unwound += 1; return false; } });
  doc.dispatch(keydown("Escape"));

  assert.equal(unwound, 1);
  assert.equal(handle.isOpen, true, "a pending inner step keeps the workspace open");
  handle.close();
});

test("closing twice is a no-op rather than a second focus move", () => {
  const { doc, dialog, pageButton } = scene();
  doc.activeElement = pageButton;
  const handle = modals.open(dialog, { document: doc });

  assert.notEqual(handle.close(), null);
  doc.activeElement = null;
  assert.equal(handle.close(), null);
  assert.equal(doc.activeElement, null, "the second close does not move focus");
});

test("the keydown listener is removed on close", () => {
  const { doc, dialog } = scene();
  const handle = modals.open(dialog, { document: doc });
  assert.equal(doc.listeners.length, 1);
  handle.close();
  assert.equal(doc.listeners.length, 0);
});

// ── the stack ────────────────────────────────────────────────────────────────

test("a modal opened over another one is reachable, not frozen by it", () => {
  const doc = makeDocument();
  const outer = element("outer", { doc });
  const outerButton = element("outer-button", { doc, focusable: true });
  outer.append(outerButton);
  const inner = element("inner", { doc });
  const innerButton = element("inner-button", { doc, focusable: true });
  inner.append(innerButton);
  doc.body.append(outer, inner);

  const outerHandle = modals.open(outer, { document: doc });
  assert.equal(inner.inert, true, "as background, the inner dialog's markup was frozen");

  const innerHandle = modals.open(inner, { document: doc });
  assert.equal(inner.inert, false, "opening it thaws its own branch");
  innerButton.focus();
  assert.equal(doc.activeElement, innerButton, "and focus can actually reach it");

  innerHandle.close();
  assert.equal(inner.inert, true, "the surface underneath still wants it out of the way");
  assert.equal(outer.inert, false);

  outerHandle.close();
  assert.equal(inner.inert, false);
  assert.equal(modals.depth, 0);
});

test("only the innermost surface answers the keyboard", () => {
  const doc = makeDocument();
  const outer = element("outer", { doc });
  outer.append(element("outer-button", { doc, focusable: true }));
  const inner = element("inner", { doc });
  inner.append(element("inner-button", { doc, focusable: true }));
  doc.body.append(outer, inner);

  let outerEscapes = 0;
  let innerEscapes = 0;
  const outerHandle = modals.open(outer, { document: doc, onEscape: () => { outerEscapes += 1; return false; } });
  const innerHandle = modals.open(inner, { document: doc, onEscape: () => { innerEscapes += 1; return false; } });

  doc.dispatch(keydown("Escape"));
  assert.deepEqual([outerEscapes, innerEscapes], [0, 1], "the inner surface consumes it");
  assert.equal(modals.top(), inner);

  innerHandle.close();
  doc.dispatch(keydown("Escape"));
  assert.deepEqual([outerEscapes, innerEscapes], [1, 1], "the outer one takes over again");

  outerHandle.close();
});

test("opening the same surface twice returns the original handle", () => {
  const { doc, dialog } = scene();
  const first = modals.open(dialog, { document: doc });
  const second = modals.open(dialog, { document: doc });
  assert.equal(first, second);
  assert.equal(modals.depth, 1);
  first.close();
});

test("open on nothing returns null instead of throwing", () => {
  assert.equal(modals.open(null, { document: makeDocument() }), null);
});
