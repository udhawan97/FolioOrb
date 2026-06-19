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
const formatPct = (n) => {
    const value = toNumber(n);
    return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
};
const formatAllocationPct = (n) => `${toNumber(n).toFixed(1)}%`;
const colorClass = (v) => v >= 0 ? "text-success" : "text-danger";
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
 
let allocationChart = null;  // Keep chart instance for updates
let latestHoldings = [];     // Most recent holdings, for re-sorting without a refetch
let latestTrendData = {};    // Cached sparkline data, so the Holdings table re-sorts without a refetch
let allocSortDir = "desc";   // Allocation sort direction: "desc" | "asc"
let allocationTotal = 0;     // Portfolio total, drawn in the doughnut's center

// Single source of truth for allocation ordering, shared by both tables and the chart.
function sortedByAllocation(holdings) {
    const dir = allocSortDir === "asc" ? 1 : -1;
    return [...holdings].sort(
        (a, b) => dir * (toNumber(a.allocation_pct) - toNumber(b.allocation_pct))
    );
}

// Keep every "sort by allocation" caret pointing the same way.
function updateSortCarets() {
    const cls = `bi small ${allocSortDir === "asc" ? "bi-caret-up-fill" : "bi-caret-down-fill"}`;
    ["alloc-sort-caret", "holdings-alloc-caret"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.className = cls;
    });
}
 
 
async function loadPortfolioValue() {
    try {
        const res = await fetch("/api/portfolio/value");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
 
        // Update summary cards
        document.getElementById("total-value").textContent =
            formatCurrency(data.total_value);
        document.getElementById("holding-count").textContent =
            data.holdings.length;
        document.getElementById("daily-pnl").innerHTML =
            `<span class="${colorClass(data.total_daily_change)}">
             ${formatCurrency(data.total_daily_change)}
             (${formatPct(data.total_daily_change_pct)})</span>`;

        // Cumulative profit/loss summary (realized + unrealized)
        renderTotalReturn(data);

        // Render the allocation breakdown table and matching doughnut chart
        latestHoldings = data.holdings;
        renderAllocation();

        // Update best/worst/largest cards
        if (data.best_performer) {
            document.getElementById("best-performer").textContent =
                `${data.best_performer.ticker} ${formatPct(data.best_performer.day_change_pct)}`;
        }
        if (data.worst_performer) {
            document.getElementById("worst-performer").textContent =
                `${data.worst_performer.ticker} ${formatPct(data.worst_performer.day_change_pct)}`;
        }
        if (data.holdings.length) {
            const largest = data.holdings.reduce((a, b) =>
                a.current_value > b.current_value ? a : b);
            document.getElementById("largest-holding").textContent =
                `${largest.ticker} ${formatCurrency(largest.current_value)}`;
        }

        // Also update the basic prices table (same allocation order as the chart)
        latestTrendData = await loadTrendData(data.holdings.map(h => h.ticker));
        renderHoldings();
        document.getElementById("last-updated").textContent =
            `Updated: ${new Date().toLocaleTimeString()}`;
 
    } catch (err) {
        console.error("Error loading portfolio value:", err);
    }
}


// Render the allocation breakdown table and the doughnut chart in the same
// (allocation-sorted) order, so the pie slices line up with the table rows.
function renderAllocation() {
    const sorted = sortedByAllocation(latestHoldings);

    // Table
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

    // Doughnut chart, using the same sorted order
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
                    // Transparent border + spacing gives crisp, separated segments.
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
                cutout: "72%",            // thin, modern ring
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

// Render the Holdings table in the current allocation order.
function renderHoldings() {
    updateHoldingsTable(sortedByAllocation(latestHoldings), latestTrendData);
    updateSortCarets();
}

// Clicking either allocation header toggles sort direction and re-renders
// the breakdown table, the Holdings table, and the chart together.
function toggleAllocationSort() {
    allocSortDir = allocSortDir === "asc" ? "desc" : "asc";
    renderAllocation();
    renderHoldings();
}


// A signed currency string, e.g. "+$1,234.56" / "-$78.90".
const formatSignedCurrency = (n) =>
    `${toNumber(n) >= 0 ? "+" : "-"}${formatCurrency(Math.abs(toNumber(n)))}`;

// Total Return card: cumulative realized + unrealized P&L from /value.
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


let pnlChart = null;  // Chart instance for the performance-history line

// Fetch the P&L ledger + snapshot history and render the chart and trades table.
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

    // Soft vertical gradient fill under the line.
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
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-secondary py-4">
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
    holdings.forEach(h => {
        const row = tbody.insertRow();
        row.innerHTML = `
            <td class="fw-bold">${h.ticker}</td>
            <td class="d-none d-md-table-cell text-secondary small">${h.name.substring(0, 28)}</td>
            <td class="text-end">${formatCurrency(h.current_price)}</td>
            <td class="text-end ${colorClass(h.day_change_pct)}">
                ${formatPct(h.day_change_pct)}</td>
            <td class="text-end d-none d-md-table-cell">${formatCurrency(h.current_value)}</td>
            <td class="text-end">${formatAllocationPct(h.allocation_pct)}</td>
            <td class="text-center d-none d-xl-table-cell trend-cell"></td>
        `;
        const canvas = document.createElement("canvas");
        canvas.className = "trend-sparkline";
        canvas.width = 120;
        canvas.height = 32;
        canvas.setAttribute("aria-label", `${h.ticker} ${TREND_DAYS}-day trend`);
        row.querySelector(".trend-cell").appendChild(canvas);
        drawTrend(canvas, trendData[h.ticker]);
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
 
 
document.addEventListener("DOMContentLoaded", initDashboard);

// Refresh everything that can go stale: live values, P&L, and market status.
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
            el.className = data.is_open
                ? "fs-4 fw-bold text-success"
                : "fs-4 fw-bold text-secondary";
        }
    } catch(e) {}
}
 
// Countdown timer
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
 
// Keyboard shortcut: R to refresh
document.addEventListener("keydown", (e) => {
    const tag = e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) return;
    if (e.key === "r" || e.key === "R") refreshData();
});
 
async function initDashboard() {
    await loadPortfolioValue();
    await loadPnl();
    await updateMarketStatus();
    startCountdown();
}

// Load holdings into the management modal
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
        loadPortfolioValue();  // Refresh totals (and any realized P&L from a reduction)
        loadPnl();             // Refresh the ledger + performance chart
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
        loadManageHoldings();  // Refresh the modal list
        loadPortfolioValue();  // Refresh the main dashboard
        loadPnl();             // The full-position sale lands in the ledger
    }
}
 
 
// Add holding form submission
document.getElementById("add-holding-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();  // Prevent page reload
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
 
 
// Simple toast notification
function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `alert alert-${type} position-fixed bottom-0 end-0 m-3`;
    toast.style.zIndex = "9999";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
