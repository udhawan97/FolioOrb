/**
 * dashboard.js
 * Fetches stock data from our FastAPI backend and updates the UI.
 * Runs automatically when the page loads.
 */
 
// Format a number as currency: 547.23 → "$547.23"
const formatCurrency = (num) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(num);
 
// Format percentage: 0.61 → "+0.61%"
const formatPct = (num) => `${num >= 0 ? "+" : ""}${num.toFixed(2)}%`;
 
// Return Bootstrap color class based on value
const colorClass = (val) => val >= 0 ? "text-success" : "text-danger";
 
 
// Main data loading function
async function loadPrices() {
    try {
        // fetch() makes an HTTP request to our FastAPI API
        // "await" pauses here until the response arrives
        const response = await fetch("/api/stocks/prices");
 
        // Check if request succeeded (status 200)
        if (!response.ok) throw new Error(`HTTP error: ${response.status}`);
 
        // Parse the JSON response body
        const data = await response.json();
        const quotes = data.quotes;
 
        // Update the holdings table
        const tbody = document.getElementById("holdings-table");
        tbody.innerHTML = "";  // Clear the loading spinner
 
        let totalDailyChange = 0;
 
        quotes.forEach(q => {
            if (q.error) return;  // Skip tickers with errors
 
            totalDailyChange += q.day_change;
 
            // Create a table row for this holding
            const row = document.createElement("tr");
            row.innerHTML = `
                <td class="fw-bold">${q.ticker}</td>
                <td class="text-secondary small">${q.name.substring(0, 30)}</td>
                <td class="text-end">${formatCurrency(q.current_price)}</td>
                <td class="text-end ${colorClass(q.day_change_pct)}">
                    ${formatPct(q.day_change_pct)}
                    <small class="d-block text-muted">${formatCurrency(q.day_change)}</small>
                </td>
                <td class="text-end small text-secondary">
                    ${formatCurrency(q.fifty_two_week_low)} –
                    ${formatCurrency(q.fifty_two_week_high)}
                </td>
            `;
            tbody.appendChild(row);
        });
 
        // Update summary cards
        document.getElementById("daily-pnl").innerHTML =
            `<span class="${colorClass(totalDailyChange)}">
             ${formatCurrency(totalDailyChange)}</span>`;
 
        document.getElementById("last-updated").textContent =
            `Updated: ${new Date().toLocaleTimeString()}`;
 
    } catch (error) {
        console.error("Failed to load prices:", error);
        document.getElementById("holdings-table").innerHTML =
            `<tr><td colspan="5" class="text-center text-danger py-3">
             Error loading data: ${error.message}</td></tr>`;
    }
}
 
 
function refreshData() {
    document.getElementById("holdings-table").innerHTML =
        `<tr><td colspan="5" class="text-center py-4">
         <div class="spinner-border spinner-border-sm text-secondary"></div>
         Refreshing...</td></tr>`;
    loadPrices();
}
 
 
// Load data when the page opens
document.addEventListener("DOMContentLoaded", loadPrices);
 
// Auto-refresh every 5 minutes (300,000 milliseconds)
setInterval(loadPrices, 300000);
