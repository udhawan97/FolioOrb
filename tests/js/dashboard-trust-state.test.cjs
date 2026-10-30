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
    const sandbox = { manageHoldingSaves: new Map(), manageUnknownEdits: new Map(), invalidateManageHoldingsLoad() {}, ...context };
    vm.createContext(sandbox);
    const exportsSource = names.map(name => `${name}`).join(", ");
    vm.runInContext(
        `${names.map(extractFunction).join("\n")}\nglobalThis.contracts = { ${exportsSource} };`,
        sandbox,
    );
    return sandbox.contracts;
}

function valuationHarness(names, context = {}) {
    const sandbox = { latestPortfolioValueData: null, ...context };
    vm.createContext(sandbox);
    const formatters = dashboardSource.slice(0, dashboardSource.indexOf("const TICKER_PATTERN"));
    vm.runInContext(`${formatters}\n${names.map(extractFunction).join("\n")}\nglobalThis.contracts = { ${names.join(", ")} };`, sandbox);
    return { ...sandbox.contracts, sandbox };
}

const htmlText = (parts, ...values) => parts.reduce((text, part, index) => text + part + (values[index] ?? ""), "");

test("native holding prices retain units while unavailable values stay unknown", () => {
    const { formatHoldingMoney, isReportingHolding } = valuationHarness(["formatHoldingMoney", "isReportingHolding"]);
    const usd = { current_value: 100, currency: "USD", reporting_eligible: true };
    const foreign = { current_value: 1000, currency: "GBp", reporting_eligible: false };
    assert.equal(formatHoldingMoney(usd, 100), "$100.00");
    for (const currency of ["usd", "Usd", "USD"]) {
        assert.equal(formatHoldingMoney({ ...usd, currency }, 100), "$100.00");
        assert.equal(isReportingHolding({ ...usd, currency }), true);
    }
    assert.equal(formatHoldingMoney(foreign, 1000), "1,000.00 GBp");
    assert.equal(formatHoldingMoney({ currency: "CAD" }, 12.5), "12.50 CAD");
    assert.equal(formatHoldingMoney({ quote_available: false }, null), "Unavailable");
    assert.equal(formatHoldingMoney(usd, null), "Unavailable");
    assert.equal(isReportingHolding(usd), true);
    assert.equal(isReportingHolding(foreign), false);
    assert.equal(isReportingHolding({ ...usd, is_watchlist: true }), false);
    assert.equal(isReportingHolding({ ...usd, current_value: null }), false);
    assert.equal(isReportingHolding({ current_value: 1000, currency: "GBp" }), false);
});

test("authoritative unavailable loads replace cached membership and recover without stale rows", async () => {
    const elements = new Map();
    const get = id => {
        if (!elements.has(id)) elements.set(id, { textContent: "", innerHTML: "", dataset: {}, classList: { add() {}, remove() {} } });
        return elements.get(id);
    };
    let response;
    let cached;
    const rendered = [];
    const { sandbox, loadPortfolioValue } = valuationHarness([
        "loadPortfolioValue", "renderPortfolioValueData", "describePortfolioSyncQuality", "renderTotalReturn",
    ], {
        document: { getElementById: get }, html: htmlText, console,
        PortfolioWorkspace: { json: async () => response },
        _portfolioValuePromise: null, _hasLoadedOnce: false,
        latestHoldings: [{ id: 99, ticker: "REMOVED", shares: 1 }], latestTrendData: {},
        dashboardZone: "overview", colorClass: () => "text-secondary",
        formatSignedCurrency: value => `$${value.toFixed(2)}`,
        renderHeroPnl() {}, updateHoldingsFilterCounts() {}, renderAllocation() {}, renderPortfolioSnapshot() {},
        loadTrendData: async () => ({}), renderHoldings: () => rendered.push(true),
        scheduleAllocationFocusPanelRefresh() {}, repaintOpenVerdictSparklines() {}, flashValue() {},
        persistPortfolioValueCache: data => { cached = data; },
    });
    const missing = { id: 1, ticker: "VTI", shares: 2, quote_available: false,
        reporting_eligible: false, current_price: null, current_value: null };
    response = { degraded: true, data_quality: "unavailable", missing_tickers: ["VTI"],
        holdings: [missing], total_value: 0, total_return: 0, realized_gain: 0 };
    await loadPortfolioValue();
    assert.equal(sandbox.latestHoldings.length, 1);
    assert.equal(sandbox.latestHoldings[0].id, 1);
    assert.equal(cached.holdings[0].ticker, "VTI");
    assert.equal(get("holding-count").textContent, 1);
    assert.equal(get("total-value").textContent, "Unavailable");
    assert.equal(get("total-return").innerHTML, "Unavailable");
    assert.match(get("portfolio-coverage-notice").textContent, /VTI/);
    assert.match(get("hud-pop-sync-sub").textContent, /VTI/);
    assert.ok(rendered.length);

    response = { data_quality: "partial", foreign_currency_tickers: ["VOD.L"],
        holdings: [{ ...missing, ticker: "VOD.L", currency: "GBp", current_value: 10000 },
            { id: 2, ticker: "USD", shares: 1, currency: "USD", reporting_eligible: true, current_value: 100 }],
        total_value: 100, realized_gain: 0,
        best_performer: { ticker: "USD", day_change_pct: 2 },
        worst_performer: { ticker: "USD", day_change_pct: 2 } };
    await loadPortfolioValue();
    assert.equal(get("total-value").textContent, "$100.00");
    assert.equal(get("total-value-label").textContent, "Known USD value");
    assert.equal(get("largest-holding").dataset.ticker, "USD");
    assert.equal(get("best-performer").textContent, "Unavailable");
    assert.equal(get("worst-performer").textContent, "Unavailable");
    assert.equal(get("best-performer").dataset.ticker, "");
    assert.equal(sandbox.latestHoldings.some(row => row.ticker === "VTI"), false);
    assert.equal(cached.holdings.length, 2);

    response = { data_quality: "complete", holdings: [], total_value: 0,
        total_return: 0, total_return_pct: 0, total_unrealized_gain: 0, realized_gain: 0 };
    await loadPortfolioValue();
    assert.equal(get("total-value").textContent, "$0.00");
    assert.equal(get("total-value-label").textContent, "Total value");
    assert.equal(sandbox.latestHoldings.length, 0);
    assert.equal(cached.holdings.length, 0);
    assert.match(get("total-return").innerHTML, /\$0\.00/);
    assert.equal(get("portfolio-coverage-notice").hidden, true);
});

test("USD projections exclude foreign/unpriced rows and withhold incomplete comparisons", () => {
    const usd = { ticker: "USD", shares: 1, current_value: 100, currency: "USD", reporting_eligible: true, daily_value_change: 2 };
    const foreign = { ticker: "GB", current_value: 10000, currency: "GBp", reporting_eligible: false, daily_value_change: 100 };
    const missing = { ticker: "MISSING", current_value: null, reporting_eligible: false };
    const { snapshotActiveHoldings, allocationImpactForHolding, allocationTooltipMetrics, allocationFocusTicker } = valuationHarness([
        "snapshotActiveHoldings", "allocationImpactForHolding", "allocationTooltipMetrics", "allocationFocusTicker", "allocationFocusDefaultTicker",
    ], {
        latestHoldings: [foreign, missing, usd], latestPortfolioValueData: { data_quality: "partial" },
        selectedAllocationTicker: "GB", sortedByAllocation: rows => rows,
    });
    assert.deepEqual(Array.from(snapshotActiveHoldings(), row => row.ticker), ["USD"]);
    assert.equal(allocationImpactForHolding(foreign), null);
    assert.equal(allocationImpactForHolding(missing), null);
    assert.equal(allocationImpactForHolding(usd), 2);
    assert.equal(allocationTooltipMetrics("USD", 100), null);
    assert.equal(allocationFocusTicker(), "USD");
});

test("incomplete coverage cannot fall through to cached range returns in the hero", () => {
    const hero = { textContent: "old", innerHTML: "" };
    const { renderHeroPnl } = valuationHarness(["renderHeroPnl"], {
        document: { getElementById: () => hero }, renderHeroPnlLabel() {},
        dashboardTimeRange: "month", TIME_RANGE: { TODAY: "day" },
        computeHeroPeriodPnl: () => { throw new Error("Incomplete value must not enter range math"); },
    });
    renderHeroPnl({ data_quality: "partial", total_value: 100, total_daily_change_pct: 0 });
    assert.equal(hero.textContent, "--");
    renderHeroPnl({ data_quality: "unavailable", total_value: 0, total_daily_change_pct: 0 });
    assert.equal(hero.textContent, "--");
});

test("an incomplete snapshot withholds cached sector mix and whole-book narrative", () => {
    const messages = [];
    const wrap = { innerHTML: "old narrative" };
    const { renderSnapshotSectors, renderSnapshotIntel } = valuationHarness(["renderSnapshotSectors", "renderSnapshotIntel"], {
        document: { getElementById: id => id === "snapshot-mode-pill" ? null : wrap },
        latestPortfolioValueData: { data_quality: "partial" },
        cachedPortfolioExposure: { sector_exposure: [{ name: "Old sector", weight_pct: 100 }] },
        isLocalIntelligenceMode: () => false, renderSnapshotSectorEmpty: message => messages.push(message),
    });
    renderSnapshotSectors([{ ticker: "USD" }]);
    renderSnapshotIntel([{ ticker: "USD", impact: 1 }], 1, null);
    assert.match(messages[0], /USD coverage is incomplete/);
    assert.equal(wrap.innerHTML, "");
});

test("allocation chart and table clear foreign values and stale selected focus", () => {
    const rows = [];
    const table = { innerHTML: "", classList: { add() {} }, insertRow: () => {
        const row = { dataset: {}, style: { setProperty() {} }, classList: { add() {} }, addEventListener() {} };
        rows.push(row); return row;
    } };
    const chart = { data: { datasets: [{}] }, update() {} };
    const { renderAllocation, sandbox } = valuationHarness(["renderAllocation"], {
        document: { getElementById: () => table }, html: htmlText,
        latestHoldings: [{ ticker: "USD", shares: 1, current_value: 100, currency: "USD", allocation_pct: 100 },
            { ticker: "GB", current_value: 10000, currency: "GBp", reporting_eligible: false },
            { ticker: "MISSING", current_value: null, quote_available: false }],
        latestPortfolioValueData: { data_quality: "partial" }, selectedAllocationTicker: "GB",
        hoveredCenterLabel: "GB", hoveredCenterValue: "$10K", hoveredCenterPct: "90%",
        sortedByAllocation: holdings => holdings, allocationChart: chart,
        chartColor: () => "blue", allocColor: () => "blue", withAlpha: value => value, allocBorderColor: () => "blue",
        updateSortCarets() {}, setAllocationFocus() {}, renderAllocationFocusPanel() {},
    });
    renderAllocation();
    assert.deepEqual(Array.from(chart.data.labels), ["USD"]);
    assert.deepEqual(Array.from(chart.data.datasets[0].data), [100]);
    assert.equal(sandbox.allocationTotal, 100);
    assert.equal(sandbox.selectedAllocationTicker, null);
    assert.equal(sandbox.hoveredCenterLabel, null);
    assert.equal(rows.length, 1);
    assert.match(rows[0].innerHTML, /Unavailable/);
    assert.doesNotMatch(rows[0].innerHTML, /10000|GBp/);
});

test("missing holding rows retain their disclosure control and native cells do not imply dollars", () => {
    const core = {};
    vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../../static/js/core.js"), "utf8")
        + "\nglobalThis.escaping = { html, escapeHtml };", core);
    const cells = new Map();
    const row = { dataset: {}, style: { setProperty() {} }, classList: { toggle() {} },
        querySelector: selector => {
            if (selector === ".trend-cell") return null;
            if (!cells.has(selector)) cells.set(selector, { innerHTML: "" });
            return cells.get(selector);
        } };
    const { updateHoldingRow } = valuationHarness(["updateHoldingRow", "holdingBadgeHtml", "holdingDetailsId", "setCellHtml", "dayChangeHtml"], {
        latestPortfolioValueData: { data_quality: "partial" }, cachedRecommendations: {}, html: core.escaping.html,
        chartColor: () => "blue", earningsBadgeHtml: () => "", escapeHtml: core.escaping.escapeHtml,
        renderTargetCell: () => "", renderAnalystRecCell: () => "", moveBadgeHtml: () => "",
    });
    updateHoldingRow(row, { id: 1, ticker: "MISSING", quote_available: false,
        current_price: null, current_value: null, day_change_pct: null, allocation_pct: null }, 0);
    assert.equal(row.dataset.ticker, "MISSING");
    assert.match(cells.get('[data-field="ticker"]').innerHTML, /holding-disclosure-btn/);
    assert.match(cells.get('[data-field="ticker"]').innerHTML, /Show details for MISSING/);
    assert.match(cells.get('[data-field="ticker"]').innerHTML, /Price unavailable/);
    assert.equal(cells.get('[data-field="price"]').innerHTML, "Unavailable");
    assert.equal(cells.get('[data-field="allocation"]').innerHTML, "Unavailable");
    updateHoldingRow(row, { id: 2, ticker: "VOD.L", currency: "GBp", current_price: 100,
        current_value: 1000, day_change_pct: null, allocation_pct: null }, 0);
    assert.equal(cells.get('[data-field="price"]').innerHTML, "100.00 GBp");
    assert.equal(cells.get('[data-field="value"]').innerHTML, "1,000.00 GBp");
    const malicious = 'GBp<img src=x onerror="globalThis.currencyExecuted=true">';
    updateHoldingRow(row, { id: 3, ticker: "UNTRUSTED", currency: malicious, current_price: 100,
        current_value: 1000, day_change_pct: null, allocation_pct: null }, 0);
    for (const field of ["price", "value"]) {
        const markup = cells.get(`[data-field="${field}"]`).innerHTML;
        assert.match(markup, /GBp&lt;img src=x onerror=&quot;globalThis.currencyExecuted=true&quot;&gt;/);
        assert.doesNotMatch(markup, /<img|&amp;lt;/);
    }
    assert.doesNotMatch(cells.get('[data-field="ticker"]').innerHTML, /<img/);
});

test("income and fee exclusions remain named without invented zero yields or non-payer claims", () => {
    const body = { innerHTML: "", replaceChildren() { this.innerHTML = ""; } };
    const empty = [];
    const { renderIncome, renderFeeDrag, _yieldPct, _feePct } = valuationHarness(["renderIncome", "renderFeeDrag", "_yieldPct", "_feePct"], {
        document: { getElementById: () => body }, escapeHtml: String,
        _cardEmpty: (_, visible, message) => { if (visible) empty.push(message); }, _exDivChip: () => "",
    });
    assert.equal(_yieldPct(null), "");
    assert.equal(_feePct(null), "");
    renderIncome({ has_data: false, coverage: { excluded_tickers: ["VOD.L"], non_payers: [] } });
    assert.match(empty.pop(), /USD income unavailable for VOD.L/);
    renderIncome({ has_data: true, total_annual_income: 2, portfolio_yield: null,
        payers: [], coverage: { excluded_tickers: ["VOD.L"] } });
    assert.match(body.innerHTML, /known USD a year/);
    assert.match(body.innerHTML, /VOD.L/);
    assert.doesNotMatch(body.innerHTML, /0.00% blended/);
    renderFeeDrag({ has_data: false, coverage: { uncovered_tickers: ["VOD.L"] },
        flags: ["No usable USD valuation for VOD.L"] });
    assert.match(empty.pop(), /usable USD value or expense ratio unavailable/);
    renderFeeDrag({ has_data: true, holdings: [], annual_fee_cost: 1,
        blended_expense_ratio_bps: null, coverage: { uncovered_tickers: ["VOD.L"] } });
    assert.match(body.innerHTML, /Fee unknown/);
    assert.doesNotMatch(body.innerHTML, /0 bps|no expense ratio published/);
});

test("expanded movement uses current quote availability and native per-share units", () => {
    const core = {};
    vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../../static/js/core.js"), "utf8")
        + "\nglobalThis.escaping = { html, escapeHtml, raw };", core);
    const section = { innerHTML: "", querySelector: () => null };
    let contributions = 0;
    const { renderMoveExplainer, sandbox } = valuationHarness([
        "renderMoveExplainer", "renderMoveStatStrip", "buildMoveStatItems", "_buildTodayInContextBlock",
    ], {
        html: core.escaping.html, raw: core.escaping.raw, escapeHtml: core.escaping.escapeHtml,
        latestHoldings: [{ ticker: "VTI", quote_available: false, day_change_pct: null, day_change: null }],
        cachedVerdicts: {}, cachedMarketRegime: {}, MOVE_ATTR_ICONS: {}, MOVE_ATTR_TONES: {}, ATTRIBUTION_SHORT: {},
        renderKeyDriversSpecRows: () => "", _buildMarketBackdropBlock: () => "", _buildTrendContextBlock: () => "",
        renderContributionBreakdown: () => { contributions += 1; return ""; },
    });
    const cached = { ticker: "VTI", day_change_pct: 0, day_change_dollar: 0,
        explanation_text: "No live price move", drivers: [{ description: "Cached price was flat" }] };
    renderMoveExplainer(section, cached);
    let markup = String(section.innerHTML);
    assert.match(markup, /move-hero-number ">Unavailable/);
    assert.match(markup, /move-hero-sub">Unavailable/);
    assert.match(markup, /Live price move unavailable/);
    assert.doesNotMatch(markup, /\+0\.00%|\$0\.00|No live price move|Cached price was flat/);
    assert.equal(contributions, 0);

    sandbox.latestHoldings = [{ ticker: "VTI", quote_available: true, currency: "GBp", day_change_pct: -2, day_change: -1.5 }];
    renderMoveExplainer(section, { ...cached, explanation_text: "Native market move" });
    markup = String(section.innerHTML);
    assert.match(markup, /-2\.00%/);
    assert.match(markup, /-1\.50 GBp\/share/);
    assert.doesNotMatch(markup, /\$/);

    sandbox.latestHoldings = [{ ticker: "VTI", quote_available: true, currency: "usd", day_change_pct: 0, day_change: 0 }];
    renderMoveExplainer(section, cached);
    markup = String(section.innerHTML);
    assert.match(markup, /\+0\.00%/);
    assert.match(markup, /\+\$0\.00\/share/);

    sandbox.latestHoldings[0].day_change = null;
    renderMoveExplainer(section, cached);
    assert.match(String(section.innerHTML), /move-hero-sub">Unavailable/);
    sandbox.latestHoldings = [];
    renderMoveExplainer(section, { ...cached, quote_available: false });
    assert.match(String(section.innerHTML), /move-hero-number ">Unavailable/);
    assert.doesNotMatch(String(section.innerHTML), /\+Unavailable|\$0\.00|\+0\.00%/);
});

test("expanded price ranges, targets and trigger levels preserve currency and withhold unavailable quotes", () => {
    const core = {};
    vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../../static/js/core.js"), "utf8")
        + "\nglobalThis.escaping = { html, escapeHtml };", core);
    const holding = { ticker: "VOD.L", quote_available: true, currency: "GBp" };
    const { _buildEquityValueBlock, _renderFlipTriggers, renderTargetCell } = valuationHarness([
        "_buildEquityValueBlock", "_renderFlipTriggers", "renderTargetCell",
    ], {
        latestHoldings: [holding], html: core.escaping.html, escapeHtml: core.escaping.escapeHtml,
        _verdictTip: () => "", renderCoverageDivider: () => "", renderCoverageSectionHint: () => "",
        signalTone: () => "neutral", formatSignalPct: value => `${value}%`, renderTargetKind: () => "",
    });
    const rating = { target_price: 120, target_upside_pct: 20 };
    const timing = { range_position_pct: 50, watch_levels: { fifty_two_week_low: 50, fifty_two_week_high: 100 } };
    let markup = _buildEquityValueBlock({ ticker: "VOD.L" }, rating, timing);
    for (const amount of ["50.00 GBp", "100.00 GBp", "120.00 GBp"]) assert.ok(markup.includes(amount));
    assert.doesNotMatch(markup, /\$/);
    assert.match(String(renderTargetCell(rating, holding)), /120\.00 GBp/);
    const verdict = { flip_triggers: { add_price: 60, trim_price: 110 } };
    markup = _renderFlipTriggers(verdict, "VOD.L");
    assert.match(markup, /60\.00 GBp/);
    assert.match(markup, /110\.00 GBp/);
    assert.doesNotMatch(markup, /\$/);

    holding.quote_available = false;
    assert.match(_buildEquityValueBlock({ ticker: "VOD.L" }, rating, timing), /Current price comparison unavailable/);
    assert.match(String(renderTargetCell(rating, holding)), /Unavailable/);
    assert.equal(_renderFlipTriggers(verdict, "VOD.L"), "");
});

test("toast announcements use one persistent live region without moving focus", () => {
    const frames = [];
    const focus = { id: "remove-holding-button" };
    const region = { dataset: {}, textContent: "", inert: true, parentNode: null };
    const attach = parent => { parent.appendChild = node => { node.parentNode = parent; }; return parent; };
    const body = attach({ connected: true });
    region.parentNode = body;
    const dialog = attach({ connected: true, hidden: false, getAttribute: () => "false", closest: () => null });
    const hiddenDialog = { hidden: true };
    const document = {
        activeElement: focus,
        body,
        getElementById: id => id === "toast-status" && region.parentNode?.connected ? region : null,
        querySelectorAll: () => [dialog, hiddenDialog],
    };
    const { announceToast } = loadFunctions(["announceToast"], {
        document, _toastStatusRegion: null, requestAnimationFrame: callback => frames.push(callback),
    });

    announceToast("Holding saved");
    assert.equal(region.parentNode, dialog);
    assert.equal(region.inert, false);
    assert.equal(region.textContent, "");
    frames.shift()();
    assert.equal(region.textContent, "Holding saved");
    assert.equal(document.activeElement, focus);

    announceToast("Holding saved");
    announceToast("Couldn't confirm whether VTI was removed. Refresh before trying again.");
    frames.shift()();
    assert.equal(region.textContent, "");
    frames.shift()();
    assert.match(region.textContent, /Couldn't confirm/);
    assert.equal(document.activeElement, focus);

    // A one-off sale dialog removes its entire subtree when it closes.
    dialog.connected = false;
    dialog.hidden = true;
    assert.equal(document.getElementById("toast-status"), null);
    announceToast("Dashboard refreshed");
    frames.shift()();
    assert.equal(region.parentNode, body);
    assert.equal(region.textContent, "Dashboard refreshed");
    assert.equal(document.activeElement, focus);

    const nested = attach({ connected: true, hidden: false, getAttribute: () => "false", closest: () => null });
    dialog.connected = true;
    dialog.hidden = false;
    dialog.closest = () => ({ inert: true });
    document.querySelectorAll = () => [dialog, nested];
    announceToast("Nested confirmation complete");
    frames.shift()();
    assert.equal(region.parentNode, nested);
    nested.hidden = true;
    dialog.closest = () => null;
    announceToast("Back to holdings");
    frames.shift()();
    assert.equal(region.parentNode, dialog);
    assert.equal(region.textContent, "Back to holdings");
    assert.equal(document.activeElement, focus);
    const markup = fs.readFileSync(path.resolve(__dirname, "../../templates/index.html"), "utf8");
    assert.match(markup, /id="toast-status" role="status"\s+aria-live="polite" aria-atomic="true"/);
    assert.equal((markup.match(/id="toast-status"/g) || []).length, 1);
    assert.match(extractFunction("showToast"), /toast.setAttribute\("aria-hidden", "true"\)/);
});

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
