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
 
// Chart.js color palette
const CHART_COLORS = [
    "#4299e1","#48bb78","#ed8936","#9f7aea","#f56565",
    "#38b2ac","#ecc94b","#ed64a6","#667eea","#81e6d9"
];
 
let allocationChart = null;  // Keep chart instance for updates
let allocationSortDir = 'desc';  // 'asc' or 'desc'
let cachedHoldings = [];
let cachedTrendData = {};


function getSortedHoldings() {
    return [...cachedHoldings].sort((a, b) =>
        allocationSortDir === 'desc'
            ? b.allocation_pct - a.allocation_pct
            : a.allocation_pct - b.allocation_pct
    );
}

function toggleAllocationSort() {
    allocationSortDir = allocationSortDir === 'desc' ? 'asc' : 'desc';
    const sorted = getSortedHoldings();
    renderAllocationTable(sorted);
    renderAllocationChart(sorted);
    updateHoldingsTable(sorted, cachedTrendData);
    updateSortIcons();
}

function updateSortIcons() {
    const iconClass = allocationSortDir === 'desc' ? 'bi-sort-down' : 'bi-sort-up';
    document.querySelectorAll('.alloc-sort-icon').forEach(el => {
        el.className = `bi ${iconClass} ms-1`;
    });
}

function renderAllocationTable(holdings) {
    const allocTable = document.getElementById("allocation-table");
    allocTable.innerHTML = "";
    holdings.forEach((h, i) => {
        const row = allocTable.insertRow();
        row.innerHTML = `
            <td><span class="badge" style="background:${CHART_COLORS[i % CHART_COLORS.length]}">&nbsp;</span>
                ${h.ticker}</td>
            <td>${h.shares}</td>
            <td class="text-end">${formatCurrency(h.current_value)}</td>
            <td class="text-end">${formatAllocationPct(h.allocation_pct)}</td>
        `;
    });
}

function renderAllocationChart(holdings) {
    const labels = holdings.map(h => h.ticker);
    const values = holdings.map(h => h.current_value);
    const colors = holdings.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]);

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
                    borderColor: "#1a1a2e",
                    borderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) =>
                                ` ${ctx.label}: ${formatCurrency(ctx.raw)}`
                        }
                    }
                }
            }
        });
    }
}


async function loadPortfolioValue() {
    try {
        const res = await fetch("/api/portfolio/value");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Update summary cards
        document.getElementById("total-value").textContent =
            formatCurrency(data.total_value);
        document.getElementById("daily-pnl").innerHTML =
            `<span class="${colorClass(data.total_daily_change)}">
             ${formatCurrency(data.total_daily_change)}
             (${formatPct(data.total_daily_change_pct)})</span>`;

        // Cache holdings for re-sorting
        cachedHoldings = data.holdings;
        const sorted = getSortedHoldings();

        renderAllocationTable(sorted);
        renderAllocationChart(sorted);
        updateSortIcons();

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

        // Also update the basic prices table
        cachedTrendData = await loadTrendData(data.holdings.map(h => h.ticker));
        updateHoldingsTable(sorted, cachedTrendData);
        document.getElementById("last-updated").textContent =
            `Updated: ${new Date().toLocaleTimeString()}`;

    } catch (err) {
        console.error("Error loading portfolio value:", err);
    }
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
 
 
document.addEventListener("DOMContentLoaded", loadPortfolioValue);
setInterval(loadPortfolioValue, 300000);
 
function refreshData() { loadPortfolioValue(); }
