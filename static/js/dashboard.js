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
 
        // Update allocation breakdown table
        const allocTable = document.getElementById("allocation-table");
        allocTable.innerHTML = "";
        data.holdings.forEach((h, i) => {
            const row = allocTable.insertRow();
            row.innerHTML = `
                <td><span class="badge" style="background:${CHART_COLORS[i]}">&nbsp;</span>
                    ${h.ticker}</td>
                <td>${h.shares}</td>
                <td class="text-end">${formatCurrency(h.current_value)}</td>
                <td class="text-end">${formatAllocationPct(h.allocation_pct)}</td>
            `;
        });
 
        // Build or update the doughnut chart
        const labels = data.holdings.map(h => h.ticker);
        const values = data.holdings.map(h => h.current_value);
 
        if (allocationChart) {
            allocationChart.data.labels = labels;
            allocationChart.data.datasets[0].data = values;
            allocationChart.update();
        } else {
            const ctx = document.getElementById("allocation-chart").getContext("2d");
            allocationChart = new Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: labels,
                    datasets: [{
                        data: values,
                        backgroundColor: CHART_COLORS,
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
        const trendData = await loadTrendData(data.holdings.map(h => h.ticker));
        updateHoldingsTable(data.holdings, trendData);
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
    refreshCountdown = 300;
    const interval = setInterval(() => {
        refreshCountdown--;
        const el = document.getElementById("countdown");
        if (el) el.textContent = `Next refresh in ${refreshCountdown}s`;
        if (refreshCountdown <= 0) {
            clearInterval(interval);
            loadPortfolioValue().then(startCountdown);
        }
    }, 1000);
}
 
// Keyboard shortcut: R to refresh
document.addEventListener("keydown", (e) => {
    if (e.key === "r" || e.key === "R") refreshData();
});
 
// Update the initDashboard function:
async function initDashboard() {
    await loadSparklineData();
    await loadPortfolioValue();
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
