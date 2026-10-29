const test = require("node:test");
const { createHash } = require("node:crypto");
const assert = require("node:assert/strict");
const { createCsvPreview } = require("../../static/js/csv-preview.js");
const { createPortfolioWorkspace } = require("../../static/js/portfolio-workspace.js");

function makeDocument() {
    const doc = { activeElement: null };
    function element(tag = "div") {
        const node = { tag, children: [], disabled: false, hidden: false, value: "", checked: false, attrs: {}, handlers: {},
            append(...children) { this.children.push(...children); },
            replaceChildren(...children) { this.children = children; this._text = ""; },
            setAttribute(key, value) { this.attrs[key] = value; },
            addEventListener(event, fn) { this.handlers[event] = fn; },
            focus() { doc.activeElement = this; },
            click() { if (!this.disabled) return this.handlers.click?.(); },
            get textContent() { return (this._text || "") + this.children.map(n => n.textContent).join(" "); },
            set textContent(value) { this._text = String(value); this.children = []; },
            set innerHTML(_value) { throw new Error("Preview must render text, never HTML"); },
        };
        return node;
    }
    const ids = ["choose", "input", "result", "heading", "status", "table", "paging", "previous", "next", "range", "close", "confirm", "recovery", "acknowledge", "fresh", "reconcile"];
    const nodes = Object.fromEntries(ids.map(id => ["csv-preview-" + id, element()]));
    nodes["import-choose-btn"] = element("button");
    nodes["import-csv-btn"] = element("button");
    for (const id of ["result", "paging", "recovery"]) nodes["csv-preview-" + id].hidden = true;
    doc.getElementById = id => nodes[id];
    doc.createElement = element;
    return doc;
}
function data(count = 2, portfolioId = 1) {
    return { portfolio_id: portfolioId, portfolio: { name: "Fictional portfolio" },
        snapshot_at: "2026-10-29T12:00:00Z", saved: false, would_add: count, skipped: 0, errors: 0,
        rows: Array.from({ length: count }, (_, i) => ({ row: i + 2, ticker: "SYN" + i,
            status: "would_add", normalized: true, values: { shares: 1, avg_cost: null,
                is_watchlist: false, hold_class: "auto", notes: '<img src=x onerror="evil()"> =1+1' }, reason: null })),
    };
}
function setup(fetchFn = async () => ({ ok: true, json: async () => data() } ), options = {}) {
    const document = makeDocument();
    const workspace = createPortfolioWorkspace({ fetchFn, origin: "http://loop.test", reload() {}, storage: null });
    const controller = createCsvPreview({ document, workspace, ...options });
    const get = id => document.getElementById("csv-preview-" + id);
    return { document, workspace, controller, get };
}
const file = () => new File(["ticker,shares\nSYN,1\n"], "fictional.csv", { type: "text/csv" });

test("preview uses scoped read-only endpoint, never import or refresh, and renders literal values", async () => {
    const calls = [];
    const ui = setup(async (url, init) => { calls.push([url, init]); return { ok: true, json: async () => data() }; });
    await ui.controller.start(file());
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], "/api/portfolio/holdings/preview?portfolio_id=1");
    assert.equal(calls[0][1].method, "POST");
    assert.equal(calls[0][1].body.get("file").name, "fictional.csv");
    assert.match(ui.get("status").textContent, /2 would add, 0 skipped, 0 errors/);
    assert.match(ui.get("status").textContent, /Nothing saved/);
    assert.doesNotMatch(ui.get("status").textContent, /\badded\b/);
    assert.match(ui.get("table").textContent, /<img src=x onerror="evil\(\)"> =1\+1/);
    assert.equal(ui.document.activeElement, ui.get("heading"));
    ui.get("close").click();
    assert.equal(ui.get("result").hidden, true);
    assert.equal(ui.get("table").textContent, "");
    assert.equal(ui.document.activeElement, ui.get("choose"));
});

test("pagination makes all bounded 200 rows reachable without creating 200 DOM rows", async () => {
    const ui = setup(async () => ({ ok: true, json: async () => data(200) }));
    await ui.controller.start(file());
    for (let page = 0; page < 8; page++) {
        const table = ui.get("table").children[0];
        const rows = table.children[2].children;
        assert.equal(rows.length, 25);
        assert.equal(rows[0].children[0].textContent, String(page * 25 + 2));
        assert.match(ui.get("range").textContent, new RegExp(`of 200$`));
        if (page < 7) ui.get("next").click();
    }
    assert.equal(ui.get("next").disabled, true);
    ui.get("previous").click();
    assert.match(ui.get("range").textContent, /Rows 151–175 of 200/);
});

test("cancel aborts request and old completion/finally cannot overwrite a newer preview", async () => {
    const pending = [];
    const ui = setup((url, init) => new Promise(resolve => pending.push({ url, init, resolve })));
    const first = ui.controller.start(file());
    ui.controller.cancel();
    assert.equal(pending[0].init.signal.aborted, true);
    const second = ui.controller.start(file());
    pending[0].resolve({ ok: false, json: async () => ({ detail: "old error" }) });
    await first;
    assert.equal(ui.get("choose").disabled, true);
    assert.doesNotMatch(ui.get("status").textContent, /old error/);
    pending[1].resolve({ ok: true, json: async () => data(3) });
    await second;
    assert.match(ui.get("status").textContent, /3 would add/);
});

test("portfolio switch discards response and clears preview without painting another identity", async () => {
    let finish;
    const ui = setup(() => new Promise(resolve => { finish = resolve; }));
    const request = ui.controller.start(file());
    ui.workspace.select(2);
    finish({ ok: true, json: async () => data() });
    await request;
    assert.equal(ui.get("result").hidden, true);
    assert.equal(ui.get("table").textContent, "");
});

test("unverified counts, wrong identity and legacy added payload fail closed", async () => {
    for (const mutate of [d => { d.errors = 3; }, d => { d.portfolio_id = 2; },
        d => { d.rows[0].status = "added"; }, d => { d.saved = true; }]) {
        const report = data(); mutate(report);
        const ui = setup(async () => ({ ok: true, json: async () => report }));
        await ui.controller.start(file());
        assert.match(ui.get("status").textContent, /could not be verified/);
        assert.equal(ui.get("table").textContent, "");
    }
});

test("HTTP and network failures stay explicit with no saved-success UI", async () => {
    for (const response of [async () => ({ ok: false, json: async () => ({ detail: "Malformed CSV" }) }),
        async () => { throw new Error("Unavailable"); }]) {
        const ui = setup(response);
        await ui.controller.start(file());
        assert.match(ui.get("status").textContent, /Nothing saved/);
        assert.equal(ui.get("choose").disabled, false);
        assert.equal(ui.get("table").textContent, "");
    }
});


test("invalid input is labeled supplied text while provider errors retain normalized values", async () => {
    const report = data();
    report.would_add = 0; report.errors = 2;
    report.rows[0].status = "error"; report.rows[0].normalized = false;
    report.rows[0].values.shares = "NaN";
    report.rows[0].ticker = "BAD"; report.rows[0].values.ticker = " bad ";
    report.rows[0].reason = "Input should be a finite number";
    report.rows[1].status = "error";
    report.rows[1].reason = "Could not validate: symbol may be invalid or the provider unavailable.";
    const ui = setup(async () => ({ ok: true, json: async () => report }));
    await ui.controller.start(file());
    const rows = ui.get("table").children[0].children[2].children;
    assert.equal(rows[0].children[1].textContent, "error (supplied text)");
    assert.equal(rows[0].children[2].textContent, " bad ");
    assert.equal(rows[0].children[3].textContent, "NaN");
    assert.equal(rows[1].children[1].textContent, "error");
    assert.equal(rows[1].children[3].textContent, "1");
    assert.match(ui.get("table").textContent, /Values are normalized unless Result says supplied text/);
});

const MARKER = "folioorb-csv-confirmation-v1";
const fields = ["ticker", "shares", "avg_cost", "is_watchlist", "hold_class", "notes", "thesis_review_interval_days"];
const copy = value => JSON.parse(JSON.stringify(value));
function storage() {
    const values = new Map();
    return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
        removeItem: key => values.delete(key) };
}
function confirmable(count = 2) {
    const report = data(count);
    report.mode = "local";
    report.portfolio.id = report.portfolio_id;
    report.input_digest = "a".repeat(64);
    report.reviewed_rows = report.rows.map(row => row.row);
    report.confirmation = { token: "t".repeat(43), expires_at: "2026-10-29T20:00:00Z" };
    for (const row of report.rows) {
        row.proposed_values = { ...row.values, ticker: row.ticker, avg_cost: row.values.avg_cost ?? 0, thesis_review_interval_days: null };
    }
    report.proposal_json = JSON.stringify({ mode: "local", rows: report.rows.map(row => ({ row: row.row, values: row.proposed_values })) });
    report.normalized_digest = createHash("sha256").update(report.proposal_json).digest("hex");
    return report;
}
function success(report) {
    const result = copy(report);
    delete result.confirmation;
    delete result.would_add;
    result.saved = true; result.added = report.would_add;
    result.inserted_ids = report.reviewed_rows.map((_row, i) => i + 1);
    for (const row of result.rows) if (row.status === "would_add") row.status = "added";
    return result;
}
function comparison(report, status = "matching") {
    const rows = report.rows.filter(row => row.status === "would_add").map(row => ({
        row: row.row, status, expected: copy(row.proposed_values),
        current: status === "matching" ? copy(row.proposed_values) : null,
        reason: status === "unknown" ? "Stored state unavailable" : status === "mismatching" ? "No active holding" : "Compare all fields",
    }));
    return { portfolio_id: report.portfolio_id, input_digest: report.input_digest,
        normalized_digest: report.normalized_digest, saved: false, rows,
        matching: status === "matching" ? rows.length : 0,
        mismatching: status === "mismatching" ? rows.length : 0,
        unknown: status === "unknown" ? rows.length : 0 };
}
const ok = value => ({ ok: true, json: async () => copy(value) });
const marker = (report, state = "uncertain") => ({ version: 1, state, portfolio_id: report.portfolio_id,
    input_digest: report.input_digest, normalized_digest: report.normalized_digest, reviewed_rows: report.reviewed_rows });
function prewrite(report, code) {
    return { ok: false, json: async () => ({ detail: { saved: false, not_executed: true,
        code, portfolio_id: report.portfolio_id, normalized_digest: report.normalized_digest,
        reviewed_rows: report.reviewed_rows, message: code === "busy" ? "Database busy; no confirmation was executed." : "Preview stale; nothing confirmed." } }) };
}

test("verified confirmation sends token/digest only once, checks all fields, refreshes and clears metadata", async () => {
    const report = confirmable(), saved = success(report), memory = storage(), calls = [];
    let refreshes = 0;
    const ui = setup(async (url, init) => {
        calls.push([url, init]);
        if (url.includes("/confirm?")) {
            const retained = memory.getItem(MARKER);
            assert.ok(retained, "recovery metadata precedes the financial POST");
            assert.doesNotMatch(retained, /token|notes|avg_cost|SYN|evil/);
            assert.deepEqual(JSON.parse(init.body), { token: report.confirmation.token, normalized_digest: report.normalized_digest });
            assert.equal(init.signal, undefined, "closing cannot promise to abort a financial write");
            return ok(saved);
        }
        return ok(url.includes("/reconcile?") ? comparison(report) : report);
    }, { storage: memory, refresh: async id => { assert.equal(id, 1); refreshes++; } });
    await ui.controller.start(file());
    assert.equal(ui.get("confirm").disabled, false);
    await ui.get("confirm").click();
    assert.equal(calls.filter(([url]) => url.includes("/confirm?")).length, 1);
    assert.equal(calls.length, 3);
    assert.equal(refreshes, 1);
    assert.equal(memory.getItem(MARKER), null);
    assert.match(ui.get("status").textContent, /Saved 2 reviewed additions.*Readback verified/);
    assert.match(ui.get("table").textContent, /Saved/);
    assert.doesNotMatch(ui.get("table").textContent, /Would add/);
    assert.equal(ui.get("confirm").hidden, true);
    assert.equal(ui.document.getElementById("import-choose-btn").disabled, false);
});

test("tampered displayed proposals cannot enable confirmation", async () => {
    for (const mutate of [report => { report.rows[0].proposed_values.shares = 99; },
        report => { report.normalized_digest = "b".repeat(64); },
        report => { report.proposal_json = "broken"; }]) {
        const report = confirmable(); mutate(report);
        const calls = [];
        const ui = setup(async url => { calls.push(url); return ok(report); }, { storage: storage() });
        await ui.controller.start(file());
        await ui.controller.confirm();
        assert.equal(calls.length, 1);
        assert.equal(ui.get("confirm").disabled, true);
        assert.equal(ui.get("table").textContent, "");
    }
});

test("storage failure prevents a financial request while preserving inspect-only preview", async () => {
    const report = confirmable(), calls = [];
    const memory = { getItem: () => null, setItem() { throw new Error("Recovery storage blocked"); } };
    const ui = setup(async url => { calls.push(url); return ok(report); }, { storage: memory });
    await ui.controller.start(file());
    await ui.controller.confirm();
    assert.equal(calls.length, 1);
    assert.match(ui.get("status").textContent, /No confirmation sent/);
    assert.match(ui.get("table").textContent, /Would add/);
});

test("zero valid rows never expose a confirmation action", async () => {
    for (const status of ["error", "skipped"]) {
        const report = data(1); report.rows[0].status = status; report.would_add = 0;
        report.errors = status === "error" ? 1 : 0; report.skipped = status === "skipped" ? 1 : 0;
        report.confirmation = null;
        const calls = [];
        const ui = setup(async url => { calls.push(url); return ok(report); }, { storage: storage() });
        await ui.controller.start(file()); await ui.controller.confirm();
        assert.equal(ui.get("confirm").disabled, true);
        assert.match(ui.get("status").textContent, /No additions to confirm/);
        assert.equal(calls.length, 1);
    }
});

test("verified busy permits only an explicit retry; stale clears marker and requires a fresh preview", async () => {
    for (const code of ["busy", "stale", "expired"]) {
        const report = confirmable(), memory = storage(); let writes = 0;
        const ui = setup(async url => {
            if (url.includes("/confirm?")) { writes++; return prewrite(report, code); }
            return ok(report);
        }, { storage: memory });
        await ui.controller.start(file()); await ui.controller.confirm();
        assert.equal(writes, 1);
        assert.equal(memory.getItem(MARKER), null);
        assert.equal(ui.get("confirm").hidden, code !== "busy");
        if (code === "busy") {
            assert.equal(ui.get("confirm").disabled, false);
            await ui.controller.confirm(); assert.equal(writes, 2);
        }
        const reloaded = setup(async () => { throw new Error("Reload must not replay"); }, { storage: memory });
        assert.equal(reloaded.get("result").hidden, true);
        assert.equal(reloaded.get("status").textContent, "");
        assert.equal(reloaded.get("choose").textContent, "Preview CSV…");
    }
});

test("lost response before or after commit stays blocked through reload until explicit comparison/inspection", async () => {
    for (const committed of [false, true]) {
        const report = confirmable(), memory = storage(), calls = [];
        const fetch = async url => {
            calls.push(url);
            if (url.includes("/confirm?")) throw new Error("Connection lost");
            return ok(url.includes("/reconcile?") ? comparison(report, committed ? "matching" : "mismatching") : report);
        };
        const first = setup(fetch, { storage: memory });
        await first.controller.start(file()); await first.controller.confirm();
        assert.match(first.get("status").textContent, /Outcome needs reconciliation/);
        assert.ok(memory.getItem(MARKER));
        const ui = setup(fetch, { storage: memory });
        assert.match(ui.get("status").textContent, /reconciliation/i);
        assert.equal(calls.length, 2, "reload sends no retry or read automatically");
        await ui.controller.start(file());
        assert.equal(calls.filter(url => url.includes("/confirm?")).length, 1);
        assert.equal(calls.filter(url => url.includes("/preview?")).length, 1);
        assert.match(ui.get("status").textContent, /No new import sent/);
        assert.match(ui.get("status").textContent, /Matching records do not prove this request created them/);
        assert.equal(ui.get("fresh").disabled, true);
        await ui.controller.startFresh(); assert.ok(memory.getItem(MARKER));
        ui.get("acknowledge").checked = true; ui.get("acknowledge").handlers.change();
        await ui.get("fresh").click();
        assert.equal(memory.getItem(MARKER), null);
        assert.equal(calls.length, 3, "starting fresh does not implicitly preview or import");
        assert.equal(ui.get("choose").textContent, "Preview CSV…");
    }
});

test("unknown or malformed comparison never unlocks a new preview", async () => {
    const report = confirmable();
    for (const response of [ok(comparison(report, "unknown")),
        { ok: false, json: async () => ({ detail: "Choose the original reviewed CSV file." }) },
        ok({ ...comparison(report), normalized_digest: "0".repeat(64) }),
        ok({ ...comparison(report), rows: comparison(report).rows.map(row => ({ ...row, current: {} })) })]) {
        const memory = storage(); memory.setItem(MARKER, JSON.stringify(marker(report)));
        let reads = 0;
        const ui = setup(async () => { reads++; return response; }, { storage: memory });
        await ui.controller.start(file());
        assert.equal(reads, 1);
        ui.get("acknowledge").checked = true;
        await ui.controller.startFresh();
        assert.ok(memory.getItem(MARKER));
        assert.equal(ui.get("fresh").disabled, true);
    }
});

test("saved but refresh failed is distinct from unknown acknowledgement and never repeats the write", async () => {
    const report = confirmable(), memory = storage(); let writes = 0;
    const ui = setup(async url => {
        if (url.includes("/confirm?")) { writes++; return ok(success(report)); }
        return ok(url.includes("/reconcile?") ? comparison(report) : report);
    }, { storage: memory, refresh: async () => { throw new Error("Readback offline"); } });
    await ui.controller.start(file()); await ui.controller.confirm();
    assert.match(ui.get("status").textContent, /Saved, but refresh failed.*Do not confirm again/);
    assert.equal(JSON.parse(memory.getItem(MARKER)).state, "saved");
    await ui.controller.confirm(); assert.equal(writes, 1);
    await ui.controller.reconcile();
    assert.match(ui.get("status").textContent, /2 matching/);
    assert.equal(writes, 1);
});

test("malformed success or unverified prewrite response retains uncertainty", async () => {
    const report = confirmable();
    const wrongRows = success(report); wrongRows.rows[0].proposed_values.notes = "different";
    const wrongCount = success(report); wrongCount.added = 1;
    const wrongScope = success(report); wrongScope.portfolio_id = 2;
    const fakeBusy = await prewrite(report, "busy").json(); fakeBusy.detail.normalized_digest = "0".repeat(64);
    for (const response of [ok(wrongRows), ok(wrongCount), ok(wrongScope), { ok: false, json: async () => fakeBusy }]) {
        const memory = storage(), calls = [];
        const ui = setup(async url => { calls.push(url); return url.includes("/confirm?") ? response : ok(report); }, { storage: memory });
        await ui.controller.start(file()); await ui.controller.confirm();
        assert.ok(memory.getItem(MARKER));
        assert.match(ui.get("status").textContent, /Outcome needs reconciliation/);
        assert.equal(calls.length, 2);
    }
});

test("close or portfolio switch during a write cannot paint a late success or lose the recovery marker", async () => {
    for (const switchPortfolio of [false, true]) {
        const report = confirmable(), memory = storage(); let finish, writes = 0, refreshes = 0;
        const ui = setup((url, _init) => {
            if (url.includes("/confirm?")) { writes++; return new Promise(resolve => { finish = resolve; }); }
            return Promise.resolve(ok(report));
        }, { storage: memory, refresh: async () => { refreshes++; } });
        await ui.controller.start(file());
        const pending = ui.controller.confirm();
        await ui.controller.confirm(); assert.equal(writes, 1);
        assert.equal(ui.document.getElementById("import-choose-btn").disabled, true);
        if (switchPortfolio) ui.workspace.select(2);
        else {
            ui.controller.cancel();
            assert.equal(ui.document.activeElement, ui.document.getElementById("import-csv-btn"));
            const unrelatedDraft = ui.document.createElement("input");
            unrelatedDraft.focus();
            finish(ok(success(report))); await pending;
            assert.equal(ui.document.activeElement, unrelatedDraft, "late completion must not steal focus");
        }
        if (switchPortfolio) { finish(ok(success(report))); await pending; }
        assert.equal(ui.get("result").hidden, true);
        assert.ok(memory.getItem(MARKER)); assert.equal(refreshes, 0);
        ui.controller.open();
        assert.match(ui.get("status").textContent, switchPortfolio ? /Reconcile portfolio 1/ : /reconciliation/i);
        assert.equal(writes, 1);
    }
});

test("all 200 comparison rows and every persisted field are reachable as literal text", async () => {
    const report = confirmable(200), memory = storage(); memory.setItem(MARKER, JSON.stringify(marker(report)));
    const current = comparison(report);
    current.rows[0].status = "mismatching"; current.rows[0].current.thesis_review_interval_days = 60;
    current.matching--; current.mismatching++;
    const ui = setup(async () => ok(current), { storage: memory });
    await ui.controller.start(file());
    assert.match(ui.get("table").textContent, /— → 60/);
    assert.match(ui.get("table").textContent, /<img src=x onerror="evil\(\)"> =1\+1/);
    for (let page = 0; page < 8; page++) {
        const rows = ui.get("table").children[0].children[2].children;
        assert.equal(rows.length, 25);
        assert.equal(rows[0].children.length, fields.length + 3);
        if (page < 7) ui.get("next").click();
    }
    assert.match(ui.get("range").textContent, /Rows 176–200 of 200/);
    assert.equal(ui.get("next").disabled, true);
});

test("unavailable crypto keeps the preview read-only", async () => {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto", { value: undefined, configurable: true });
    try {
        const calls = [];
        const ui = setup(async url => { calls.push(url); return ok(confirmable()); }, { storage: storage() });
        await ui.controller.start(file()); await ui.controller.confirm();
        assert.match(ui.get("status").textContent, /Read-only preview/);
        assert.equal(ui.get("confirm").disabled, true);
        assert.equal(calls.length, 1);
    } finally {
        Object.defineProperty(globalThis, "crypto", descriptor);
    }
});

test("misleading comparison summaries cannot unlock unknown rows", async () => {
    const report = confirmable(), memory = storage();
    memory.setItem(MARKER, JSON.stringify(marker(report)));
    const malformed = comparison(report, "unknown");
    malformed.unknown = 0;
    malformed.mismatching = malformed.rows.length;
    const ui = setup(async () => ok(malformed), { storage: memory });
    await ui.controller.start(file());
    assert.equal(ui.get("acknowledge").disabled, true);
    assert.equal(ui.get("fresh").disabled, true);
    ui.get("acknowledge").checked = true;
    await ui.controller.startFresh();
    assert.ok(memory.getItem(MARKER), "unknown rows must retain recovery metadata");
});
