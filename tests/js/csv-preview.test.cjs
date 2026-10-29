const test = require("node:test");
const assert = require("node:assert/strict");
const { createCsvPreview } = require("../../static/js/csv-preview.js");
const { createPortfolioWorkspace } = require("../../static/js/portfolio-workspace.js");

function makeDocument() {
    const doc = { activeElement: null };
    function element(tag = "div") {
        const node = { tag, children: [], disabled: false, hidden: false, value: "", attrs: {}, handlers: {},
            append(...children) { this.children.push(...children); },
            replaceChildren(...children) { this.children = children; this._text = ""; },
            setAttribute(key, value) { this.attrs[key] = value; },
            addEventListener(event, fn) { this.handlers[event] = fn; },
            focus() { doc.activeElement = this; },
            click() { if (!this.disabled) this.handlers.click?.(); },
            get textContent() { return (this._text || "") + this.children.map(n => n.textContent).join(" "); },
            set textContent(value) { this._text = String(value); this.children = []; },
            set innerHTML(_value) { throw new Error("Preview must render text, never HTML"); },
        };
        return node;
    }
    const ids = ["choose", "input", "result", "heading", "status", "table", "paging", "previous", "next", "range", "close"];
    const nodes = Object.fromEntries(ids.map(id => ["csv-preview-" + id, element()]));
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
function setup(fetchFn = async () => ({ ok: true, json: async () => data() })) {
    const document = makeDocument();
    const workspace = createPortfolioWorkspace({ fetchFn, origin: "http://loop.test", reload() {}, storage: null });
    const controller = createCsvPreview({ document, workspace });
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
    report.rows[0].reason = "Input should be a finite number";
    report.rows[1].status = "error";
    report.rows[1].reason = "Could not validate: symbol may be invalid or the provider unavailable.";
    const ui = setup(async () => ({ ok: true, json: async () => report }));
    await ui.controller.start(file());
    const rows = ui.get("table").children[0].children[2].children;
    assert.equal(rows[0].children[1].textContent, "error (supplied text)");
    assert.equal(rows[0].children[3].textContent, "NaN");
    assert.equal(rows[1].children[1].textContent, "error");
    assert.equal(rows[1].children[3].textContent, "1");
    assert.match(ui.get("table").textContent, /Values are normalized unless Result says supplied text/);
});
