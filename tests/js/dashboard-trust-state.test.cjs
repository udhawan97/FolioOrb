const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const dashboardPath = path.resolve(__dirname, "../../static/js/dashboard.js");
const dashboardSource = fs.readFileSync(dashboardPath, "utf8");

function extractFunction(name) {
    const marker = `function ${name}(`;
    const markerStart = dashboardSource.indexOf(marker);
    assert.notEqual(markerStart, -1, `${name} must remain a named dashboard contract`);
    const start = dashboardSource.slice(markerStart - 6, markerStart) === "async "
        ? markerStart - 6
        : markerStart;

    const paramsStart = dashboardSource.indexOf("(", start);
    let paramsDepth = 0;
    let paramsEnd = -1;
    for (let index = paramsStart; index < dashboardSource.length; index += 1) {
        if (dashboardSource[index] === "(") paramsDepth += 1;
        if (dashboardSource[index] === ")") paramsDepth -= 1;
        if (paramsDepth === 0) {
            paramsEnd = index;
            break;
        }
    }
    const bodyStart = dashboardSource.indexOf("{", paramsEnd);
    let depth = 0;
    for (let index = bodyStart; index < dashboardSource.length; index += 1) {
        if (dashboardSource[index] === "{") depth += 1;
        if (dashboardSource[index] === "}") depth -= 1;
        if (depth === 0) return dashboardSource.slice(start, index + 1);
    }
    throw new Error(`Unable to extract ${name}`);
}

function loadFunctions(names, context = {}) {
    const sandbox = { ...context };
    vm.createContext(sandbox);
    const exportsSource = names.map(name => `${name}`).join(", ");
    vm.runInContext(
        `${names.map(extractFunction).join("\n")}\nglobalThis.contracts = { ${exportsSource} };`,
        sandbox,
    );
    return sandbox.contracts;
}

function perfCalloutDocument() {
    const icon = { className: "" };
    const title = { textContent: "" };
    const body = { textContent: "" };
    const callout = {
        style: { display: "none" },
        querySelector(selector) {
            return {
                ".perf-callout-icon": icon,
                ".perf-callout-title": title,
                ".perf-callout-body": body,
            }[selector];
        },
    };
    return {
        icon,
        title,
        body,
        document: {
            getElementById(id) {
                return id === "perf-stale-callout" ? callout : null;
            },
        },
    };
}

test("partial realized metadata maps to an unavailable performance state", () => {
    const { describeRealizedQuality } = loadFunctions(["describeRealizedQuality"]);

    const excluded = describeRealizedQuality({
        realized_data_quality: "partial",
        excluded_realized_trade_count: 2,
    });
    assert.equal(excluded.isPartial, true);
    assert.equal(excluded.excludedCount, 2);
    assert.match(excluded.performanceTitle, /unavailable/i);
    assert.match(excluded.performanceBody, /2 realized trades are excluded/i);
    assert.match(excluded.performanceBody, /USD sale details/i);
    assert.doesNotMatch(excluded.performanceBody, /No performance history yet/i);
    assert.match(excluded.realizedNotice, /Partial realized history/i);

    const metadataOnly = describeRealizedQuality({ realized_data_quality: "partial" });
    assert.equal(metadataOnly.isPartial, true);
    assert.match(metadataOnly.performanceBody, /could not be verified/i);
});

test("complete realized metadata preserves the established empty-state copy", () => {
    const { describeRealizedQuality } = loadFunctions(["describeRealizedQuality"]);
    const complete = describeRealizedQuality({
        realized_data_quality: "complete",
        excluded_realized_trade_count: 0,
    });

    assert.equal(complete.isPartial, false);
    assert.equal(complete.performanceTitle, "No performance history yet");
    assert.match(complete.realizedEmpty, /No realized trades yet/);
});

test("the performance callout renders the partial disclosure instead of no-data copy", () => {
    const fake = perfCalloutDocument();
    const { describeRealizedQuality, updatePerfCallout } = loadFunctions(
        ["describeRealizedQuality", "updatePerfCallout"],
        { document: fake.document },
    );
    const disclosure = describeRealizedQuality({
        realized_data_quality: "partial",
        excluded_realized_trade_count: 1,
    });

    updatePerfCallout("partial", 0, disclosure);

    assert.match(fake.title.textContent, /unavailable/i);
    assert.match(fake.body.textContent, /1 realized trade is excluded/i);
    assert.doesNotMatch(fake.title.textContent, /No performance history yet/i);
    assert.match(fake.icon.className, /exclamation/);
});

test("partial performance clears a previously rendered portfolio chart first", async () => {
    let destroyed = 0;
    const context = {
        latestPnlDisclosure: { isPartial: true },
        pnlChart: { destroy: () => { destroyed += 1; } },
        performanceRange: "max",
        latestPnlHasUserData: true,
        latestPnlIsStale: false,
        latestPnlStaleDays: 0,
        latestPnlHistory: [],
        updatePerfCallout: () => {},
        loadMarketReferenceChart: async () => {},
        hidePerfCallout: () => {},
        renderPnlChart: () => {},
        filterHistoryForPerformanceRange: value => value,
    };
    const { renderCurrentPerformanceChart } = loadFunctions(
        ["renderCurrentPerformanceChart"],
        context,
    );

    await renderCurrentPerformanceChart();

    assert.equal(destroyed, 1);
});

test("the realized table renders a partial notice even when no trusted rows remain", () => {
    const tbody = { innerHTML: "", insertRow() { throw new Error("no trade rows expected"); } };
    const document = {
        getElementById(id) {
            return id === "realized-table" ? tbody : null;
        },
    };
    const { describeRealizedQuality, renderRealizedTable } = loadFunctions(
        ["describeRealizedQuality", "renderRealizedTable"],
        { document },
    );
    const disclosure = describeRealizedQuality({
        realized_data_quality: "partial",
        excluded_realized_trade_count: 1,
    });

    renderRealizedTable([], disclosure);

    assert.match(tbody.innerHTML, /Partial realized history/i);
    assert.match(tbody.innerHTML, /1 trade is excluded/i);
    assert.doesNotMatch(tbody.innerHTML, /No realized trades yet/i);
});

test("portfolio sync disclosure warns for every partial-quality source", () => {
    const { describePortfolioSyncQuality } = loadFunctions(["describePortfolioSyncQuality"]);

    const complete = describePortfolioSyncQuality({
        data_quality: "complete",
        realized_data_quality: "complete",
    });
    assert.deepEqual(
        { isWarning: complete.isWarning, text: complete.text },
        { isWarning: false, text: "Prices, P&L and holdings pulled from market data" },
    );

    const missing = describePortfolioSyncQuality({
        data_quality: "partial",
        missing_tickers: ["MSFT"],
    });
    assert.equal(missing.isWarning, true);
    assert.match(missing.text, /Partial data/i);
    assert.match(missing.text, /MSFT/);
    assert.match(missing.text, /because it has no usable USD price/i);

    const foreign = describePortfolioSyncQuality({
        data_quality: "partial",
        foreign_currency_tickers: ["VOD.L"],
    });
    assert.equal(foreign.isWarning, true);
    assert.match(foreign.text, /because it is priced in another currency/i);

    const realized = describePortfolioSyncQuality({
        data_quality: "partial",
        realized_data_quality: "partial",
        excluded_realized_trade_count: 2,
    });
    assert.equal(realized.isWarning, true);
    assert.match(realized.text, /realized P&L excludes 2 trades/i);

    const metadataOnly = describePortfolioSyncQuality({ data_quality: "partial" });
    assert.equal(metadataOnly.isWarning, true);
    assert.match(metadataOnly.text, /some portfolio figures are unavailable/i);
});

test("dashboard loaders consume the quality disclosures", () => {
    assert.match(dashboardSource, /describeRealizedQuality\(data\)/);
    assert.match(dashboardSource, /renderRealizedTable\(data\.trades \|\| \[\], realizedDisclosure\)/);
    assert.match(dashboardSource, /describePortfolioSyncQuality\(data\)/);
});

test("canonical holdings reconcile an interrupted removal without guessing", async () => {
    const calls = [];
    const PortfolioWorkspace = {
        async json(url) {
            if (url === "/api/portfolio/holdings") {
                return { holdings: [{ id: 8, ticker: "MSFT" }] };
            }
            if (url === "/api/portfolio/pnl") return { trades: [], history: [] };
            throw new Error(`Unexpected URL ${url}`);
        },
        invalidate() { calls.push("invalidate"); },
    };
    const { reconcileHoldingRemovalOutcome } = loadFunctions(
        ["resolveHoldingRemovalReconciliation", "reconcileHoldingRemovalOutcome"],
        {
            PortfolioWorkspace,
            renderManageHoldingsData: holdings => calls.push(["holdings", holdings]),
            renderPnlData: async data => calls.push(["pnl", data]),
            applyRemovedHoldingState: (id, ticker) => calls.push(["removed", id, ticker]),
            loadPortfolioValueAfterMutation: async () => calls.push("valuation"),
            console: { warn: () => {} },
        },
    );

    const outcome = await reconcileHoldingRemovalOutcome(7, "VTI");

    assert.equal(outcome.status, "removed");
    assert.equal(outcome.realizedRefreshed, true);
    assert.deepEqual(calls[0], "invalidate");
    assert.equal(calls.some(call => Array.isArray(call) && call[0] === "removed"), true);
    assert.equal(calls.some(call => Array.isArray(call) && call[0] === "pnl"), true);
    assert.equal(calls.includes("valuation"), true);
});

test("canonical holdings distinguish still-active from an unknown outcome", async () => {
    const baseContext = {
        renderManageHoldingsData: () => {},
        renderPnlData: async () => {},
        applyRemovedHoldingState: () => { throw new Error("must not remove active state"); },
        loadPortfolioValueAfterMutation: async () => {},
        console: { warn: () => {} },
    };

    const activeContracts = loadFunctions(
        ["resolveHoldingRemovalReconciliation", "reconcileHoldingRemovalOutcome"],
        {
            ...baseContext,
            PortfolioWorkspace: {
                json: async url => url.endsWith("/holdings")
                    ? { holdings: [{ id: 7, ticker: "VTI" }] }
                    : { trades: [], history: [] },
                invalidate: () => {},
            },
        },
    );
    const active = await activeContracts.reconcileHoldingRemovalOutcome(7, "VTI");
    assert.equal(active.status, "active");

    let pnlRendered = false;
    const unknownContracts = loadFunctions(
        ["resolveHoldingRemovalReconciliation", "reconcileHoldingRemovalOutcome"],
        {
            ...baseContext,
            PortfolioWorkspace: {
                json: async url => {
                    if (url.endsWith("/holdings")) throw new Error("offline");
                    return { trades: [], history: [] };
                },
                invalidate: () => {},
            },
            renderPnlData: async () => { pnlRendered = true; },
        },
    );
    const unknown = await unknownContracts.reconcileHoldingRemovalOutcome(7, "VTI");
    assert.equal(unknown.status, "unknown");
    assert.equal(unknown.realizedRefreshed, true);
    assert.equal(pnlRendered, true);
});

test("removal outcome copy never calls an interrupted request unchanged", () => {
    const { describeHoldingRemovalOutcome } = loadFunctions(["describeHoldingRemovalOutcome"]);

    const unknown = describeHoldingRemovalOutcome("VTI", {
        status: "unknown",
        realizedRefreshed: false,
    });
    assert.match(unknown.message, /Couldn't confirm whether VTI was removed/i);
    assert.match(unknown.message, /Refresh before trying again/i);
    assert.doesNotMatch(unknown.message, /unchanged/i);

    const active = describeHoldingRemovalOutcome("VTI", {
        status: "active",
        realizedRefreshed: true,
    });
    assert.match(active.message, /still active/i);
    assert.match(active.message, /refreshed/i);

    const removed = describeHoldingRemovalOutcome("VTI", {
        status: "removed",
        realizedRefreshed: false,
    });
    assert.match(removed.message, /was removed/i);
    assert.match(removed.message, /realized history couldn't refresh/i);
});

test("removeHolding reconciles a thrown request before reporting its outcome", async () => {
    const toasts = [];
    let reconciliationCalls = 0;
    const { removeHolding } = loadFunctions(
        ["describeHoldingRemovalOutcome", "removeHolding"],
        {
            manageHoldingsCache: [{ id: 7, ticker: "VTI", shares: 2 }],
            latestHoldings: [],
            promptSaleDetails: async () => ({ sale_price: 100, sale_date: "2026-08-31" }),
            HoldingRemovalLogic: {
                buildPayload: value => value,
                requiresExplicitPrice: () => false,
            },
            PortfolioWorkspace: {
                response: async () => { throw new TypeError("connection lost"); },
            },
            reconcileHoldingRemovalOutcome: async () => {
                reconciliationCalls += 1;
                return { status: "unknown", realizedRefreshed: false };
            },
            showToast: (message, level) => toasts.push([message, level]),
            console: { warn: () => {} },
        },
    );

    await removeHolding(7, "VTI");

    assert.equal(reconciliationCalls, 1);
    assert.equal(toasts.length, 1);
    assert.match(toasts[0][0], /Couldn't confirm whether VTI was removed/i);
    assert.match(toasts[0][0], /Refresh before trying again/i);
    assert.doesNotMatch(toasts[0][0], /holding kept unchanged/i);
});

test("removeHolding reconciles an ambiguous server error before reporting", async () => {
    const toasts = [];
    let reconciliationCalls = 0;
    const { removeHolding } = loadFunctions(
        ["describeHoldingRemovalOutcome", "removeHolding"],
        {
            manageHoldingsCache: [{ id: 7, ticker: "VTI", shares: 2 }],
            latestHoldings: [],
            promptSaleDetails: async () => ({ sale_price: 100, sale_date: "2026-08-31" }),
            HoldingRemovalLogic: {
                buildPayload: value => value,
                requiresExplicitPrice: () => false,
            },
            PortfolioWorkspace: {
                response: async () => ({
                    ok: false,
                    status: 500,
                    json: async () => ({ detail: "response failed after commit" }),
                }),
            },
            reconcileHoldingRemovalOutcome: async () => {
                reconciliationCalls += 1;
                return { status: "removed", realizedRefreshed: true };
            },
            showToast: (message, level) => toasts.push([message, level]),
            console: { warn: () => {} },
        },
    );

    await removeHolding(7, "VTI");

    assert.equal(reconciliationCalls, 1);
    assert.deepEqual(toasts, [[
        "VTI was removed — refreshed saved holdings and realized history",
        "warning",
    ]]);
});

test("a deterministic HTTP conflict keeps its server-proven no-mutation message", async () => {
    const toasts = [];
    let reconciliationCalls = 0;
    const { removeHolding } = loadFunctions(
        ["describeHoldingRemovalOutcome", "removeHolding"],
        {
            manageHoldingsCache: [{ id: 7, ticker: "VTI", shares: 2 }],
            latestHoldings: [],
            promptSaleDetails: async () => ({ sale_price: 100, sale_date: "2026-08-31" }),
            HoldingRemovalLogic: {
                buildPayload: value => value,
                requiresExplicitPrice: () => false,
            },
            PortfolioWorkspace: {
                response: async () => ({
                    ok: false,
                    status: 409,
                    json: async () => ({ detail: "Sale price unavailable — holding kept unchanged" }),
                }),
            },
            reconcileHoldingRemovalOutcome: async () => {
                reconciliationCalls += 1;
                return { status: "unknown", realizedRefreshed: false };
            },
            apiErrorMessage: (error, fallback) => error.detail || fallback,
            showToast: (message, level) => toasts.push([message, level]),
            console: { warn: () => {} },
        },
    );

    await removeHolding(7, "VTI");

    assert.equal(reconciliationCalls, 0);
    assert.deepEqual(toasts[0], ["Sale price unavailable — holding kept unchanged", "danger"]);
});
