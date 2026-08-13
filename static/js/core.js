/**
 * core.js
 * The runtime the rest of the dashboard is built on: HTML escaping, data
 * error normalization and the holding-panel registry.
 *
 * Loaded first, so these globals exist before analytics-charts.js or
 * dashboard.js runs. There is no build step and no module system here —
 * everything below is a plain global shared by every script on the page.
 *
 * Each piece is deep on purpose: a small interface with a lot of behaviour
 * behind it, so callers stop re-implementing that behaviour by hand.
 *   escaping       — `html` escapes every interpolation, so a forgotten wrap
 *                    can no longer be an XSS; `raw` is the one visible seam
 *                    for opting out.
 *   panel registry — `registerHoldingPanel` + `renderHoldingPanels` turn "add
 *                    a panel to a holding row" into one registration instead
 *                    of an edit at every render site.
 *
 * Why `function` and not `const` for escapeHtml / inlineJsString /
 * apiErrorMessage: these three were lifted out of dashboard.js, and a later
 * script redeclaring one of them must not break the page. Two `function`
 * declarations of one name across two classic scripts is legal — the later one
 * wins — whereas a `const` here against a `function` there is a SyntaxError
 * that kills the whole later script. The duplicate copies are all gone now;
 * the declaration form stays as the cheap guard against a copy coming back.
 */

// ── Escaping ──────────────────────────────────────────────────────────────

/**
 * Escape a value for interpolation into HTML text or a quoted attribute.
 * Character-for-character identical to the copy in dashboard.js it replaces,
 * because hundreds of call sites depend on its exact output — including the
 * `String(str)` quirk that renders null as "null". `html` is kinder about
 * nullish values; this stays as-is so a drop-in swap changes nothing.
 */
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Quote a value as a JS string literal safe to sit inside an HTML attribute,
 * e.g. onclick="setHoldMode(event, ${inlineJsString(ticker)})". Same output as
 * the copy in dashboard.js it replaces.
 */
function inlineJsString(str) {
    return JSON.stringify(String(str ?? "")).replace(/"/g, "&quot;");
}

// Marker for already-built HTML. `html` returns one and passes one through
// untouched, which is what keeps a nested tag from being escaped twice. It
// extends String so a marker behaves like the string it carries everywhere a
// caller might put one: `${marker}`, `el.innerHTML = marker`, `.length`,
// array .join(""). Kept private — `raw()` is how callers make one.
class _CoreRawHtml extends String {}

// One interpolation, coerced to a string that is safe to concatenate.
function _coreHtmlValue(value) {
    if (value === null || value === undefined) return "";
    if (value instanceof _CoreRawHtml) return value.toString();
    if (Array.isArray(value)) return value.map(_coreHtmlValue).join("");
    return escapeHtml(value);
}

/**
 * Tagged template that escapes every interpolation. Use it instead of a bare
 * template literal plus hand-placed escapeHtml() calls: escaping becomes the
 * default and `raw()` the only way out, so safety no longer depends on
 * remembering to wrap — which is the whole point, since one forgotten wrap in
 * an innerHTML template is an XSS.
 *
 *   html`<td title="${h.name}">${h.ticker}</td>`
 *   html`<ul>${items.map(i => html`<li>${i}</li>`)}</ul>`  // no double-escape
 *   html`<div>${raw(builtElsewhere)}</div>`                // deliberate opt-out
 *
 * Interpolation rules: null and undefined render as "", arrays join with ""
 * (so a .map() drops straight in, nested arrays included), a `raw()` or nested
 * `html` value passes through untouched, everything else goes through
 * escapeHtml.
 *
 * Returns a raw-marked value rather than a bare string — that is what makes
 * nesting safe. It stringifies to the built HTML, so assigning it to innerHTML
 * or interpolating it into another template needs no unwrapping. Two things to
 * know about it: it is an object, so it is truthy even when empty and `===`
 * against a plain string is false; and String methods on it (.trim(), .slice())
 * return plain strings, which the tag would then escape — re-wrap in `raw()`
 * if you transform a built result.
 */
function html(strings, ...values) {
    let out = strings[0];
    for (let i = 0; i < values.length; i++) {
        out += _coreHtmlValue(values[i]) + strings[i + 1];
    }
    return new _CoreRawHtml(out);
}

/**
 * Mark a value as already-built HTML so `html` interpolates it untouched.
 * The seam for the deliberate cases — nesting markup a caller built elsewhere
 * — and the only route to unescaped output, which is what makes those cases
 * greppable. null and undefined become "".
 */
function raw(value) {
    return new _CoreRawHtml(value ?? "");
}

// ── Data access ───────────────────────────────────────────────────────────

/**
 * Turn whatever an API handed back — an Error, a FastAPI {"detail": …}, a
 * pydantic list of validation errors, a bare string — into one line of text
 * fit to show a person. Copied verbatim from dashboard.js so the wording users
 * see does not shift as call sites move over.
 */
function apiErrorMessage(err, fallback = "Something went wrong") {
    const detail = err?.detail ?? err?.message ?? err;
    if (Array.isArray(detail)) {
        return detail
            .map(item => item?.msg || item?.message || String(item))
            .filter(Boolean)
            .join("; ") || fallback;
    }
    if (detail && typeof detail === "object") {
        return detail.msg || detail.message || JSON.stringify(detail);
    }
    return detail ? String(detail) : fallback;
}

// ── Holding-panel registry ────────────────────────────────────────────────

/**
 * Every panel that can appear inside a holding's expand-row, in render order.
 * Read it to drive work across all panels at once — rendering, and the lazy
 * fetching that fills their caches. Write to it only via registerHoldingPanel.
 *
 * A descriptor is:
 *   sel    — CSS selector for the panel's element inside the expand-row.
 *   render — (section, ticker, ctx) => void. Paints `section`. `ctx` is
 *            whatever the calling render site passes; panels that must tell
 *            "still loading" from "loaded and empty" read it.
 *   fetch  — optional (ticker) => url, the endpoint whose payload fills
 *            `cache`. Carried here so one loader can serve every panel.
 *   cache  — the store this panel reads, keyed by ticker.
 *
 * core.js knows nothing about which panels exist; consumers register them.
 */
const HOLDING_PANELS = [];

/**
 * Add a panel to the registry. Registration is the whole interface: a new panel
 * costs one descriptor instead of an edit at every render site — which is
 * exactly how those sites drifted apart in the first place.
 *
 * A malformed descriptor throws at registration rather than rendering nothing
 * later, so the mistake surfaces at its cause. Returns the descriptor.
 */
function registerHoldingPanel(descriptor) {
    if (!descriptor || typeof descriptor.sel !== "string" || !descriptor.sel) {
        throw new TypeError("registerHoldingPanel: sel must be a non-empty CSS selector");
    }
    if (typeof descriptor.render !== "function") {
        throw new TypeError(`registerHoldingPanel(${descriptor.sel}): render must be a function`);
    }
    if (descriptor.fetch !== undefined && typeof descriptor.fetch !== "function") {
        throw new TypeError(`registerHoldingPanel(${descriptor.sel}): fetch must be a function`);
    }
    HOLDING_PANELS.push(descriptor);
    return descriptor;
}

/**
 * Paint every registered panel present in this expand-row, in registration
 * order. Panels the row does not contain are skipped, so one call covers every
 * layout variant and every render site.
 *
 * A render that throws propagates rather than being swallowed, matching what
 * the hand-written runs of `if (section) render(...)` did before.
 */
function renderHoldingPanels(expandRow, ticker, ctx) {
    if (!expandRow) return;
    HOLDING_PANELS.forEach(panel => {
        const section = expandRow.querySelector(panel.sel);
        if (section) panel.render(section, ticker, ctx);
    });
}
