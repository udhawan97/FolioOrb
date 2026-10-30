const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const Logic = require("../../static/js/review-orbit-logic.js");
const interactions = require("../../static/js/interaction-state.js");
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
function plan(value) {
    return { items: [{ holding_id: 1, ticker: "TEST", target_weight_bps: value,
        actual_weight_bps: 10000, drift_bps: null }], target_total_bps: value,
        remaining_bps: 10000 - value, complete: false, drift_available: false };
}
function harness({ backups = null, report = null, deferReports = false, comparison = null } = {}) {
    let inputs = [];
    const elements = new Map();
    const listeners = {};
    const makeElement = id => {
        let markup = "";
        const element = { id, value: "", textContent: "", hidden: false, disabled: false,
            dataset: {}, events: {}, classList: { add() {}, remove() {} },
            addEventListener(name, callback) { this.events[name] = callback; },
            setAttribute() {}, removeAttribute() {}, focus() {}, replaceChildren() {},
            querySelectorAll() { return []; },
            insertAdjacentHTML(_, value) { markup = value + markup; },
            get innerHTML() { return markup; },
            set innerHTML(value) {
                markup = String(value);
                if (id === "review-target-table") {
                    inputs = [...value.matchAll(/data-holding-id="(\d+)" value="([^"]*)"/g)]
                        .map(([, holdingId, target]) => ({ dataset: { holdingId }, value: target,
                            matches: selector => selector === ".review-target-input" }));
                }
            },
        };
        return element;
    };
    const get = id => {
        if (!elements.has(id)) elements.set(id, makeElement(id));
        return elements.get(id);
    };
    const document = {
        getElementById: get,
        querySelector: selector => selector.startsWith("[data-review-") ? get(selector) : null,
        querySelectorAll: selector => {
            if (selector === ".review-target-input") return inputs;
            if (selector === "[data-report-period]") {
                return ["month", "quarter"].map(period => {
                    const button = get(`period-${period}`); button.dataset.reportPeriod = period; return button;
                });
            }
            if (selector === ".review-watchlist-pick input:checked") {
                return ["LEFT", "RIGHT"].map(value => ({ value, dataset: { kind: "ETF" } }));
            }
            if (selector === "[data-report-export]") {
                const button = get("report-export"); button.dataset.reportExport = "csv"; return [button];
            }
            if (selector === "[data-review-snapshot-export]") {
                get("review-plan-export").dataset.reviewSnapshotExport = "plan";
                return [get("review-plan-export")];
            }
            return [];
        },
        addEventListener: (name, callback) => { listeners[name] = callback; },
    };
    const reads = [], puts = [], exports = [], messages = [], reportReads = [];
    const workspace = { json: (url, init) => {
        if (init?.method === "PUT") {
            const request = deferred(); puts.push({ ...request, body: JSON.parse(init.body) });
            return request.promise;
        }
        if (url === "/api/review/plan") {
            const request = deferred(); reads.push(request); return request.promise;
        }
        if (url === "/api/review/backups") return Promise.resolve(backups);
        if (url.startsWith("/api/review/report?")) {
            if (!deferReports) return Promise.resolve(report);
            const request = deferred(); reportReads.push({ ...request, url }); return request.promise;
        }
        if (url.startsWith("/api/review/compare?")) return Promise.resolve(comparison);
        if (url === "/api/review/overview") return Promise.resolve({ items: [], known_value_usd: 0 });
        return Promise.reject(new Error("Unused review surface"));
    }, response: async url => { exports.push(url); throw new Error("export reached"); } };
    const context = {
        window: { ReviewOrbitLogic: Logic, FolioInteractionState: interactions }, document,
        localStorage: { getItem() { return null; }, setItem() {} },
        PortfolioWorkspace: workspace, CSS: { escape: value => value },
        html: (parts, ...values) => parts.reduce((result, part, i) => result + part +
            (Array.isArray(values[i]) ? values[i].join("") : values[i] ?? ""), ""),
        apiErrorMessage: (error, fallback) => error?.message || fallback,
        Intl, requestAnimationFrame: callback => callback(),
        formatHoldingMoney: (item, value) => value == null ? "Unavailable" : item.currency.toUpperCase() === "USD"
            ? `$${Number(value).toFixed(2)}` : `${Number(value).toFixed(2)} ${item.currency}`,
        showToast: message => messages.push(message),
    };
    vm.runInNewContext(fs.readFileSync(require.resolve("../../static/js/core.js"), "utf8")
        + "\n" + fs.readFileSync(require.resolve("../../static/js/review-orbit.js"), "utf8"), context);
    listeners.DOMContentLoaded();
    return {
        get, reads, puts, exports, messages, reportReads, orbit: context.window.ReviewOrbit,
        value: () => inputs[0]?.value,
        edit: value => { inputs[0].value = value; get("review-target-form").events.input({ target: inputs[0] }); },
        save: () => get("review-target-form").events.submit({ preventDefault() {} }),
        start: async () => {
            context.window.ReviewOrbit.activateTab("plan");
            reads[0].resolve(plan(1000)); await flush();
        },
    };
}

test("Review Pack distinguishes unavailable full value from known subtotal and real zero", async () => {
    const report = { current: { total_value: null, known_value: 0, total_return: null, total_return_pct: null },
        period_activity: { value_change: null, realized_gain: 0 }, snapshot_count: 1,
        observed_start: "2026-09-25", data_quality: { history: "complete", valuation: "unavailable", missing_prices: ["VTI"] },
        foreign_currency_tickers: ["VOD.L"], thesis_attention: [] };
    const h = harness({ report });
    h.orbit.activateTab("report"); await flush();
    const markup = h.get("review-report-summary").innerHTML;
    assert.match(markup, /Current value<\/span><strong>Unavailable/);
    assert.match(markup, /Known USD subtotal · incomplete<\/span><strong>\$0/);
    assert.match(markup, /Value change since 2026-09-25<\/span><strong>Unavailable/);
    assert.match(markup, /Realized this period<\/span><strong>\$0/);
    assert.match(markup, /Missing prices: VTI/);
    assert.match(markup, /Foreign-priced, excluded from USD: VOD.L/);
    assert.doesNotMatch(markup, /0%/);

    const empty = harness({ report: { ...report, current: { total_value: 0, known_value: 0, total_return: 0, total_return_pct: 0 },
        data_quality: { valuation: "complete", history: "unavailable", missing_prices: [] }, foreign_currency_tickers: [] } });
    empty.orbit.activateTab("report"); await flush();
    assert.match(empty.get("review-report-summary").innerHTML, /Current value<\/span><strong>\$0/);
    assert.doesNotMatch(empty.get("review-report-summary").innerHTML, /Known USD subtotal/);
});

test("delayed save and readback preserve edits typed during both requests", async () => {
    const h = harness(); await h.start();
    h.edit("2000"); const saving = h.save();
    assert.equal(h.puts[0].body.items[0].target_weight_bps, 2000);
    h.edit("3000"); h.puts[0].resolve({}); await flush();
    h.edit("4000"); h.reads[1].resolve(plan(2000)); await saving;
    assert.equal(h.value(), "4000");
    assert.equal(h.get("review-plan-export").disabled, true);
    assert.match(h.get("review-target-status").textContent, /unsaved/i);
    assert.match(h.get("review-target-status").textContent, /saved/i);
});

test("ordinary refresh preserves edits started or changed after its GET began", async () => {
    const h = harness(); await h.start();
    const refreshing = h.orbit.refresh();
    h.edit("3000"); h.reads[1].resolve(plan(1000)); await refreshing;
    assert.equal(h.value(), "3000");
    const again = h.orbit.refresh();
    h.edit("4000"); h.reads[2].resolve(plan(1000)); await again;
    assert.equal(h.value(), "4000");
    assert.equal(h.get("review-plan-export").disabled, true);
});

test("repeated submit is serialized and pre-save GET cannot replace newer saved state", async () => {
    const h = harness(); await h.start();
    const oldRefresh = h.orbit.refresh();
    h.edit("2000"); const saving = h.save();
    h.edit("3000"); h.save();
    assert.equal(h.puts.length, 1);
    h.puts[0].resolve({}); await flush();
    h.reads[2].resolve(plan(2000)); await saving;
    h.reads[1].resolve(plan(1000)); await oldRefresh;
    assert.equal(h.value(), "3000");
    h.edit("2000");
    assert.equal(h.get("review-plan-export").disabled, false);
    h.edit("4000"); const next = h.save();
    assert.equal(h.puts.length, 2);
    h.puts[1].resolve({}); await flush();
    h.reads[3].resolve(plan(4000)); await next;
    assert.equal(h.value(), "4000");
    assert.equal(h.get("review-plan-export").disabled, false);
});

test("failed readback retains newer draft and blocks export even when it equals the old saved value", async () => {
    const h = harness(); await h.start();
    h.edit("2000"); const saving = h.save();
    h.puts[0].resolve({}); await flush();
    h.edit("1000"); h.reads[1].reject(new Error("offline")); await saving;
    assert.equal(h.value(), "1000");
    assert.equal(h.get("review-plan-export").disabled, true);
    assert.match(h.get("review-target-status").textContent, /saved.*could not be read back/i);
    const retry = h.orbit.refresh(); h.reads[2].resolve(plan(2000)); await retry;
    assert.equal(h.value(), "1000");
    assert.equal(h.get("review-plan-export").disabled, true);
    h.edit("2000"); assert.equal(h.get("review-plan-export").disabled, false);
});


test("Plan and bundle export handlers refuse in-flight saves and unreadback saves", async () => {
    const h = harness(); await h.start();
    const checkExports = async () => {
        await h.get("review-plan-export").events.click();
        await h.get("review-bundle-export").events.click();
        assert.equal(h.exports.length, 0);
        assert.match(h.messages.at(-1), /refresh the saved Plan/);
    };
    // Saving an unchanged value still makes export wait for its result.
    const saving = h.save(); await checkExports();
    h.puts[0].resolve({}); await flush();
    h.reads[1].reject(new Error("offline")); await saving;
    await checkExports();
    const retry = h.orbit.refresh(); h.reads[2].resolve(plan(1000)); await retry;
    assert.equal(h.get("review-plan-export").disabled, false);
    assert.match(h.get("review-target-status").textContent, /read back/);
    assert.doesNotMatch(h.get("review-target-status").textContent, /could not/);
    await h.get("review-plan-export").events.click();
    assert.equal(h.exports.length, 1);
});

test("refresh during PUT leaves editable draft intact and readback retains only newer edits", async () => {
    const h = harness(); await h.start();
    h.edit("2000"); const saving = h.save();
    const refreshing = h.orbit.refresh(); await flush();
    assert.equal(h.reads.length, 1);
    await refreshing;
    assert.equal(h.value(), "2000");
    h.puts[0].resolve({}); await flush(); h.reads[1].resolve(plan(2000)); await saving;
    assert.equal(h.value(), "2000");
    assert.equal(h.get("review-plan-export").disabled, false);
    assert.doesNotMatch(h.get("review-target-status").textContent, /unsaved/i);
});


for (const [receipt, expected, absent] of [
    [{ status: "restored", installer_status: "failed", environment_status: "failed" },
        ["database was restored", "previous installer could not be launched", "Saved settings could not be restored"],
        ["failed before replacing"]],
    [{ status: "restored" }, ["Restored fixture successfully"],
        ["could not be launched", "settings could not"]],
    [{ status: "failed" }, ["failed before replacing the live database"],
        ["Restored fixture successfully"]],
]) {
    test("backup receipt distinguishes database, installer and settings outcomes: " + JSON.stringify(receipt), async () => {
        const h = harness({ backups: { items: [], last_restore: { name: "fixture", ...receipt } } });
        h.orbit.activateTab("backups"); await flush();
        const status = h.get("review-restore-status");
        assert.equal(status.hidden, false);
        for (const text of expected) assert.ok(status.textContent.includes(text), status.textContent);
        for (const text of absent) assert.ok(!status.textContent.includes(text), status.textContent);
    });
}


test("a failed save preserves newer input and permits an explicit retry", async () => {
    const h = harness(); await h.start();
    h.edit("2000"); const saving = h.save(); h.edit("3000");
    h.puts[0].reject(new Error("save unavailable")); await saving;
    assert.equal(h.value(), "3000");
    assert.equal(h.get("review-target-save").disabled, false);
    assert.equal(h.get("review-plan-export").disabled, true);
    assert.match(h.get("review-target-status").textContent, /save unavailable/);
    const retry = h.save(); h.puts[1].resolve({}); await flush();
    h.reads[1].resolve(plan(3000)); await retry;
    assert.equal(h.value(), "3000");
    assert.equal(h.get("review-plan-export").disabled, false);
});

function periodReport(value) {
    return { current: { total_value: value, total_return: 0, total_return_pct: 0 },
        period_activity: { value_change: value, realized_gain: 0 }, snapshot_count: 1,
        observed_start: '2026-10-01', data_quality: { valuation: 'complete', history: 'complete' },
        thesis_attention: [] };
}

test('latest selected report period owns metrics, stale responses, and export', async () => {
    const h = harness({ deferReports: true });
    h.orbit.activateTab('report');
    h.get('period-quarter').events.click();
    assert.match(h.reportReads[0].url, /period=month/);
    assert.match(h.reportReads[1].url, /period=quarter/);
    h.reportReads[1].resolve(periodReport(300)); await flush();
    assert.match(h.get('review-report-title').textContent, /Quarterly/);
    assert.match(h.get('review-report-summary').innerHTML, /\$300/);
    h.reportReads[0].resolve(periodReport(100)); await flush();
    assert.match(h.get('review-report-summary').innerHTML, /\$300/);
    assert.doesNotMatch(h.get('review-report-summary').innerHTML, /\$100/);
    await h.get('report-export').events.click(); await flush();
    assert.match(h.exports[0], /period=quarter/);
});

test('older failed report cannot replace the latest success with a stale error', async () => {
    const h = harness({ deferReports: true }); h.orbit.activateTab('report');
    h.get('period-quarter').events.click();
    h.reportReads[1].resolve(periodReport(300)); await flush();
    h.reportReads[0].reject(new Error('old month failed')); await flush();
    assert.doesNotMatch(h.get('review-report-summary').innerHTML, /old month failed/);
    assert.match(h.get('review-report-summary').innerHTML, /\$300/);
});

test('retained report identifies its actual period while a new period loads or fails', async () => {
    const h = harness({ deferReports: true }); h.orbit.activateTab('report');
    h.reportReads[0].resolve(periodReport(100)); await flush();
    h.get('period-quarter').events.click();
    assert.match(h.get('review-report-summary').innerHTML, /previous month report while the quarter report loads/);
    h.reportReads[1].reject(new Error('quarter unavailable')); await flush();
    assert.match(h.get('review-report-summary').innerHTML, /last successful month report/);
    assert.match(h.get('review-report-summary').innerHTML, /\$100/);
});

test('Compare preserves GBp/CAD price units and escaped ETF text without inventing market-cap currency', async () => {
    const items = [
        { ticker: 'LEFT', name: 'London', current_price: 100, currency: 'GBp', day_change_pct: 1,
            metrics: { category: 'Large Blend', concentration: '<img src=x onerror=alert(1)>', expense_ratio: 0.001, aum: 1000000, pe_ratio: 20, top_holdings: [{ ticker: 'A' }] }, thesis: { status: 'missing' } },
        { ticker: 'RIGHT', name: 'Canada', current_price: 12.5, currency: 'CAD', day_change_pct: null,
            metrics: { category: null, concentration: 'Moderate' }, thesis: { status: 'missing' } },
    ];
    const h = harness({ comparison: { items } }); await h.get('review-compare-run').events.click();
    const markup = h.get('review-compare-results').innerHTML;
    assert.match(markup, /100\.00 GBp/); assert.match(markup, /12\.50 CAD/);
    assert.match(markup, /Large Blend/); assert.match(markup, /Moderate/);
    assert.match(markup, /&lt;img src=x onerror=alert\(1\)&gt;/);
    assert.doesNotMatch(markup, /<img|NaN|\$/);
    assert.match(markup, /currency unverified/); assert.match(markup, /Unavailable/);
});

test('Compare does not imply USD when a provider omits currency', async () => {
    const items = [null, 'USD'].map((currency, index) => ({ ticker: index ? 'RIGHT' : 'LEFT', name: 'Example',
        current_price: 10, currency, day_change_pct: null, metrics: {}, thesis: { status: 'missing' } }));
    const h = harness({ comparison: { items } }); await h.get('review-compare-run').events.click();
    const markup = h.get('review-compare-results').innerHTML;
    assert.match(markup, /Unavailable \(quote currency unknown\)/);
    assert.match(markup, /\$10\.00/);
});

for (const excluded of [undefined, 0, 2]) {
    test(`review and target explanation preserves all-time scope and legacy fields: ${excluded}`, async () => {
        const report = periodReport(null);
        report.data_quality.valuation = 'partial';
        if (excluded !== undefined) report.data_quality.excluded_realized_trade_count = excluded;
        const h = harness({ report });
        h.orbit.activateTab('report'); await flush();
        const markup = h.get('review-report-summary').innerHTML;
        assert.match(markup, /Valuation coverage/);
        assert.doesNotMatch(markup, /Price coverage/);
        if (excluded === 2) {
            assert.match(markup, /2 realized records excluded from USD returns \(all time\)/);
            assert.match(markup, /View Trust Center/);
        } else assert.doesNotMatch(markup, /realized records excluded/);
        h.orbit.activateTab('plan');
        h.reads[0].resolve({ ...plan(10000), complete: true, valuation_quality: 'partial',
            ...(excluded === undefined ? {} : { excluded_realized_trade_count: excluded }) });
        await flush();
        const target = h.get('review-course-summary').innerHTML;
        if (excluded === 2) assert.match(target, /2 realized records excluded.*all time/);
        else assert.doesNotMatch(target, /realized records excluded/);
    });
}

for (const excluded of [undefined, 0, 2]) {
    test(`empty target view keeps controls disabled and explains only known exclusions: ${excluded}`, async () => {
        const h = harness();
        h.orbit.activateTab('plan');
        h.reads[0].resolve({ ...plan(0), items: [],
            ...(excluded === undefined ? {} : { excluded_realized_trade_count: excluded }) });
        await flush();
        const markup = h.get('review-course-summary').innerHTML;
        assert.match(markup, /Add an owned position/);
        assert.equal(h.get('review-target-save').disabled, true);
        assert.equal(h.get('review-plan-export').disabled, true);
        assert.equal(h.get('review-rehearsal-run').disabled, true);
        if (excluded === 2) {
            assert.match(markup, /2 realized records excluded.*all time/);
            assert.match(markup, /View Trust Center/);
        } else assert.doesNotMatch(markup, /realized records excluded/);
    });
}
