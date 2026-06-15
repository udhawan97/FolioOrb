/**
 * dashboard.js
 * Fetches stock data from our FastAPI backend and updates the UI.
 * Runs automatically when the page loads.
 */
 
const formatCurrency = (n) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
const formatPct = (n) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
const colorClass = (v) => v >= 0 ? "text-success" : "text-danger";
 
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
                <td class="text-end">${h.allocation_pct}%</td>
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
 
        // Also update the basic prices table
        updateHoldingsTable(data.holdings);
        document.getElementById("last-updated").textContent =
            `Updated: ${new Date().toLocaleTimeString()}`;
 
    } catch (err) {
        console.error("Error loading portfolio value:", err);
    }
}
 
 
function updateHoldingsTable(holdings) {
    const tbody = document.getElementById("holdings-table");
    tbody.innerHTML = "";
    holdings.forEach(h => {
        const row = tbody.insertRow();
        row.innerHTML = `
            <td class="fw-bold">${h.ticker}</td>
            <td class="text-secondary small">${h.name.substring(0, 28)}</td>
            <td class="text-end">${formatCurrency(h.current_price)}</td>
            <td class="text-end ${colorClass(h.day_change_pct)}">
                ${formatPct(h.day_change_pct)}</td>
            <td class="text-end">${h.allocation_pct}%</td>
        `;
    });
}
 
 
document.addEventListener("DOMContentLoaded", loadPortfolioValue);
setInterval(loadPortfolioValue, 300000);
 
function refreshData() { loadPortfolioValue(); }