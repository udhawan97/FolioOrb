/**
 * dashboard.js
 * Fetches stock data from our FastAPI backend and updates the UI.
 * Runs automatically when the page loads.
 */

const toNumber = (n, fallback = 0) => {
    const value = Number(n);
    return Number.isFinite(value) ? value : fallback;
};
const formatCurrency = (n) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(toNumber(n));

// Abbreviated for tight spaces: $1.2K, $1.4M, $2.1B
const formatCompact = (n) => {
    const v = toNumber(n);
    const abs = Math.abs(v);
    const sign = v < 0 ? "-" : "";
    if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
    if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
    return formatCurrency(v);
};
const formatPct = (n) => {
    const value = toNumber(n);
    return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
};
const isFiniteNumber = (n) => n !== null && n !== "" && Number.isFinite(Number(n));
const formatOptionalPct = (n) => isFiniteNumber(n) ? formatPct(Number(n)) : "—";
const formatAllocationPct = (n) => `${toNumber(n).toFixed(1)}%`;
const colorClass = (v) => v >= 0 ? "text-success" : "text-danger";
const valueClass = (v) => {
    if (!isFiniteNumber(v) || Number(v) === 0) return "text-secondary";
    return Number(v) > 0 ? "text-success" : "text-danger";
};
const TREND_DAYS = 7;

// Apple system colors (dark) — vibrant but restrained, matches the UI accents.
const CHART_COLORS = [
    "#0a84ff", // blue
    "#30d158", // green
    "#5e5ce6", // indigo
    "#ff9f0a", // orange
    "#ff375f", // pink
    "#64d2ff", // cyan
    "#bf5af2", // purple
    "#ffd60a", // yellow
    "#66d4cf", // mint
    "#ff453a", // red
];
// Wrap around the palette so portfolios with >10 holdings still get colors.
const chartColor = (i) => CHART_COLORS[i % CHART_COLORS.length];

// Human-readable labels for attribution types (badge text)
const ATTRIBUTION_SHORT = {
    "market-driven":    "Market",
    "sector-driven":    "Sector",
    "holdings-driven":  "Holdings",
    "macro-driven":     "Macro",
    "company-specific": "Company",
    "earnings-driven":  "Earnings",
    "filing-driven":    "Filing",
    "mixed":            "Mixed",
    "unclear":          "No clear",
    "etf-index":        "Index",
};

const ATTRIBUTION_LABELS = {
    "market-driven":    "Market Driven",
    "sector-driven":    "Sector Driven",
    "holdings-driven":  "Holdings Driven",
    "macro-driven":     "Macro Driven",
    "company-specific": "Company Specific",
    "earnings-driven":  "Earnings Driven",
    "filing-driven":    "Filing Driven",
    "mixed":            "Mixed Factors",
    "unclear":          "No Clear Catalyst",
    "etf-index":        "Index / ETF",
};

let allocationChart = null;  // Keep chart instance for updates
let latestHoldings = [];     // Most recent holdings, for re-sorting without a refetch
let latestTrendData = {};    // Cached sparkline data, so the Holdings table re-sorts without a refetch
let allocSortDir = "desc";   // Allocation sort direction: "desc" | "asc"
let holdingsSort = { key: "allocation_pct", dir: "desc" };
let allocationTotal = 0;     // Portfolio total, drawn in the doughnut's center

// Holding Intelligence state (covers "What it covers" + "Why it moved")
let cachedIntelligence = {};   // ticker → intelligence object (coverage data)
let cachedExplanations = {};   // ticker → explanation object (move data)
let intelligenceLoaded = false;
let intelligenceLoading = false;

// Rating state: stock analyst ratings or ETF quality labels
let cachedRecommendations = {};  // ticker → rec object from /api/ai/analyst-recommendations/all

// Single source of truth for allocation ordering, shared by both tables and the chart.
function sortedByAllocation(holdings) {
    const dir = allocSortDir === "asc" ? 1 : -1;
    return [...holdings].sort(
        (a, b) => dir * (toNumber(a.allocation_pct) - toNumber(b.allocation_pct))
    );
}

function sortedHoldings(holdings) {
    const dir = holdingsSort.dir === "asc" ? 1 : -1;
    return holdings
        .map((holding, index) => ({ holding, index }))
        .sort((a, b) => {
            const av = Number(a.holding[holdingsSort.key]);
            const bv = Number(b.holding[holdingsSort.key]);
            const aOk = Number.isFinite(av);
            const bOk = Number.isFinite(bv);
            if (!aOk && !bOk) return a.index - b.index;
            if (!aOk) return 1;
            if (!bOk) return -1;
            const diff = av - bv;
            return diff === 0 ? a.index - b.index : dir * diff;
        })
        .map(item => item.holding);
}

// Keep sortable header carets in sync with their current sort state.
function updateSortCarets() {
    const allocEl = document.getElementById("alloc-sort-caret");
    if (allocEl) {
        allocEl.className = `bi small ${allocSortDir === "asc" ? "bi-caret-up-fill" : "bi-caret-down-fill"}`;
    }

    const caretIds = {
        current_price: "holdings-price-caret",
        day_change_pct: "holdings-today-caret",
        current_value: "holdings-value-caret",
        allocation_pct: "holdings-alloc-caret",
    };
    Object.entries(caretIds).forEach(([key, id]) => {
        const el = document.getElementById(id);
        if (!el) return;
        const active = holdingsSort.key === key;
        el.className = `bi small ${holdingsSort.dir === "asc" ? "bi-caret-up-fill" : "bi-caret-down-fill"}`;
        el.style.visibility = active ? "visible" : "hidden";
    });
}


async function loadPortfolioValue() {
    try {
        const res = await fetch("/api/portfolio/value");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Update summary cards
        document.getElementById("total-value").textContent =
            formatCompact(data.total_value);
        document.getElementById("holding-count").textContent =
            data.holdings.length;
        document.getElementById("daily-pnl").innerHTML =
            `<span class="${colorClass(data.total_daily_change)}">
             ${formatCompact(data.total_daily_change)}
             <span style="font-size:.85em;opacity:.8">(${formatPct(data.total_daily_change_pct)})</span>
             </span>`;

        renderTotalReturn(data);

        latestHoldings = data.holdings;
        renderAllocation();

        if (data.best_performer) {
            document.getElementById("best-performer").innerHTML =
                `${data.best_performer.ticker} <span style="font-size:.85em;opacity:.8">${formatPct(data.best_performer.day_change_pct)}</span>`;
        }
        if (data.worst_performer) {
            document.getElementById("worst-performer").innerHTML =
                `${data.worst_performer.ticker} <span style="font-size:.85em;opacity:.8">${formatPct(data.worst_performer.day_change_pct)}</span>`;
        }
        if (data.holdings.length) {
            const largest = data.holdings.reduce((a, b) =>
                a.current_value > b.current_value ? a : b);
            document.getElementById("largest-holding").innerHTML =
                `${largest.ticker} <span style="font-size:.85em;opacity:.8">${formatCompact(largest.current_value)}</span>`;
        }

        latestTrendData = await loadTrendData(data.holdings.map(h => h.ticker));
        renderHoldings();
        document.getElementById("last-updated").textContent =
            `Updated: ${new Date().toLocaleTimeString()}`;

    } catch (err) {
        console.error("Error loading portfolio value:", err);
    }
}


function renderAllocation() {
    const sorted = sortedByAllocation(latestHoldings);

    const allocTable = document.getElementById("allocation-table");
    allocTable.innerHTML = "";
    sorted.forEach((h, i) => {
        const row = allocTable.insertRow();
        row.innerHTML = `
            <td><span class="badge" style="background:${chartColor(i)}">&nbsp;</span>
                ${h.ticker}</td>
            <td>${h.shares}</td>
            <td class="text-end">${formatCurrency(h.current_value)}</td>
            <td class="text-end">${formatAllocationPct(h.allocation_pct)}</td>
        `;
    });

    updateSortCarets();

    const labels = sorted.map(h => h.ticker);
    const values = sorted.map(h => h.current_value);
    const colors = sorted.map((_, i) => chartColor(i));

    allocationTotal = values.reduce((sum, v) => sum + toNumber(v), 0);

    if (allocationChart) {
        allocationChart.data.labels = labels;
        allocationChart.data.datasets[0].data = values;
        allocationChart.data.datasets[0].backgroundColor = colors;
        allocationChart.update();
    } else {
        const ctx = document.getElementById("allocation-chart").getContext("2d");
        allocationChart = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderColor: "transparent",
                    borderWidth: 0,
                    borderRadius: 6,
                    spacing: 3,
                    hoverOffset: 10,
                    hoverBorderColor: "rgba(255,255,255,0.18)",
                    hoverBorderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                cutout: "72%",
                layout: { padding: 6 },
                animation: { animateRotate: true, animateScale: true, duration: 900,
                             easing: "easeOutQuart" },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "rgba(28,28,34,0.92)",
                        titleColor: "#f5f5f7",
                        bodyColor: "rgba(235,235,245,0.85)",
                        borderColor: "rgba(255,255,255,0.12)",
                        borderWidth: 1,
                        cornerRadius: 12,
                        padding: 12,
                        boxPadding: 6,
                        usePointStyle: true,
                        titleFont: { family: "-apple-system, SF Pro Display, sans-serif",
                                     weight: "600", size: 13 },
                        bodyFont: { family: "-apple-system, SF Pro Text, sans-serif", size: 12 },
                        callbacks: {
                            title: (items) => items[0]?.label ?? "",
                            label: (item) => {
                                const sum = allocationTotal || 1;
                                const pct = (toNumber(item.raw) / sum) * 100;
                                return `${formatCurrency(item.raw)}  ·  ${pct.toFixed(1)}%`;
                            },
                            labelPointStyle: () => ({ pointStyle: "circle" }),
                        }
                    }
                }
            },
            plugins: [centerTotalPlugin],
        });
    }
}

// Draws "Total" + the portfolio value in the doughnut's hole, Apple-style.
const centerTotalPlugin = {
    id: "centerTotal",
    afterDraw(chart) {
        if (chart.config.type !== "doughnut") return;
        const meta = chart.getDatasetMeta(0);
        const arc = meta?.data?.[0];
        if (!arc) return;
        const { x, y } = arc;
        const { ctx } = chart;

        ctx.save();
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        ctx.fillStyle = "rgba(235,235,245,0.45)";
        ctx.font = "600 11px -apple-system, 'SF Pro Text', sans-serif";
        ctx.fillText("TOTAL", x, y - 14);

        ctx.fillStyle = "#f5f5f7";
        ctx.font = "600 20px -apple-system, 'SF Pro Display', sans-serif";
        ctx.fillText(formatCurrency(allocationTotal), x, y + 6);
        ctx.restore();
    },
};

function renderHoldings() {
    updateHoldingsTable(sortedHoldings(latestHoldings), latestTrendData);
    updateSortCarets();
}

function toggleHoldingsSort(key) {
    holdingsSort = {
        key,
        dir: holdingsSort.key === key && holdingsSort.dir === "asc" ? "desc" : "asc",
    };
    renderHoldings();
}

function toggleAllocationSort() {
    allocSortDir = allocSortDir === "asc" ? "desc" : "asc";
    holdingsSort = { key: "allocation_pct", dir: allocSortDir };
    renderAllocation();
    renderHoldings();
}


const formatSignedCurrency = (n) =>
    `${toNumber(n) >= 0 ? "+" : "-"}${formatCurrency(Math.abs(toNumber(n)))}`;

function renderTotalReturn(data) {
    const tr = toNumber(data.total_return);
    const cls = colorClass(tr);

    const set = (id, html) => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = html;
    };
    set("total-return", `<span class="${cls}">${formatSignedCurrency(tr)}</span>`);
    set("total-return-pct", `<span class="${cls}">${formatPct(data.total_return_pct)} all-time</span>`);
    set("unrealized-gain",
        `<span class="${colorClass(data.total_unrealized_gain)}">${formatSignedCurrency(data.total_unrealized_gain)}</span>`);
    set("realized-gain",
        `<span class="${colorClass(data.realized_gain)}">${formatSignedCurrency(data.realized_gain)}</span>`);
}


let pnlChart = null;

async function loadPnl() {
    try {
        const res = await fetch("/api/portfolio/pnl");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderPnlChart(data.history || []);
        renderRealizedTable(data.trades || []);
    } catch (err) {
        console.warn("Unable to load P&L:", err);
    }
}

function renderPnlChart(history) {
    const canvas = document.getElementById("pnl-chart");
    if (!canvas) return;

    const labels = history.map(h => h.date);
    const values = history.map(h => toNumber(h.total_return));
    const up = values.length < 2 || values[values.length - 1] >= values[0];
    const line = up ? "#30d158" : "#ff453a";

    const ctx = canvas.getContext("2d");
    const fill = ctx.createLinearGradient(0, 0, 0, canvas.height || 150);
    fill.addColorStop(0, up ? "rgba(48,209,88,0.28)" : "rgba(255,69,58,0.28)");
    fill.addColorStop(1, "rgba(0,0,0,0)");

    if (pnlChart) {
        pnlChart.data.labels = labels;
        pnlChart.data.datasets[0].data = values;
        pnlChart.data.datasets[0].borderColor = line;
        pnlChart.data.datasets[0].backgroundColor = fill;
        pnlChart.update();
        return;
    }

    pnlChart = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [{
                data: values,
                borderColor: line,
                backgroundColor: fill,
                borderWidth: 2,
                fill: true,
                tension: 0.35,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointHoverBackgroundColor: line,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(28,28,34,0.92)",
                    titleColor: "#f5f5f7",
                    bodyColor: "rgba(235,235,245,0.85)",
                    borderColor: "rgba(255,255,255,0.12)",
                    borderWidth: 1,
                    cornerRadius: 12,
                    padding: 12,
                    callbacks: {
                        label: (item) => `Total return: ${formatSignedCurrency(item.raw)}`,
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: "rgba(235,235,245,0.42)", maxRotation: 0, autoSkip: true,
                             maxTicksLimit: 6, font: { size: 10 } },
                },
                y: {
                    grid: { color: "rgba(255,255,255,0.06)" },
                    ticks: { color: "rgba(235,235,245,0.42)", font: { size: 10 },
                             callback: (v) => formatSignedCurrency(v) },
                }
            }
        }
    });
}

function renderRealizedTable(trades) {
    const tbody = document.getElementById("realized-table");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!trades.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-secondary py-4">
            No realized trades yet — they appear here when you reduce a holding.</td></tr>`;
        return;
    }

    trades.forEach(t => {
        const row = tbody.insertRow();
        const day = t.date ? new Date(t.date).toLocaleDateString() : "--";
        row.innerHTML = `
            <td class="text-secondary small">${day}</td>
            <td class="fw-bold">${t.ticker}</td>
            <td class="text-end">${toNumber(t.shares_sold).toFixed(3)}</td>
            <td class="text-end">${formatCurrency(t.sale_price)}</td>
            <td class="text-end">${formatCurrency(t.avg_cost)}</td>
            <td class="text-end ${colorClass(t.realized_gain)}">${formatSignedCurrency(t.realized_gain)}</td>
            <td class="text-end ${valueClass(t.total_return_pct)}">${formatOptionalPct(t.total_return_pct)}</td>
        `;
    });
}


async function loadTrendData(tickers) {
    if (!tickers.length) return {};

    try {
        const params = new URLSearchParams({
            tickers: tickers.join(","),
            period: "1mo",
        });
        const res = await fetch(`/api/stocks/history/batch?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        return data.data || {};
    } catch (err) {
        console.warn("Unable to load trend data:", err);
        return {};
    }
}


function updateHoldingsTable(holdings, trendData = {}) {
    const tbody = document.getElementById("holdings-table");
    tbody.innerHTML = "";
    holdings.forEach((h, i) => {
        const row = tbody.insertRow();
        row.dataset.ticker = h.ticker;
        const up = h.day_change_pct >= 0;
        const exp = cachedExplanations[h.ticker];
        const badgeHtml = (intelligenceLoaded && exp)
            ? `<div class="move-badge ${exp.attribution_type}" title="${exp.confidence} confidence">${ATTRIBUTION_SHORT[exp.attribution_type] || "?"}</div>`
            : `<div class="move-badge" id="move-badge-${h.ticker}"></div>`;

        const rec = cachedRecommendations[h.ticker];
        row.innerHTML = `
            <td class="fw-bold">
                <span class="ticker-dot" style="background:${chartColor(i)}"></span>${h.ticker}<i class="bi bi-chevron-right row-chevron"></i>
            </td>
            <td class="d-none d-md-table-cell text-secondary small">${h.name.substring(0, 28)}</td>
            <td class="text-end">${formatCurrency(h.current_price)}</td>
            <td class="text-end">
                <div class="${colorClass(h.day_change_pct)}">
                    <i class="bi ${up ? "bi-caret-up-fill" : "bi-caret-down-fill"}"
                       style="font-size:.65rem;vertical-align:middle;opacity:.75"></i>
                    ${formatPct(h.day_change_pct)}
                </div>
                ${badgeHtml}
            </td>
            <td class="text-end d-none d-md-table-cell">${formatCurrency(h.current_value)}</td>
            <td class="text-end">${formatAllocationPct(h.allocation_pct)}</td>
            <td class="text-end ${valueClass(h.total_return_pct)}">${formatOptionalPct(h.total_return_pct)}</td>
            <td class="text-center d-none d-lg-table-cell" id="rec-cell-${h.ticker}">${renderAnalystRecCell(rec)}</td>
            <td class="text-center d-none d-xl-table-cell trend-cell"></td>
        `;
        row.addEventListener("click", () => toggleSummaryRow(row));
        const canvas = document.createElement("canvas");
        canvas.className = "trend-sparkline";
        canvas.width = 120;
        canvas.height = 32;
        canvas.setAttribute("aria-label", `${h.ticker} ${TREND_DAYS}-day trend`);
        row.querySelector(".trend-cell").appendChild(canvas);
        drawTrend(canvas, trendData[h.ticker]);
    });

    const hasContent = intelligenceLoaded || intelligenceLoading || Object.keys(cachedIntelligence).length > 0;
    if (hasContent) {
        injectSummaryRows(tbody);
    }
}

function toggleSummaryRow(mainRow) {
    const expandRow = mainRow.nextElementSibling;
    if (!expandRow || !expandRow.classList.contains("summary-expand-row")) return;
    const body = expandRow.querySelector(".summary-body");
    const isOpen = body.classList.toggle("open");
    mainRow.classList.toggle("summary-open", isOpen);
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function parseBullets(text) {
    if (!text) return [];
    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    const bulletLines = lines.filter(l => /^[•\-*]/.test(l));
    if (bulletLines.length >= 2) {
        return bulletLines.map(l => l.replace(/^[•\-*]+\s*/, "").trim()).filter(Boolean);
    }
    return lines
        .map(l => l.replace(/^#+\s*/, "").replace(/\*\*/g, "").trim())
        .filter(Boolean);
}

function renderSummaryInner(inner, text, isLoading) {
    if (isLoading) {
        inner.innerHTML = `
            <div class="summary-bullet"><span class="summary-dot" style="opacity:.25"></span><div class="shimmer-line" style="width:72%"></div></div>
            <div class="summary-bullet"><span class="summary-dot" style="opacity:.25"></span><div class="shimmer-line" style="width:55%"></div></div>
            <div class="summary-bullet"><span class="summary-dot" style="opacity:.25"></span><div class="shimmer-line" style="width:63%"></div></div>
        `;
        return;
    }
    const bullets = parseBullets(text).slice(0, 3);
    if (bullets.length) {
        inner.innerHTML = bullets.map(b =>
            `<div class="summary-bullet"><span class="summary-dot"></span><span>${escapeHtml(b)}</span></div>`
        ).join("");
    } else {
        inner.innerHTML = `<span style="font-size:.75rem;color:var(--text-tertiary)">Summary unavailable</span>`;
    }
}

// ── Move Explainer UI ──────────────────────────────────────────────────────

function renderCoverageShimmer(section) {
    section.innerHTML = `
        <div class="intel-coverage">
            <div class="intel-label"><i class="bi bi-layers"></i> What it covers</div>
            <div class="shimmer-line" style="width:80px;height:18px;border-radius:20px;margin-bottom:.5rem"></div>
            <div class="shimmer-line" style="width:95%;height:10px;margin-bottom:.25rem"></div>
            <div class="shimmer-line" style="width:78%;height:10px;margin-bottom:.6rem"></div>
            ${[80, 60, 45, 35, 25].map(w => `
                <div class="sector-bar-row">
                    <div class="shimmer-line" style="width:72px;height:9px;flex-shrink:0"></div>
                    <div class="shimmer-line" style="width:${w}%;height:4px"></div>
                    <div class="shimmer-line" style="width:26px;height:9px;flex-shrink:0"></div>
                </div>`).join("")}
        </div>`;
}

function renderMoveExplainerShimmer(section) {
    section.innerHTML = `
        <div class="intel-move">
            <div class="intel-label"><i class="bi bi-lightning-charge-fill" style="color:var(--accent-yellow)"></i> Why it moved</div>
            <div class="move-explainer-header" style="margin-bottom:.5rem">
                <div class="shimmer-line" style="width:110px;height:20px;border-radius:10px"></div>
                <div class="shimmer-line" style="width:80px;height:16px;border-radius:10px"></div>
            </div>
            <div class="shimmer-line" style="width:88%;margin-bottom:.3rem"></div>
            <div class="shimmer-line" style="width:70%;margin-bottom:.55rem"></div>
            <div class="move-drivers">
                ${[65, 52, 74].map(w => `
                    <div class="driver-item">
                        <div class="shimmer-line" style="width:10px;height:10px;border-radius:50%;flex-shrink:0;margin-top:.12em"></div>
                        <div class="shimmer-line" style="width:${w}%"></div>
                    </div>
                `).join("")}
            </div>
        </div>`;
}

function renderMoveExplainer(section, data) {
    if (!data) { section.innerHTML = ""; return; }

    const attrType   = data.attribution_type || "unclear";
    const confidence = data.confidence || "Low";
    const drivers    = data.drivers || [];
    const news       = data.news || [];
    const macro      = data.macro_context;
    const isPos      = (data.day_change_pct || 0) >= 0;
    const pctColor   = isPos ? "var(--accent-green)" : "var(--accent-red)";

    // Build context pills — use holding-specific benchmark first, then SPY/QQQ if relevant
    const macroPills = [];
    if (macro) {
        // Primary benchmark (BTC for IBIT, EEM for IEMG, XAR for ITA, etc.)
        if (macro.primary_benchmark && macro.primary_benchmark_chg !== null && macro.primary_benchmark_chg !== undefined) {
            const label = macro.primary_benchmark_label || macro.primary_benchmark;
            macroPills.push({ label: `${label} ${formatPct(macro.primary_benchmark_chg)}`, pos: macro.primary_benchmark_chg >= 0 });
        }
        // Sector ETF (individual stocks only)
        if (macro.sector_etf && macro.sector_etf_change_pct !== null && macro.sector_etf_change_pct !== undefined) {
            macroPills.push({
                label: `${macro.sector_etf} ${formatPct(macro.sector_etf_change_pct)}`,
                pos: macro.sector_etf_change_pct >= 0,
            });
        }
        // SPY only when relevant (not suppressed)
        if (!macro.suppress_spy && macro.primary_benchmark !== "SPY") {
            macroPills.push({ label: `SPY ${formatPct(macro.spy_change_pct)}`, pos: macro.spy_change_pct >= 0 });
        }
        // QQQ only when relevant (not suppressed, not primary)
        if (!macro.suppress_qqq && macro.primary_benchmark !== "QQQ" && Math.abs(macro.qqq_change_pct) > 0.05) {
            macroPills.push({ label: `QQQ ${formatPct(macro.qqq_change_pct)}`, pos: macro.qqq_change_pct >= 0 });
        }
    }
    if (data.volume_vs_avg !== null && data.volume_vs_avg !== undefined) {
        macroPills.push({ label: `Vol ${data.volume_vs_avg.toFixed(1)}× avg`, pos: data.volume_vs_avg >= 1.5 });
    }

    const driversHtml = drivers.map(d => `
        <div class="driver-item">
            <i class="bi ${escapeHtml(d.icon)} driver-icon ${escapeHtml(d.magnitude)}"></i>
            <span>${escapeHtml(d.description)}</span>
        </div>`).join("");

    const macroPillsHtml = macroPills.length
        ? `<div class="macro-pills">${macroPills.map(p =>
            `<span class="macro-pill ${p.pos ? "positive" : "negative"}">${escapeHtml(p.label)}</span>`
          ).join("")}</div>`
        : "";

    const newsHtml = news.length
        ? `<div class="evidence-section">
            <div class="expand-section-label" style="margin-top:.3rem">
                <i class="bi bi-newspaper"></i> Recent News
            </div>
            ${news.map(n => `
                <div class="news-item">
                    <i class="bi bi-link-45deg" style="color:var(--accent-cyan);opacity:.6;font-size:.65rem;flex-shrink:0;margin-top:.15em"></i>
                    <div>
                        ${n.url
                            ? `<a href="${escapeHtml(n.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(n.title)}</a>`
                            : `<span style="color:var(--text-secondary)">${escapeHtml(n.title)}</span>`}
                        ${n.source ? `<span class="news-source"> · ${escapeHtml(n.source)}</span>` : ""}
                    </div>
                </div>`).join("")}
           </div>`
        : "";

    section.innerHTML = `
        <div class="intel-move">
            <div class="intel-label">
                <i class="bi bi-lightning-charge-fill" style="color:var(--accent-yellow)"></i>
                Why it moved
            </div>
            <div class="move-explainer-header">
                <span class="attribution-badge ${escapeHtml(attrType)}">${escapeHtml(ATTRIBUTION_LABELS[attrType] || attrType)}</span>
                <span class="confidence-badge ${escapeHtml(confidence)}">${escapeHtml(confidence)} confidence</span>
                <span style="margin-left:auto;font-size:.72rem;color:${pctColor};font-variant-numeric:tabular-nums;font-weight:600">
                    ${formatPct(data.day_change_pct)}
                    <span style="opacity:.65;font-weight:400;font-size:.68rem"> · ${formatCompact(data.day_change_dollar || 0)}/share</span>
                </span>
            </div>
            <p class="move-explanation-text">${escapeHtml(data.explanation_text || "")}</p>
            ${driversHtml ? `<div class="move-drivers">${driversHtml}</div>` : ""}
            ${macroPillsHtml}
            ${newsHtml}
        </div>`;
}

// ── Holding Coverage ("What it covers") ──────────────────────────────────────

function renderHoldingCoverage(section, data) {
    if (!data) {
        section.innerHTML = `<div class="intel-coverage"><span class="intel-na">Coverage data not available</span></div>`;
        return;
    }

    const coverageClass = (data.coverage_type || "equity").replace(/[^a-z-]/g, "");
    const rating = cachedRecommendations[data.ticker] || {};
    const quality = rating.etf_quality || null;

    // Sector bars (top 5)
    const sectorBarsHtml = data.sectors && data.sectors.length
        ? `<div class="intel-label" style="margin-top:.45rem"><i class="bi bi-diagram-3"></i> Sectors</div>
           <div class="sector-bars">
             ${data.sectors.slice(0, 5).map(s => `
               <div class="sector-bar-row">
                 <div class="sector-bar-label" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</div>
                 <div class="sector-bar-track"><div class="sector-bar-fill" style="width:${Math.min(s.weight, 100)}%"></div></div>
                 <div class="sector-bar-pct">${s.weight.toFixed(0)}%</div>
               </div>`).join("")}
           </div>`
        : "";

    // Country chips (top 6)
    const countryChipsHtml = data.countries && data.countries.length
        ? `<div class="intel-label"><i class="bi bi-globe2"></i> Countries / Regions</div>
           <div class="country-chips">
             ${data.countries.slice(0, 6).map((c, i) =>
               `<span class="country-chip${i === 0 ? " primary" : ""}">${escapeHtml(c.name)} ${c.weight.toFixed(0)}%</span>`
             ).join("")}
           </div>`
        : "";

    // Top holdings mini list (for individual stock: show peers instead)
    let topHoldingsHtml = "";
    if (data.top_holdings && data.top_holdings.length && data.coverage_type !== "equity") {
        const maxBarWeight = Math.max(...data.top_holdings.map(h => h.weight), 1);
        topHoldingsHtml = `
            <div class="intel-label"><i class="bi bi-list-task"></i> Top Holdings</div>
            <div class="top-holdings-list">
              ${data.top_holdings.slice(0, 5).map(h => `
                <div class="holding-mini-row">
                  <span class="holding-mini-ticker">${escapeHtml(h.ticker)}</span>
                  <span class="holding-mini-name">${escapeHtml(h.name)}</span>
                  <div class="holding-mini-bar-track">
                    <div class="holding-mini-bar-fill" style="width:${(h.weight / maxBarWeight * 100).toFixed(0)}%"></div>
                  </div>
                  <span class="holding-mini-pct">${h.weight.toFixed(1)}%</span>
                </div>`).join("")}
            </div>`;
    } else if (data.coverage_type === "equity" && data.peer_tickers && data.peer_tickers.length) {
        topHoldingsHtml = `
            <div class="intel-label"><i class="bi bi-people"></i> Peer Group</div>
            <div class="peer-chips">
              ${data.peer_tickers.slice(0, 6).map(p => `<span class="peer-chip">${escapeHtml(p)}</span>`).join("")}
            </div>`;
    }

    // Key drivers
    const keyDriversHtml = data.key_drivers && data.key_drivers.length
        ? `<div class="intel-label" style="margin-top:.3rem"><i class="bi bi-bullseye"></i> Key Drivers</div>
           <div class="key-drivers">
             ${data.key_drivers.slice(0, 4).map(d =>
               `<div class="key-driver-item"><span class="key-driver-dot"></span><span>${escapeHtml(d)}</span></div>`
             ).join("")}
           </div>`
        : "";

    const etfProfileHtml = quality && (data.coverage_type || "").startsWith("etf")
        ? `<div class="intel-label" style="margin-top:.45rem"><i class="bi bi-sliders"></i> ETF Profile</div>
           <div class="key-drivers">
             <div class="key-driver-item"><span class="key-driver-dot"></span><span>ETF Quality: ${escapeHtml(quality.qualityLabel || "Insufficient Data")}</span></div>
             <div class="key-driver-item"><span class="key-driver-dot"></span><span>Cost: ${escapeHtml(quality.costLabel || "Unknown")}</span></div>
             <div class="key-driver-item"><span class="key-driver-dot"></span><span>Liquidity: ${escapeHtml(quality.liquidityLabel || "Unknown")}</span></div>
             <div class="key-driver-item"><span class="key-driver-dot"></span><span>Diversification: ${escapeHtml(quality.diversificationLabel || "Unknown")}</span></div>
             <div class="key-driver-item"><span class="key-driver-dot"></span><span>Category risk: ${escapeHtml(quality.categoryRiskLabel || "Unknown")}</span></div>
           </div>`
        : "";

    // Metadata footer
    const expRatio = data.expense_ratio_bps != null
        ? `<span class="expense-tag">${data.expense_ratio_bps}bps/yr</span>` : "";
    const dataQual = data.data_quality
        ? `<span class="data-quality-tag ${escapeHtml(data.data_quality)}">
             <i class="bi bi-${data.data_quality === 'live' ? 'circle-fill' : 'database'}"></i>
             ${data.data_quality === 'live' ? 'Live data' : data.data_quality === 'partial' ? 'Partial live' : 'Reference data'}
           </span>` : "";

    section.innerHTML = `
        <div class="intel-coverage">
            <div class="intel-label"><i class="bi bi-layers"></i> What it covers</div>
            <span class="coverage-type-badge ${escapeHtml(coverageClass)}">${escapeHtml(data.coverage_label || data.coverage_type)}</span>
            ${data.theme ? `<div style="font-size:.65rem;color:var(--accent-cyan);opacity:.8;margin-bottom:.3rem;font-weight:600">${escapeHtml(data.theme)}</div>` : ""}
            <div class="intel-strategy">${escapeHtml(data.strategy || "")}</div>
            ${sectorBarsHtml}
            ${countryChipsHtml}
            ${topHoldingsHtml}
            ${etfProfileHtml}
            ${keyDriversHtml}
            <div style="margin-top:.45rem">${expRatio}${dataQual}</div>
        </div>`;
}

function injectSummaryRows(tbody) {
    Array.from(tbody.querySelectorAll("tr[data-ticker]")).forEach(mainRow => {
        const ticker = mainRow.dataset.ticker;
        const next = mainRow.nextElementSibling;
        let expandRow = (next && next.classList.contains("summary-expand-row")) ? next : null;

        if (!expandRow) {
            expandRow = document.createElement("tr");
            expandRow.className = "summary-expand-row";
            const td = document.createElement("td");
            td.colSpan = 9;
            td.innerHTML = `<div class="summary-body"><div class="intel-grid">
                <div class="intel-coverage-section"></div>
                <div class="intel-move-section"></div>
            </div></div>`;
            expandRow.appendChild(td);
            mainRow.after(expandRow);
        }

        const body          = expandRow.querySelector(".summary-body");
        const coverageSection = expandRow.querySelector(".intel-coverage-section");
        const moveSection   = expandRow.querySelector(".intel-move-section");

        if (!coverageSection || !moveSection) return;

        if (intelligenceLoading && !intelligenceLoaded) {
            renderCoverageShimmer(coverageSection);
            renderMoveExplainerShimmer(moveSection);
        } else if (intelligenceLoaded) {
            renderHoldingCoverage(coverageSection, cachedIntelligence[ticker]);
            renderMoveExplainer(moveSection, cachedExplanations[ticker]);
        }

        if (intelligenceLoaded || intelligenceLoading) {
            body.classList.add("open");
            mainRow.classList.add("summary-open");
        }
    });
}

function drawTrend(canvas, history = []) {
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    const padding = 3;
    const closes = history
        .slice(-TREND_DAYS)
        .map(point => toNumber(point.close, NaN))
        .filter(Number.isFinite);

    ctx.clearRect(0, 0, width, height);

    if (closes.length < 2) {
        ctx.strokeStyle = "rgba(255,255,255,0.25)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(padding, height / 2);
        ctx.lineTo(width - padding, height / 2);
        ctx.stroke();
        return;
    }

    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = max - min || 1;
    const isPositive = closes[closes.length - 1] >= closes[0];

    ctx.strokeStyle = isPositive ? "#3fb950" : "#f85149";
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();

    closes.forEach((close, index) => {
        const x = padding + (index * (width - padding * 2)) / (closes.length - 1);
        const y = height - padding - ((close - min) / range) * (height - padding * 2);
        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });

    ctx.stroke();
}


// ── Ratings ────────────────────────────────────────────────────────────────

const REC_ICONS = {
    "buy":       "bi-arrow-up-circle-fill",
    "hold":      "bi-dash-circle-fill",
    "sell":      "bi-arrow-down-circle-fill",
    "unavailable": "bi-question-circle",
    "etf-quality": "bi-layers-fill",
};

function renderAnalystRecCell(rec) {
    if (!rec) {
        return `<div class="analyst-rec-wrap">
            <div class="shimmer-line" style="width:52px;height:14px;border-radius:4px;margin:0 auto .25rem"></div>
            <div class="shimmer-line" style="width:64px;height:9px;border-radius:4px;margin:0 auto"></div>
        </div>`;
    }
    const action = rec.action || "unavailable";
    const icon = REC_ICONS[action] || "bi-question-circle";
    return `<div class="analyst-rec-wrap">
        <div class="analyst-rec-main analyst-rec-${escapeHtml(action)}">
            <i class="bi ${escapeHtml(icon)} analyst-rec-icon"></i>
            <span class="analyst-rec-label">${escapeHtml(rec.label || "Unavailable")}</span>
        </div>
        <div class="analyst-rec-subtext">${escapeHtml(rec.subtext || "")}</div>
    </div>`;
}

async function loadAnalystRecommendations() {
    try {
        const res = await fetch("/api/ai/analyst-recommendations/all");
        if (!res.ok) return;
        const data = await res.json();
        Object.entries(data.recommendations || {}).forEach(([ticker, rec]) => {
            cachedRecommendations[ticker] = rec;
            const cell = document.getElementById(`rec-cell-${ticker}`);
            if (cell) cell.innerHTML = renderAnalystRecCell(rec);
            if (intelligenceLoaded && cachedIntelligence[ticker]) {
                const row = document.querySelector(`tr[data-ticker="${ticker}"]`);
                const expandRow = row?.nextElementSibling;
                const coverageSection = expandRow?.querySelector(".intel-coverage-section");
                if (coverageSection) renderHoldingCoverage(coverageSection, cachedIntelligence[ticker]);
            }
        });
    } catch (err) {
        console.warn("Analyst recommendations unavailable:", err);
    }
}

document.addEventListener("DOMContentLoaded", initDashboard);

function refreshData() {
    loadPortfolioValue();
    loadPnl();
    updateMarketStatus();
}


async function updateMarketStatus() {
    try {
        const res = await fetch("/api/stocks/market-status");
        const data = await res.json();
        const el = document.getElementById("market-status");
        if (el) {
            el.textContent = data.status;
            el.className = data.is_open ? "stat-value text-success" : "stat-value text-secondary";
        }
        const icon = document.getElementById("market-icon");
        if (icon) {
            icon.style.background = data.is_open
                ? "rgba(48,209,88,.13)"
                : "rgba(235,235,245,.06)";
            icon.style.color = data.is_open ? "#30d158" : "var(--text-tertiary)";
            icon.classList.toggle("market-open", !!data.is_open);
        }
    } catch(e) {}
}

function startCountdown() {
    let refreshCountdown = 300;
    const interval = setInterval(() => {
        refreshCountdown--;
        const el = document.getElementById("countdown");
        if (el) el.textContent = `Next refresh in ${refreshCountdown}s`;
        if (refreshCountdown <= 0) {
            clearInterval(interval);
            loadPortfolioValue().then(() => {
                loadPnl();
                updateMarketStatus();
                startCountdown();
            });
        }
    }, 1000);
}

document.addEventListener("keydown", (e) => {
    const tag = e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) return;
    if (e.key === "r" || e.key === "R") refreshData();
});

async function initDashboard() {
    await loadPortfolioValue();
    await loadPnl();
    await updateMarketStatus();
    // Fire without blocking — prices and P&L are already visible
    loadAnalystRecommendations();
    startCountdown();
}


// ── Holding Intelligence ────────────────────────────────────────────────────

async function loadHoldingIntelligence() {
    const tbody = document.getElementById("holdings-table");
    const btn = document.querySelector('[onclick="loadHoldingIntelligence()"]');

    if (intelligenceLoaded) {
        // Toggle expand rows open/closed on repeated click
        const allBodies = tbody.querySelectorAll(".summary-body");
        const anyOpen = Array.from(allBodies).some(b => b.classList.contains("open"));
        allBodies.forEach(b => b.classList.toggle("open", !anyOpen));
        tbody.querySelectorAll("tr[data-ticker]").forEach(r => r.classList.toggle("summary-open", !anyOpen));
        return;
    }

    intelligenceLoading = true;
    injectSummaryRows(tbody);
    if (btn) {
        btn.innerHTML = '<div class="spinner-border spinner-border-sm me-1" style="color:#64d2ff"></div> Analyzing…';
        btn.disabled = true;
    }

    try {
        // Fetch both data sources in parallel
        const [intelRes, moveRes] = await Promise.all([
            fetch("/api/ai/intelligence/all/batch"),
            fetch("/api/ai/move-explanations/all"),
        ]);

        if (intelRes.ok) {
            const intelData = await intelRes.json();
            Object.entries(intelData.intelligence || {}).forEach(([ticker, intel]) => {
                cachedIntelligence[ticker] = intel;
            });
        }

        if (moveRes.ok) {
            const moveData = await moveRes.json();
            Object.entries(moveData.explanations || {}).forEach(([ticker, exp]) => {
                cachedExplanations[ticker] = exp;
            });
        }

        intelligenceLoaded = true;
        intelligenceLoading = false;

        // Render all expanded rows
        Array.from(tbody.querySelectorAll("tr[data-ticker]")).forEach(mainRow => {
            const ticker = mainRow.dataset.ticker;
            const expandRow = mainRow.nextElementSibling;
            if (!expandRow || !expandRow.classList.contains("summary-expand-row")) return;
            const coverageSection = expandRow.querySelector(".intel-coverage-section");
            const moveSection     = expandRow.querySelector(".intel-move-section");
            if (coverageSection) renderHoldingCoverage(coverageSection, cachedIntelligence[ticker]);
            if (moveSection)     renderMoveExplainer(moveSection, cachedExplanations[ticker]);
        });

        // Update compact badges in the holdings table
        Object.entries(cachedExplanations).forEach(([ticker, exp]) => {
            const badge = document.getElementById(`move-badge-${ticker}`);
            if (!badge) return;
            badge.textContent = ATTRIBUTION_SHORT[exp.attribution_type] || "?";
            badge.className = `move-badge ${exp.attribution_type}`;
            badge.title = `${exp.confidence} confidence`;
        });

    } catch (err) {
        intelligenceLoading = false;
        intelligenceLoaded = true;
        Array.from(tbody.querySelectorAll(".intel-coverage-section")).forEach(s => {
            s.innerHTML = `<div class="intel-coverage"><span style="font-size:.75rem;color:var(--accent-red)">Could not load coverage data</span></div>`;
        });
    } finally {
        if (btn) {
            btn.innerHTML = '<i class="bi bi-layers"></i> Holding Intel';
            btn.disabled = false;
        }
    }
}


// ── Portfolio Management Modal ──────────────────────────────────────────────

async function loadManageHoldings() {
    const res = await fetch("/api/portfolio/holdings");
    const data = await res.json();
    const tbody = document.getElementById("manage-holdings-table");
    tbody.innerHTML = "";

    data.holdings.forEach(h => {
        const row = tbody.insertRow();
        row.innerHTML = `
            <td class="fw-bold">${h.ticker}</td>
            <td>
                <input type="number" value="${h.shares}" min="0.001" step="0.001"
                       class="form-control form-control-sm bg-dark border-secondary
                              text-white d-inline" style="width:90px"
                       id="shares-${h.id}">
            </td>
            <td>
                <input type="number" value="${h.avg_cost || ""}" min="0.01" step="0.01"
                       class="form-control form-control-sm bg-dark border-secondary
                              text-white d-inline" style="width:90px"
                       id="cost-${h.id}" placeholder="--">
            </td>
            <td>
                <button class="btn btn-sm btn-outline-primary me-1"
                        onclick="updateHolding(${h.id})">
                    <i class="bi bi-check"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger"
                        onclick="removeHolding(${h.id}, '${h.ticker}')">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;
    });
}


async function updateHolding(holdingId) {
    const shares = parseFloat(document.getElementById(`shares-${holdingId}`).value);
    const avgCost = parseFloat(document.getElementById(`cost-${holdingId}`).value) || null;

    if (isNaN(shares) || shares <= 0) {
        alert("Shares must be a positive number");
        return;
    }

    const res = await fetch(`/api/portfolio/holdings/${holdingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shares, avg_cost: avgCost }),
    });
    if (res.ok) {
        showToast("Holding updated!", "success");
        loadPortfolioValue();
        loadPnl();
    } else {
        showToast("Update failed", "danger");
    }
}


async function removeHolding(holdingId, ticker) {
    if (!confirm(`Remove ${ticker} from your portfolio?`)) return;

    const res = await fetch(`/api/portfolio/holdings/${holdingId}`, {
        method: "DELETE"
    });
    if (res.ok) {
        showToast(`${ticker} removed`, "warning");
        loadManageHoldings();
        loadPortfolioValue();
        loadPnl();
    }
}


document.getElementById("add-holding-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticker = document.getElementById("new-ticker").value.trim().toUpperCase();
    const shares = parseFloat(document.getElementById("new-shares").value);
    const avgCost = parseFloat(document.getElementById("new-avgcost").value) || null;

    const res = await fetch("/api/portfolio/holdings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, shares, avg_cost: avgCost }),
    });
    const msg = document.getElementById("add-msg");
    if (res.ok) {
        msg.className = "ms-2 small text-success";
        msg.textContent = `${ticker} added!`;
        e.target.reset();
        loadManageHoldings();
        loadPortfolioValue();
        loadPnl();
    } else {
        const err = await res.json();
        msg.className = "ms-2 small text-danger";
        msg.textContent = err.detail || "Error adding holding";
    }
});


function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `alert alert-${type} position-fixed bottom-0 end-0 m-3`;
    toast.style.zIndex = "9999";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
