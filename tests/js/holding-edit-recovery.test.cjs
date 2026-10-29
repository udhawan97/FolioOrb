const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../../static/js/dashboard.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
function extract(name) {
    const marker = source.indexOf(`function ${name}(`);
    const start = source.slice(marker - 6, marker) === 'async ' ? marker - 6 : marker;
    let depth = 0, body = source.indexOf('{', source.indexOf(') {', marker));
    for (let i = body; i < source.length; i++) {
        if (source[i] === '{') depth++;
        if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
    }
    throw new Error(`Missing function ${name}`);
}
function harness({ response, readback, prompt } = {}) {
    const names = ['updateHolding', 'saveHoldingEdit', 'holdingEditHasDraft', 'rebaseHoldingEdit', 'readBackHoldingEdit', 'invalidateManageHoldingsLoad'];
    const shares = { value: '10', defaultValue: '10', dataset: { watchlist: 'false' } };
    const cost = { value: '100', defaultValue: '100' };
    const classes = new Set();
    const card = { dataset: { ticker: 'TEST' }, classList: { add: c => classes.add(c), remove: c => classes.delete(c) } };
    const puts = [], statuses = [], messages = [], prompts = [], reads = [];
    const context = { document: { getElementById: id => ({ 'shares-7': shares, 'cost-7': cost, 'manage-row-7': card })[id] },
        manageHoldingSaves: new Map(), manageUnknownEdits: new Map(),
        manageHoldingsRequestId: 0,
        manageHoldingsCache: [{ id: 7, ticker: 'TEST', shares: 10, avg_cost: 100 }],
        PortfolioWorkspace: {
            invalidate() {},
            response(url, init) { puts.push(JSON.parse(init.body)); return response ? response(puts.length, puts.at(-1)) : Promise.resolve({ ok: true }); },
            async json(url) { reads.push(url); return readback ? readback(url) : { holdings: [{ id: 7, ticker: 'TEST', shares: 10, avg_cost: 100 }] }; },
        },
        renderPnlData: async () => {}, refreshPortfolioMutationInBackground() {}, refreshAiVerdicts() {},
        setManageSaveStatus: (_, state) => statuses.push(state), showToast: (text, level) => messages.push({ text, level }),
        promptSaleDetails: async details => { prompts.push(details); return prompt ? prompt(details) : { sale_price: 120, sale_date: '2026-10-29' }; },
        apiErrorMessage: (error, fallback) => error.detail || fallback,
        console: { warn() {} },
    };
    vm.createContext(context);
    vm.runInContext(names.map(extract).join('\n'), context);
    return { shares, cost, card, puts, statuses, messages, prompts, reads, context, classes,
        save: options => context.updateHolding(7, { silent: true, ...options }) };
}

test('validation rejection finishes saving and preserves the unsaved draft', async () => {
    const h = harness({ response: async () => ({ ok: false, status: 422, json: async () => ({ detail: 'Invalid cost' }) }) });
    h.cost.value = '120'; await h.save();
    assert.equal(h.puts.length, 1); assert.equal(h.reads.length, 0);
    assert.equal(h.cost.defaultValue, '100'); assert.equal(h.cost.value, '120');
    assert.equal(h.statuses.at(-1), 'error'); assert.equal(h.classes.has('is-saving'), false);
    assert.match(h.messages.at(-1).text, /Invalid cost/);
});

test('precommit connection failure reads persisted facts and never retries automatically', async () => {
    const h = harness({ response: async () => { throw new Error('offline'); } });
    h.shares.value = '12'; await h.save();
    assert.equal(h.puts.length, 1); assert.equal(h.shares.defaultValue, '10');
    assert.equal(h.shares.value, '12'); assert.equal(h.statuses.at(-1), 'draft');
    assert.equal(h.classes.has('is-saving'), false); assert.match(h.messages.at(-1).text, /unsaved inputs remain/);
    assert.equal(h.context.manageUnknownEdits.size, 0);
});

test('committed sale with a lost response rebases shares and refreshes realized history without another sale', async () => {
    let ledgerRendered = 0;
    const h = harness({ response: async () => { throw new Error('response lost'); },
        readback: async url => url.endsWith('/holdings')
            ? { holdings: [{ id: 7, shares: 8, avg_cost: 100 }] } : { trades: [{ shares_sold: 2 }] } });
    h.context.renderPnlData = async () => { ledgerRendered++; };
    h.shares.value = '8'; await h.save({ viaBlur: true });
    assert.equal(h.puts.length, 1); assert.equal(h.shares.defaultValue, '8');
    assert.equal(ledgerRendered, 1); assert.equal(h.statuses.at(-1), 'saved');
    await h.save({ viaBlur: true });
    assert.equal(h.puts.length, 1); assert.equal(h.prompts.length, 1);
    assert.equal(h.context.manageUnknownEdits.size, 0);
});

test('unknown response blocks further writes until authoritative readback succeeds', async () => {
    let readable = false;
    const h = harness({ response: async () => { throw new Error('response lost'); },
        readback: async () => {
            if (!readable) throw new Error('still offline');
            return { holdings: [{ id: 7, shares: 12, avg_cost: 100 }] };
        } });
    h.shares.value = '12'; await h.save();
    assert.equal(h.statuses.at(-1), 'unknown'); assert.equal(h.classes.has('is-saving'), false);
    await h.save({ viaBlur: true });
    assert.equal(h.puts.length, 1); assert.equal(h.statuses.at(-1), 'unknown');
    readable = true; await h.save({ viaBlur: true });
    assert.equal(h.puts.length, 1); assert.equal(h.statuses.at(-1), 'saved');
    assert.equal(h.shares.defaultValue, '12');
});

test('queued edits serialize PUTs and retain newer text while a slow save finishes', async () => {
    const first = deferred(), second = deferred();
    const h = harness({ response: count => count === 1 ? first.promise : second.promise });
    h.shares.value = '12'; const saving = h.save();
    h.shares.value = '14'; h.cost.value = '130'; const queued = h.save({ viaBlur: true });
    assert.equal(h.puts.length, 1);
    first.resolve({ ok: true }); await flush();
    assert.equal(h.puts.length, 2); assert.equal(h.shares.defaultValue, '12');
    assert.equal(h.shares.value, '14'); assert.equal(h.cost.defaultValue, '100'); assert.equal(h.cost.value, '130');
    assert.equal(h.puts[1].shares, 14); assert.equal(h.puts[1].avg_cost, 130);
    assert.equal('hold_class' in h.puts[1], false);
    second.resolve({ ok: true }); await Promise.all([saving, queued]);
    assert.equal(h.shares.defaultValue, '14'); assert.equal(h.cost.defaultValue, '130');
    assert.equal(h.context.manageHoldingSaves.size, 0); assert.equal(h.statuses.at(-1), 'saved');
});

test('cancelled reduction sends nothing, restores only that shares draft and keeps cost unsaved', async () => {
    const h = harness({ prompt: async () => null });
    h.shares.value = '8'; h.cost.value = '110'; await h.save({ viaBlur: true });
    assert.equal(h.puts.length, 0); assert.equal(h.shares.value, '10');
    assert.equal(h.cost.value, '110'); assert.equal(h.cost.defaultValue, '100');
    assert.equal(h.statuses.at(-1), 'draft'); assert.equal(h.classes.has('is-saving'), false);
});

test('reduction waits for blur and cancellation cannot erase a newer shares draft', async () => {
    const dialog = deferred(); const h = harness({ prompt: () => dialog.promise });
    h.shares.value = '8'; await h.save(); assert.equal(h.prompts.length, 0);
    const saving = h.save({ viaBlur: true }); await flush();
    h.shares.value = '7'; dialog.resolve(null); await saving;
    assert.equal(h.shares.value, '7'); assert.equal(h.shares.defaultValue, '10');
    assert.equal(h.puts.length, 0); assert.equal(h.statuses.at(-1), 'draft');
});

test('old saving response does not rebaseline newer cost text as saved', async () => {
    const response = deferred(); const h = harness({ response: () => response.promise });
    h.cost.value = '120'; const saving = h.save(); h.cost.value = '130';
    response.resolve({ ok: true }); await saving;
    assert.equal(h.cost.defaultValue, '120'); assert.equal(h.cost.value, '130');
    assert.equal(h.statuses.at(-1), 'draft');
});

test('empty average cost preserves the endpoint no-change policy and displays its saved value', async () => {
    const h = harness(); h.cost.value = ''; h.shares.value = '12'; await h.save();
    assert.equal('avg_cost' in h.puts[0], false); assert.equal(h.cost.value, '100');
    assert.equal(h.cost.defaultValue, '100'); assert.equal(h.shares.defaultValue, '12');
});

test('management refresh keeps dirty card inputs and their keyboard focus', () => {
    const h = harness(); h.cost.value = '130';
    const list = { kept: [], querySelectorAll: () => [h.card],
        appendChild(node) { this.kept.push(node); }, insertAdjacentHTML() { throw new Error('Must keep the dirty card'); } };
    h.card.id = 'manage-row-7'; h.card.contains = element => element === h.cost;
    let focused = 0; h.cost.focus = () => { focused++; };
    const oldGet = h.context.document.getElementById;
    h.context.document.activeElement = h.cost;
    h.context.document.getElementById = id => id === 'manage-holdings-list' ? list
        : id === 'manage-holdings-empty' ? { hidden: true } : oldGet(id);
    h.context.updateManageStatsPill = () => {}; h.context.filterManageHoldings = () => {};
    vm.runInContext(extract('renderManageHoldingsData'), h.context);
    h.context.renderManageHoldingsData([{ id: 7, shares: 10, avg_cost: 100 }]);
    assert.equal(list.kept[0], h.card); assert.equal(h.cost.value, '130');
    assert.equal(h.cost.defaultValue, '100'); assert.equal(focused, 1);
});

test('dependent removal waits for an active edit or unresolved saved state', async () => {
    const pending = deferred(); const h = harness({ response: () => pending.promise,
        readback: async () => { throw new Error('unreachable'); } });
    h.context.latestHoldings = []; h.context.HoldingRemovalLogic = { buildPayload: x => x };
    vm.runInContext(extract('removeHolding'), h.context);
    h.shares.value = '12'; const saving = h.save();
    await h.context.removeHolding(7, 'TEST');
    assert.equal(h.prompts.length, 0); assert.equal(h.puts.length, 1);
    pending.reject(new Error('lost')); await saving;
    await h.context.removeHolding(7, 'TEST');
    assert.equal(h.prompts.length, 0); assert.equal(h.puts.length, 1);
    assert.match(h.messages.at(-1).text, /No removal was sent/);
});

test('a manager GET begun during a slow save cannot repaint its older baseline afterward', async () => {
    const put = deferred(), get = deferred();
    const h = harness({ response: () => put.promise, readback: () => get.promise });
    const list = { querySelector: () => h.card, children: [h.card] };
    const oldGet = h.context.document.getElementById;
    h.context.document.getElementById = id => id === 'manage-holdings-list' ? list : oldGet(id);
    let rendered = 0; h.context.renderManageHoldingsData = () => { rendered++; };
    vm.runInContext(extract('loadManageHoldings'), h.context);
    h.cost.value = '120'; const saving = h.save();
    const loading = h.context.loadManageHoldings({ preserveExisting: true });
    put.resolve({ ok: true }); await saving;
    get.resolve({ holdings: [{ id: 7, shares: 10, avg_cost: 100 }] }); await loading;
    assert.equal(rendered, 0); assert.equal(h.cost.defaultValue, '120'); assert.equal(h.cost.value, '120');
});

test('late old commit after an old-state readback rejects a newer stale-baseline edit and retains its draft', async () => {
    let stored = { id: 7, ticker: 'TEST', shares: 10, avg_cost: 100 };
    let latePayload;
    const h = harness({ response: async (count, payload) => {
        if (count === 1) { latePayload = payload; throw new Error('response lost while request is still pending'); }
        assert.equal(payload.expected_shares, 10); assert.equal(payload.expected_avg_cost, 100);
        return { ok: false, status: 409, json: async () => ({ detail: { code: 'holding_changed', message: 'Saved holding changed' } }) };
    }, readback: async url => url.endsWith('/holdings') ? { holdings: [{ ...stored }] } : { trades: [] } });
    h.shares.value = '12'; await h.save();
    assert.equal(h.shares.defaultValue, '10'); // First readback precedes the original commit.
    assert.equal(latePayload.expected_shares, 10); assert.equal(latePayload.expected_avg_cost, 100);
    stored.shares = 12; // The original PUT obtains the backend writer reservation late.
    h.shares.value = '14'; h.cost.value = '130'; await h.save({ viaBlur: true });
    assert.equal(h.puts.length, 2); assert.equal(stored.shares, 12); assert.equal(stored.avg_cost, 100);
    assert.equal(h.shares.defaultValue, '12'); assert.equal(h.cost.defaultValue, '100');
    assert.equal(h.shares.value, '14'); assert.equal(h.cost.value, '130');
    assert.equal(h.statuses.at(-1), 'draft'); assert.match(h.messages.at(-1).text, /holding changed before this edit/);
    assert.equal(h.context.manageUnknownEdits.size, 0);
});

test('guarded manager edits preserve exact sub-cent saved basis in their precondition', async () => {
    const h = harness(); h.cost.value = h.cost.defaultValue = '3.125'; h.shares.value = '12';
    await h.save(); assert.equal(h.puts[0].expected_avg_cost, 3.125); assert.equal(h.puts[0].expected_shares, 10);
});

test('save status exposes persistent unknown feedback and an old saved timer cannot clear it', () => {
    const el = { dataset: {}, title: '', innerHTML: '', classList: { add() {}, remove() {} } };
    const feedback = { hidden: true, textContent: '' }, timers = [];
    const context = { document: { querySelector: () => el, getElementById: () => feedback },
        manageLucide: () => '<svg aria-hidden="true"></svg>', window: { setTimeout: callback => timers.push(callback) } };
    vm.createContext(context); vm.runInContext(extract('setManageSaveStatus'), context);
    context.setManageSaveStatus(7, 'saved'); context.setManageSaveStatus(7, 'unknown'); timers[0]();
    assert.equal(el.dataset.saveState, 'unknown'); assert.equal(feedback.hidden, false);
    assert.match(feedback.textContent, /Status unknown/); assert.match(feedback.textContent, /before another change/);
    assert.match(source, /id="manage-edit-feedback-\$\{h.id\}" role="status" hidden/);
    context.setManageSaveStatus(7, 'saved'); assert.equal(feedback.hidden, true); assert.equal(el.title, '');
});

function installRemoval(h) {
    h.context.latestHoldings = [];
    h.context.HoldingRemovalLogic = require('../../static/js/holding-removal-logic.js');
    h.context.updateHoldingsFilterCounts = () => {}; h.context.renderHoldings = () => {};
    h.context.applyRemovedHoldingState = () => {};
    vm.runInContext(extract('removeHolding'), h.context);
}

test('late PUT before removal rejects stale sale consent and reads back without retrying DELETE', async () => {
    let stored = { id: 7, ticker: 'TEST', shares: 10, avg_cost: 3.125 };
    const h = harness({ response: async () => { throw new Error('lost PUT response'); },
        readback: async url => url.endsWith('/holdings') ? { holdings: [{ ...stored }] } : { trades: [] } });
    h.cost.value = h.cost.defaultValue = '3.125'; h.shares.value = '12'; await h.save();
    assert.equal(h.shares.defaultValue, '10');
    stored.shares = 12; // Original guarded PUT commits after the first readback.
    installRemoval(h); const deletes = [];
    h.context.PortfolioWorkspace.response = async (_url, init) => {
        assert.equal(init.method, 'DELETE'); deletes.push(JSON.parse(init.body));
        return { ok: false, status: 409, json: async () => ({ detail: { code: 'holding_changed' } }) };
    };
    let realizedReads = 0; h.context.renderPnlData = async () => { realizedReads++; };
    await h.context.removeHolding(7, 'TEST');
    assert.equal(h.prompts.at(-1).soldQty, 10); assert.equal(deletes.length, 1);
    assert.equal(deletes[0].expected_shares, 10); assert.equal(deletes[0].expected_avg_cost, 3.125);
    assert.equal(deletes[0].sale_price, 120); assert.equal(deletes[0].sale_currency, 'USD');
    assert.equal(h.shares.defaultValue, '12'); assert.equal(realizedReads, 1);
    assert.match(h.messages.at(-1).text, /Review it and confirm again/);
    assert.match(h.messages.at(-1).text, /No removal was retried/);
    assert.equal(stored.shares, 12); // Conflict made no sale or holding change.
});

test('removal arriving first carries reviewed guards and a later archived-holding conflict cannot resubmit an edit', async () => {
    const h = harness(); installRemoval(h);
    const deletes = [];
    h.context.PortfolioWorkspace.response = async (_url, init) => {
        deletes.push(JSON.parse(init.body)); return { ok: true, status: 200 };
    };
    await h.context.removeHolding(7, 'TEST');
    assert.equal(deletes.length, 1); assert.equal(h.prompts.at(-1).soldQty, 10);
    assert.equal(deletes[0].expected_shares, 10); assert.equal(deletes[0].expected_avg_cost, 100);
    // A guarded PUT rejected after DELETE must reconcile the archived result, never retry.
    h.context.PortfolioWorkspace.response = async () => ({ ok: false, status: 409,
        json: async () => ({ detail: { code: 'holding_archived' } }) });
    h.context.PortfolioWorkspace.json = async url => url.endsWith('/holdings') ? { holdings: [] } : { trades: [{ shares_sold: 10 }] };
    h.shares.value = '12'; await h.save();
    assert.equal(h.statuses.at(-1), 'unknown'); assert.equal(h.context.manageUnknownEdits.has(7), true);
    assert.equal(deletes.length, 1);
    assert.match(h.messages.at(-1).text, /No retry was sent/);
});

for (const readable of [false, true]) test(`edit readback (${readable ? 'saved' : 'unreachable'}) retires a concurrent manager GET and releases its loading blocker`, async () => {
    const put = deferred(), managerGet = deferred(); let reads = 0;
    const h = harness({ response: () => put.promise,
        readback: () => ++reads === 1 ? managerGet.promise : readable
            ? Promise.resolve({ holdings: [{ id: 7, shares: 10, avg_cost: 100 }] })
            : Promise.reject(new Error('readback unreachable')) });
    const list = { querySelector: () => h.card, children: [h.card] }, loading = new Set();
    const popover = { classList: { add: name => loading.add(name), remove: name => loading.delete(name) } };
    const oldGet = h.context.document.getElementById;
    h.context.document.getElementById = id => id === 'manage-holdings-list' ? list
        : id === 'portfolioModal' ? popover : oldGet(id);
    h.context.renderManageHoldingsData = () => { throw new Error('Retired GET must not repaint'); };
    vm.runInContext(extract('loadManageHoldings'), h.context);
    h.cost.value = '120'; const saving = h.save();
    const loadingRequest = h.context.loadManageHoldings({ preserveExisting: true });
    assert.equal(loading.has('is-loading'), true);
    put.reject(new Error('lost response')); await saving;
    assert.equal(h.statuses.at(-1), readable ? 'draft' : 'unknown'); assert.equal(loading.has('is-loading'), false);
    managerGet.resolve({ holdings: [{ id: 7, shares: 10, avg_cost: 100 }] }); await loadingRequest;
    assert.equal(loading.has('is-loading'), false); assert.equal(h.cost.value, '120');
});
