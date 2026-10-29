const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../../static/js/dashboard.js'), 'utf8');
function extract(name) {
    const start = source.indexOf(`function ${name}(`);
    let depth = 0;
    const body = source.indexOf(') {', start) + 2;
    for (let i = body; i < source.length; i++) {
        if (source[i] === '{') depth++;
        if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
    }
    throw new Error(`Missing ${name}`);
}
function harness() {
    let resolve, reject, config;
    const read = new Promise((yes, no) => { resolve = yes; reject = no; });
    const input = { dataset: {}, addEventListener() {} };
    const painted = [], background = [];
    const context = {
        document: { getElementById: id => id === 'import-csv-input' ? input : null },
        window: { sessionStorage: {} }, manageHoldingsRequestId: 0,
        PortfolioWorkspace: { id: 1, json: () => read },
        createCsvPreview: options => { config = options; },
        renderManageHoldingsData: rows => painted.push(rows),
        refreshPortfolioMutationInBackground: () => background.push(true),
    };
    vm.createContext(context);
    vm.runInContext(['initCsvImport', 'invalidateManageHoldingsLoad'].map(extract).join('\n'), context);
    context.initCsvImport();
    return { context, painted, background, resolve, reject, refresh: () => config.refresh(1) };
}
for (const scenario of ['success', 'failed', 'scope-changed', 'superseded']) {
    test(`CSV refresh ${scenario} fences stale manager paints`, async () => {
        const h = harness();
        const refreshing = h.refresh();
        if (scenario === 'failed') h.reject(new Error('offline'));
        else {
            if (scenario === 'scope-changed') h.context.PortfolioWorkspace.id = 2;
            if (scenario === 'superseded') h.context.invalidateManageHoldingsLoad();
            h.resolve({ portfolio_id: 1, holdings: [{ id: 7 }] });
        }
        if (scenario === 'success') {
            await refreshing;
            assert.equal(h.painted.length, 1);
            assert.equal(h.background.length, 1);
        } else {
            await assert.rejects(refreshing);
            assert.equal(h.painted.length, 0);
            assert.equal(h.background.length, 0);
        }
    });
}
for (const state of ['dirty', 'pending', 'unknown']) {
    test(`CSV refresh renderer retains ${state} card, baseline and focus`, () => {
        const field = { value: '12', defaultValue: '10', focus(options) { this.restored = options.preventScroll; } };
        const card = { id: 'manage-row-7', contains: element => element === field };
        const nodes = [card];
        const list = {
            querySelectorAll: () => nodes.slice(),
            set innerHTML(value) { assert.equal(value, ''); nodes.length = 0; },
            appendChild: node => nodes.push(node),
            insertAdjacentHTML: (_, html) => nodes.push(html),
        };
        const context = {
            document: { activeElement: field, getElementById: id => id === 'manage-holdings-list' ? list : null },
            manageHoldingSaves: new Map(state === 'pending' ? [[7, {}]] : []),
            manageUnknownEdits: new Map(state === 'unknown' ? [[7, {}]] : []),
            holdingEditHasDraft: () => state === 'dirty', updateManageStatsPill() {}, filterManageHoldings() {},
            renderManageHoldingCard: holding => `new-${holding.id}`, bindManageHoldingInputs() {},
        };
        vm.createContext(context);
        vm.runInContext(extract('renderManageHoldingsData'), context);
        context.renderManageHoldingsData([{ id: 7, shares: 10 }, { id: 8, shares: 1 }]);
        assert.equal(nodes[0], card);
        assert.equal(nodes[1], 'new-8');
        assert.equal(field.value, '12');
        assert.equal(field.defaultValue, '10');
        assert.equal(field.restored, true);
        assert.equal(context.manageHoldingSaves.size, state === 'pending' ? 1 : 0);
        assert.equal(context.manageUnknownEdits.size, state === 'unknown' ? 1 : 0);
    });
}
