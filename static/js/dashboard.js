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
const formatUsdTiny = (n) => {
    const value = toNumber(n);
    if (value > 0 && value < 0.01) return `$${value.toFixed(4)}`;
    return `$${value.toFixed(2)}`;
};
const formatCompactNumber = (n) => {
    const value = toNumber(n);
    const abs = Math.abs(value);
    const sign = value < 0 ? "-" : "";
    if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`;
    if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
    return `${Math.round(value)}`;
};

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
const THEME_KEY = "foliosense-theme";
const TEXT_SIZE_KEY = "foliosense-text-size";

const currentTheme = () =>
    document.documentElement.dataset.bsTheme === "light" ? "light" : "dark";

const currentTextSize = () =>
    document.documentElement.dataset.textSize === "comfortable" ? "comfortable" : "standard";

const cssVar = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const uiScale = () => toNumber(cssVar("--ui-scale"), 1);
const prefersReducedMotion = () =>
    window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;

function chartTheme() {
    const isLight = currentTheme() === "light";
    return {
        tooltipBg: isLight ? "rgba(255,255,255,0.96)" : "rgba(28,28,34,0.92)",
        tooltipTitle: cssVar("--text-primary") || (isLight ? "#101828" : "#f5f5f7"),
        tooltipBody: cssVar("--text-secondary") || (isLight ? "rgba(16,24,40,0.68)" : "rgba(235,235,245,0.85)"),
        tooltipBorder: cssVar("--hairline") || (isLight ? "rgba(31,41,55,0.11)" : "rgba(255,255,255,0.12)"),
        tick: cssVar("--text-tertiary") || (isLight ? "rgba(16,24,40,0.45)" : "rgba(235,235,245,0.42)"),
        grid: isLight ? "rgba(15,23,42,.08)" : "rgba(255,255,255,.06)",
    };
}

function tooltipOptions() {
    const theme = chartTheme();
    const isLight = currentTheme() === "light";
    return {
        backgroundColor: isLight ? "rgba(255,255,255,0.90)" : "rgba(12,12,18,0.90)",
        titleColor: theme.tooltipTitle,
        bodyColor: theme.tooltipBody,
        borderColor: theme.tooltipBorder,
        borderWidth: 1,
        cornerRadius: 12,
        padding: 12,
        caretSize: 5,
        caretPadding: 6,
    };
}

function applyTheme(theme, persist = false) {
    const resolved = theme === "light" ? "light" : "dark";
    const isDark = resolved === "dark";
    document.documentElement.dataset.bsTheme = resolved;
    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
        toggle.setAttribute("aria-pressed", String(isDark));
        toggle.setAttribute("aria-label", `Switch to ${isDark ? "light" : "dark"} mode`);
        toggle.title = `Switch to ${isDark ? "light" : "dark"} mode`;
    }
    const toggleIcon = document.getElementById("theme-toggle-icon");
    if (toggleIcon) {
        toggleIcon.className = [
            "bi",
            isDark ? "bi-moon-stars-fill" : "bi-sun-fill",
            "theme-toggle-thumb-icon",
            isDark ? "theme-toggle-thumb-icon-dark" : "theme-toggle-thumb-icon-light",
        ].join(" ");
    }
    if (persist) animateToggle(toggle);
    if (persist) {
        try { localStorage.setItem(THEME_KEY, resolved); } catch (_) {}
    }
    refreshThemeAwareVisuals();
}

function animateToggle(toggle) {
    if (!toggle) return;
    toggle.classList.remove("is-animating");
    void toggle.offsetWidth;
    toggle.classList.add("is-animating");
    window.setTimeout(() => toggle.classList.remove("is-animating"), 420);
}

function initThemeToggle() {
    let saved = null;
    try { saved = localStorage.getItem(THEME_KEY); } catch (_) {}
    const initial = saved || currentTheme();
    applyTheme(initial, false);

    const toggle = document.getElementById("theme-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", () => {
        const next = currentTheme() === "dark" ? "light" : "dark";
        applyTheme(next, true);
    });
}

function refreshThemeAwareVisuals() {
    updateChartChrome(allocationChart);
    updateChartChrome(pnlChart);
    if (latestHoldings.length) renderHoldings();
}

function updateChartChrome(chart) {
    if (!chart?.options) return;
    const theme = chartTheme();
    if (chart.options.plugins?.tooltip) {
        Object.assign(chart.options.plugins.tooltip, tooltipOptions());
    }
    if (chart.options.scales?.x?.ticks) chart.options.scales.x.ticks.color = theme.tick;
    if (chart.options.scales?.y?.ticks) chart.options.scales.y.ticks.color = theme.tick;
    if (chart.options.scales?.y?.grid) chart.options.scales.y.grid.color = theme.grid;
    const scale = uiScale();
    if (chart.options.scales?.x?.ticks?.font) chart.options.scales.x.ticks.font.size = 10 * scale;
    if (chart.options.scales?.y?.ticks?.font) chart.options.scales.y.ticks.font.size = 10 * scale;
    if (chart === allocationChart && chart.data?.datasets?.[0]) {
        chart.data.datasets[0].borderColor = allocBorderColor();
    }
    chart.update("none");
}

function applyTextSize(size, persist = false) {
    const resolved = size === "comfortable" ? "comfortable" : "standard";
    document.documentElement.dataset.textSize = resolved;
    const toggle = document.getElementById("text-size-toggle");
    if (toggle) {
        const comfortable = resolved === "comfortable";
        toggle.setAttribute("aria-pressed", String(comfortable));
        toggle.setAttribute("aria-label", `Switch to ${comfortable ? "standard" : "comfortable"} text size`);
        toggle.title = `Switch to ${comfortable ? "standard" : "comfortable"} text size`;
    }
    if (persist) animateToggle(toggle);
    if (persist) {
        try { localStorage.setItem(TEXT_SIZE_KEY, resolved); } catch (_) {}
    }
    refreshThemeAwareVisuals();
}

function initTextSizeToggle() {
    let saved = null;
    try { saved = localStorage.getItem(TEXT_SIZE_KEY); } catch (_) {}
    applyTextSize(saved || currentTextSize(), false);

    const toggle = document.getElementById("text-size-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", () => {
        const next = currentTextSize() === "comfortable" ? "standard" : "comfortable";
        applyTextSize(next, true);
    });
}

function initPerformanceTabs() {
    const perfTab = document.getElementById("performance-history-tab");
    if (!perfTab) return;

    perfTab.addEventListener("shown.bs.tab", () => {
        if (!pnlChart) return;
        pnlChart.resize();
        pnlChart.update("none");
    });
}

// Apple-inspired vivid palette: high-chroma hues with enough separation for quick scanning.
// Badges use these at full opacity; the doughnut gets a slight glass softening below.
const CHART_COLORS = [
    "rgba(0, 122, 255, 1)",       // system blue
    "rgba(48, 209, 88, 1)",       // system green
    "rgba(255, 149, 0, 1)",       // system orange
    "rgba(191, 90, 242, 1)",      // system purple
    "rgba(90, 200, 250, 1)",      // system cyan
    "rgba(255, 45, 85, 1)",       // system pink
    "rgba(255, 204, 0, 1)",       // system yellow
    "rgba(88, 86, 214, 1)",       // system indigo
    "rgba(0, 199, 190, 1)",       // system teal
    "rgba(175, 82, 222, 1)",      // system violet
];
// Wrap around the palette so portfolios with >10 holdings still get colors.
const chartColor = (i) => CHART_COLORS[i % CHART_COLORS.length];

// Glass-opacity version for doughnut segments; keeps the palette vivid with material depth.
const allocColor = (i) => chartColor(i).replace(/[\d.]+\)$/, "0.94)");
const withAlpha = (rgba, alpha) => rgba.replace(/[\d.]+\)$/, `${alpha})`);

// Background-matching border for clean segment separation — works in both themes.
const allocBorderColor = () =>
    currentTheme() === "dark" ? "#0a0a0f" : "#f2f2f7";

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
let _hasLoadedOnce = false;  // True after first successful data load

// Doughnut center hover / selection state
let hoveredCenterLabel = null;
let hoveredCenterValue = null;
let hoveredCenterPct = null;
let selectedAllocationTicker = null;  // persists after click

// Holding Intelligence state (covers "What It Covers" + "Why it moved")
let cachedIntelligence = {};   // ticker → intelligence object (coverage data)
let cachedExplanations = {};   // ticker → explanation object (move data)
let intelligenceLoaded = false;
let intelligenceLoading = false;
let intelligenceRetryState = {}; // ticker → number of retry attempts
let intelligenceRetryingTickers = new Set();
let intelligenceExhaustedTickers = new Set();

// Rating state: stock analyst ratings or ETF quality labels
let cachedRecommendations = {};  // ticker → rec object from /api/ai/analyst-recommendations/all
let aiCheckInterval = null;

const AI_CHECK_MESSAGES = [
    "Reading positions",
    "Matching benchmarks",
    "Checking catalysts",
    "Scoring context",
    "Writing notes",
];

const CLAUDE_FUNNY_MESSAGES = [
    "Sliding into Claude's DMs for your portfolio tea...",
    "She read it. Now typing. Always delivers — just takes her 30–60s.",
    "Claude has entered the chat. Your stonks don't stand a chance.",
    "Still typing... she's very thorough. Or judging your YOLO plays.",
    "Claude is cooking. Your portfolio is about to get roasted — lovingly.",
    "She's seen your allocations. She's choosing her words carefully.",
];
let claudeMessageIndex = 0;

const INTEL_BUTTON_READY_HTML = `
    <span class="btn-intel-frame">
        <span class="btn-intel-glyph">
            <img class="btn-intel-logo btn-intel-icon" src="/static/img/brand/folio-orbit-icon.svg" alt="">
        </span>
        <span class="btn-intel-text">
            <span class="btn-intel-command">Holding Intel</span>
        </span>
        <span class="btn-intel-badge">AI</span>
    </span>
`;

const INTEL_BUTTON_LOADING_HTML = `
    <span class="btn-intel-frame">
        <span class="btn-intel-glyph">
            <img class="btn-intel-logo btn-intel-icon" src="/static/img/brand/folio-orbit-icon.svg" alt="">
        </span>
        <span class="btn-intel-text">
            <span class="btn-intel-command">Scanning</span>
        </span>
        <span class="btn-intel-badge">AI</span>
    </span>
`;

const INTELLIGENCE_MAX_RETRIES = 3;
const INTELLIGENCE_RETRY_BASE_DELAY_MS = 900;

function holdingTickers() {
    return latestHoldings.map(h => h.ticker).filter(Boolean);
}

function delay(ms) {
    return new Promise(resolve => window.setTimeout(resolve, ms));
}

function marketPulseLoaded(data) {
    if (!data) return false;
    const status = data.load_status?.market_pulse;
    if (status && typeof status.loaded === "boolean") return status.loaded;
    return buildMarketPulseItems(data).every(item => item.value && item.value !== "Unavailable");
}

function holdingIntelSettled(ticker) {
    return !!cachedIntelligence[ticker] && (
        marketPulseLoaded(cachedIntelligence[ticker]) ||
        intelligenceExhaustedTickers.has(ticker)
    );
}

function allHoldingIntelSettled() {
    const tickers = holdingTickers();
    return tickers.length > 0 && tickers.every(holdingIntelSettled);
}

function incompleteIntelligenceTickers() {
    return holdingTickers().filter(ticker => !holdingIntelSettled(ticker));
}

function updateIntelligenceLoadedState() {
    intelligenceLoaded = allHoldingIntelSettled();
    return intelligenceLoaded;
}

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

function setAgentLine(text) {
    const line = document.getElementById("ai-agent-line");
    if (line) line.textContent = text;
}

function setAgentReadyState(ready, message = "Insights ready") {
    const status = document.getElementById("ai-agent-status");
    const card = document.getElementById("holdings-card");

    if (card) card.classList.toggle("has-ai-insights", ready);
    if (!status) return;

    if (ready) setAgentLine(message);
    status.hidden = !ready;
    status.setAttribute("aria-hidden", ready ? "false" : "true");
    status.classList.toggle("is-ready", ready);
}

const SCAN_ROW_LABELS = ["Scanning", "Reading", "Analyzing", "Processing", "Checking", "Fetching", "Loading", "Parsing", "Resolving"];

function renderAiScanTickers() {
    const tickerRail = document.getElementById("ai-scan-tickers");
    if (!tickerRail) return;

    const tickers = latestHoldings
        .map(h => h.ticker)
        .filter(Boolean)
        .slice(0, 12);

    tickerRail.innerHTML = tickers.map((ticker, index) => {
        const phase = ((index * 0.6180339887) % 1).toFixed(3);
        return `<div class="ai-scan-row" style="--row-index:${index};--row-phase:${phase}">
            <span class="ai-scan-row-dot" aria-hidden="true"></span>
            <span class="ai-scan-row-ticker">${escapeHtml(ticker)}</span>
            <span class="ai-scan-row-bar" aria-hidden="true"><span class="ai-scan-row-fill" style="--row-index:${index}"></span></span>
            <span class="ai-scan-row-label">${SCAN_ROW_LABELS[index % SCAN_ROW_LABELS.length]}</span>
        </div>`;
    }).join("");
}

function setAiChecking(active, message = "Reading positions", insightsReady = false) {
    const card = document.getElementById("holdings-card");
    const panel = document.getElementById("ai-scan-panel");
    const subtitle = document.getElementById("ai-scan-subtitle");

    if (aiCheckInterval) {
        clearInterval(aiCheckInterval);
        aiCheckInterval = null;
    }

    if (!card) return;

    if (!active) {
        card.classList.remove("is-ai-checking");
        if (panel) panel.setAttribute("aria-hidden", "true");
        setAgentReadyState(insightsReady, message);
        HoldingsBg.stop();
        return;
    }

    let messageIndex = 0;
    card.classList.add("is-ai-checking");
    setAgentReadyState(false);
    HoldingsBg.stop();
    if (panel) {
        panel.setAttribute("aria-hidden", "false");
        panel.style.setProperty("--scan-travel", `${panel.offsetHeight + 180}px`);
    }
    renderAiScanTickers();
    setAgentLine(message);
    claudeMessageIndex = 0;
    const CLAUDE_FLIRT_BEAT = 2;
    const CLAUDE_HOLD_TICKS = 5; // keep Claude message visible for about 4s
    let claudeHoldRemaining = CLAUDE_HOLD_TICKS; // protect the first message too
    if (subtitle) {
        subtitle.textContent = CLAUDE_FUNNY_MESSAGES[0];
        subtitle.classList.add("ai-scan-subtitle--highlight");
        subtitle.classList.add("ai-scan-subtitle--pop");
        subtitle.addEventListener("animationend", () => subtitle.classList.remove("ai-scan-subtitle--pop"), { once: true });
    }
    aiCheckInterval = window.setInterval(() => {
        messageIndex = (messageIndex + 1) % AI_CHECK_MESSAGES.length;
        const next = AI_CHECK_MESSAGES[messageIndex];
        setAgentLine(next);
        if (subtitle) {
            const isClaudeBeat = messageIndex === CLAUDE_FLIRT_BEAT;
            if (isClaudeBeat) {
                claudeMessageIndex = (claudeMessageIndex + 1) % CLAUDE_FUNNY_MESSAGES.length;
                claudeHoldRemaining = CLAUDE_HOLD_TICKS;
                subtitle.textContent = CLAUDE_FUNNY_MESSAGES[claudeMessageIndex];
                subtitle.classList.remove("ai-scan-subtitle--pop");
                void subtitle.offsetWidth;
                subtitle.classList.add("ai-scan-subtitle--pop");
                subtitle.addEventListener("animationend", () => subtitle.classList.remove("ai-scan-subtitle--pop"), { once: true });
            } else if (claudeHoldRemaining > 0) {
                claudeHoldRemaining--;
                // leave subtitle text and highlight intact while holding
            } else {
                subtitle.textContent = `${next} across ${latestHoldings.length || "your"} holdings.`;
            }
            subtitle.classList.toggle("ai-scan-subtitle--highlight", isClaudeBeat || claudeHoldRemaining > 0);
        }
    }, 800);
}


async function loadPortfolioValue() {
    try {
        const res = await fetch("/api/portfolio/value");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Flash on refresh (not on first load)
        if (_hasLoadedOnce) {
            ["total-value", "daily-pnl", "best-performer", "worst-performer", "largest-holding"].forEach(id => {
                flashValue(document.getElementById(id));
            });
        }

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
            const el = document.getElementById("best-performer");
            el.dataset.ticker = data.best_performer.ticker;
            el.innerHTML = `${data.best_performer.ticker} <span style="font-size:.85em;opacity:.8">${formatPct(data.best_performer.day_change_pct)}</span>`;
        }
        if (data.worst_performer) {
            const el = document.getElementById("worst-performer");
            el.dataset.ticker = data.worst_performer.ticker;
            el.innerHTML = `${data.worst_performer.ticker} <span style="font-size:.85em;opacity:.8">${formatPct(data.worst_performer.day_change_pct)}</span>`;
        }
        if (data.holdings.length) {
            const largest = data.holdings.reduce((a, b) =>
                a.current_value > b.current_value ? a : b);
            const el = document.getElementById("largest-holding");
            el.dataset.ticker = largest.ticker;
            el.innerHTML = `${largest.ticker} <span style="font-size:.85em;opacity:.8">${formatCompact(largest.current_value)}</span>`;
        }

        latestTrendData = await loadTrendData(data.holdings.map(h => h.ticker));
        renderHoldings();
        const updatedEl = document.getElementById("last-updated");
        if (updatedEl) updatedEl.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        const pill = document.getElementById("hud-status-pill");
        if (pill) {
            pill.classList.remove("is-refreshed");
            void pill.offsetWidth;
            pill.classList.add("is-refreshed");
        }
        _hasLoadedOnce = true;

    } catch (err) {
        console.error("Error loading portfolio value:", err);
    }
}


function selectAllocationTicker(ticker) {
    // Toggle deselection if same tile is clicked again
    if (selectedAllocationTicker === ticker) ticker = null;
    selectedAllocationTicker = ticker;

    // Sync allocation breakdown table rows
    const allocTable = document.getElementById("allocation-table");
    if (allocTable) {
        const hasSelection = !!ticker;
        allocTable.classList.toggle("has-selection", hasSelection);
        Array.from(allocTable.rows).forEach(row => {
            row.classList.toggle("alloc-selected", !!ticker && row.dataset.ticker === ticker);
        });
    }

    // Sync chart segment (set active element so the segment pops out)
    if (allocationChart) {
        if (ticker) {
            const idx = allocationChart.data.labels.indexOf(ticker);
            if (idx >= 0) {
                setAllocationFocus(allocationChart, idx);
                allocationChart.setActiveElements([{ datasetIndex: 0, index: idx }]);
            }
        } else {
            setAllocationFocus(allocationChart, -1);
            allocationChart.setActiveElements([]);
        }
        allocationChart.update("none");
    }
}

function allocationImpactForHolding(holding) {
    return toNumber(holding?.current_value) * (toNumber(holding?.day_change_pct) / 100);
}

function allocationTooltipMetrics(ticker, value) {
    const holding = latestHoldings.find(h => h.ticker === ticker);
    const holdingsCount = latestHoldings.length;
    if (!holding || !holdingsCount) return null;

    const rank = sortedByAllocation(latestHoldings)
        .findIndex(h => h.ticker === ticker) + 1;
    const equalWeightValue = allocationTotal / holdingsCount;
    const equalWeightDrift = toNumber(value) - equalWeightValue;
    const impactToday = allocationImpactForHolding(holding);
    const portfolioImpactToday = latestHoldings.reduce(
        (sum, h) => sum + allocationImpactForHolding(h),
        0
    );
    const shareOfMove = Math.abs(portfolioImpactToday) > 0.01
        ? (impactToday / portfolioImpactToday) * 100
        : null;
    const weightPct = allocationTotal > 0 ? (toNumber(value) / allocationTotal) * 100 : 0;
    const stressValue = toNumber(value) * -0.10;
    const stressPct = allocationTotal > 0 ? (stressValue / allocationTotal) * 100 : 0;

    return {
        holding,
        holdingsCount,
        rank,
        equalWeightDrift,
        equalWeightRatio: equalWeightValue > 0 ? equalWeightDrift / equalWeightValue : 0,
        impactToday,
        shareOfMove,
        stressValue,
        stressPct,
        weightPct,
    };
}

function allocationInsightRow(title, value, note, tone = "") {
    return `
        <div class="alloc-popover-row ${tone}">
            <div>
                <span>${escapeHtml(title)}</span>
                <small>${escapeHtml(note)}</small>
            </div>
            <strong>${escapeHtml(value)}</strong>
        </div>`;
}

function getOrCreateAllocationPopover(chart) {
    const parent = chart.canvas.parentNode;
    let popover = parent.querySelector(".alloc-popover");
    if (!popover) {
        popover = document.createElement("div");
        popover.className = "alloc-popover";
        popover.setAttribute("role", "tooltip");
        parent.appendChild(popover);
    }
    return popover;
}

function allocationExternalTooltip({ chart, tooltip }) {
    const popover = getOrCreateAllocationPopover(chart);

    if (!tooltip || tooltip.opacity === 0 || !tooltip.dataPoints?.length) {
        popover.classList.remove("is-visible");
        return;
    }

    const point = tooltip.dataPoints[0];
    const ticker = point.label;
    const value = toNumber(point.raw);
    const color = chart.data.datasets[point.datasetIndex].$baseColors?.[point.dataIndex]
        || chart.data.datasets[point.datasetIndex].backgroundColor?.[point.dataIndex]
        || "rgba(111,214,240,1)";
    const metrics = allocationTooltipMetrics(ticker, value);
    if (!metrics) {
        popover.classList.remove("is-visible");
        return;
    }

    const impactTone = metrics.impactToday > 0 ? "is-positive" : metrics.impactToday < 0 ? "is-negative" : "";
    const concentrationTone = metrics.equalWeightDrift > 0 && Math.abs(metrics.equalWeightRatio) >= 0.35
        ? "is-warning"
        : "";
    const concentrationNote = metrics.equalWeightDrift >= 0
        ? `${formatCurrency(Math.abs(metrics.equalWeightDrift))} more than an even split`
        : `${formatCurrency(Math.abs(metrics.equalWeightDrift))} less than an even split`;
    const todayNote = metrics.shareOfMove !== null
        ? `${Math.abs(metrics.shareOfMove).toFixed(0)}% of today's portfolio change`
        : "Its dollar effect on today's portfolio move";

    popover.innerHTML = `
        <div class="alloc-popover-hero">
            <span class="alloc-popover-dot" style="background:${color}"></span>
            <div>
                <div class="alloc-popover-title">${escapeHtml(ticker)}</div>
                <div class="alloc-popover-subtitle">
                    ${escapeHtml(formatCurrency(value))} · ${metrics.weightPct.toFixed(1)}%
                </div>
            </div>
        </div>
        <div class="alloc-popover-rows">
            ${allocationInsightRow("How much rides on this?", `${metrics.weightPct.toFixed(1)}% · #${metrics.rank}`, concentrationNote, concentrationTone)}
            ${allocationInsightRow("Did it drive today?", formatSignedCurrency(metrics.impactToday), todayNote, impactTone)}
            ${allocationInsightRow("What if it drops 10%?", formatSignedCurrency(metrics.stressValue), `${metrics.stressPct.toFixed(1)}% hit to the whole portfolio`, "is-negative")}
        </div>
    `;

    const shell = chart.canvas.parentNode;
    const shellRect = shell.getBoundingClientRect();
    const popWidth = popover.offsetWidth || 236;
    const popHeight = popover.offsetHeight || 172;
    const gap = 14;
    let left = tooltip.caretX + gap;
    let top = tooltip.caretY - popHeight / 2;

    if (left + popWidth > shellRect.width - 8) {
        left = tooltip.caretX - popWidth - gap;
    }
    left = Math.max(8, Math.min(left, shellRect.width - popWidth - 8));
    top = Math.max(8, Math.min(top, shellRect.height - popHeight - 8));

    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
    popover.classList.add("is-visible");
}

function setAllocationFocus(chart, activeIndex = -1) {
    if (!chart?.data?.datasets?.[0]) return;
    const dataset = chart.data.datasets[0];
    const baseColors = dataset.$baseColors || dataset.backgroundColor || [];
    dataset.backgroundColor = baseColors.map((color, index) =>
        activeIndex >= 0 && index !== activeIndex ? withAlpha(color, 0.80) : withAlpha(color, 0.96)
    );
}

function renderAllocation() {
    const sorted = sortedByAllocation(latestHoldings);

    const allocTable = document.getElementById("allocation-table");
    allocTable.innerHTML = "";
    if (selectedAllocationTicker) allocTable.classList.add("has-selection");
    sorted.forEach((h, i) => {
        const row = allocTable.insertRow();
        row.dataset.ticker = h.ticker;
        row.style.setProperty("--row-index", i);
        if (selectedAllocationTicker === h.ticker) row.classList.add("alloc-selected");
        row.innerHTML = `
            <td><span class="badge" style="background:${chartColor(i)}">&nbsp;</span>
                ${h.ticker}</td>
            <td>${h.shares}</td>
            <td class="text-end">${formatCurrency(h.current_value)}</td>
            <td class="text-end">${formatAllocationPct(h.allocation_pct)}</td>
        `;
        row.addEventListener("click", () => selectAllocationTicker(h.ticker));
    });

    updateSortCarets();

    const labels = sorted.map(h => h.ticker);
    const values = sorted.map(h => h.current_value);
    const colors = sorted.map((_, i) => allocColor(i));
    const glowBorders = colors.map(c => withAlpha(c, 1));

    allocationTotal = values.reduce((sum, v) => sum + toNumber(v), 0);

    if (allocationChart) {
        allocationChart.data.labels = labels;
        allocationChart.data.datasets[0].data = values;
        allocationChart.data.datasets[0].backgroundColor = colors;
        allocationChart.data.datasets[0].$baseColors = colors;
        allocationChart.data.datasets[0].hoverBorderColor = glowBorders;
        allocationChart.data.datasets[0].borderColor = allocBorderColor();
        const activeIndex = selectedAllocationTicker ? labels.indexOf(selectedAllocationTicker) : -1;
        setAllocationFocus(allocationChart, activeIndex);
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
	                    $baseColors: colors,
	                    borderColor: allocBorderColor(),
	                    borderWidth: 3,
	                    borderRadius: 8,
	                    spacing: 3.5,
	                    hoverOffset: prefersReducedMotion() ? 8 : 14,
	                    hoverBorderColor: glowBorders,
	                    hoverBorderWidth: 3,
	                }]
	            },
            options: {
	                responsive: true,
	                cutout: "68%",
	                layout: { padding: 8 },
	                animation: { animateRotate: true, animateScale: true, duration: 900,
	                             easing: "easeOutQuart" },
	                transitions: {
	                    active: { animation: { duration: prefersReducedMotion() ? 0 : 340, easing: "easeOutBack" } }
	                },
	                onHover: (event, elements) => {
	                    if (elements.length > 0) {
	                        const idx = elements[0].index;
	                        hoveredCenterLabel = allocationChart.data.labels[idx];
	                        const val = toNumber(allocationChart.data.datasets[0].data[idx]);
	                        const pct = allocationTotal > 0 ? (val / allocationTotal * 100).toFixed(1) : "0.0";
	                        hoveredCenterValue = formatCurrency(val);
	                        hoveredCenterPct = `${pct}%`;
	                        setAllocationFocus(allocationChart, idx);
	                    } else {
	                        hoveredCenterLabel = null;
	                        hoveredCenterValue = null;
	                        hoveredCenterPct = null;
	                        const selectedIndex = selectedAllocationTicker
	                            ? allocationChart.data.labels.indexOf(selectedAllocationTicker)
	                            : -1;
	                        setAllocationFocus(allocationChart, selectedIndex);
	                        if (!selectedAllocationTicker) {
	                            allocationChart.setActiveElements([]);
	                            allocationChart.tooltip.setActiveElements(
                                [],
                                { x: event?.x ?? 0, y: event?.y ?? 0 }
                            );
                        }
                    }
                    allocationChart.draw();
                },
                onClick: (_event, elements) => {
                    const ticker = elements.length > 0
                        ? allocationChart.data.labels[elements[0].index]
                        : null;
                    selectAllocationTicker(ticker);
                },
	                plugins: {
	                    legend: { display: false },
	                    tooltip: {
	                        enabled: false,
	                        external: allocationExternalTooltip,
	                    }
	                }
            },
            plugins: [segmentGlowPlugin, centerHaloPlugin, centerTotalPlugin],
        });
    }
}

function allocationCenterColor(chart) {
    const active = chart.getActiveElements()?.[0];
    let idx = Number.isInteger(active?.index) ? active.index : -1;
    if (idx < 0 && selectedAllocationTicker) {
        idx = chart.data.labels.indexOf(selectedAllocationTicker);
    }
    return idx >= 0
        ? chart.data.datasets[0].backgroundColor[idx]
        : "rgba(100, 210, 255, 0.86)";
}

// Polished live center treatment, tinted by the active/selected holding.
const centerHaloPlugin = {
    id: "centerHalo",
    afterInit(chart) {
        if (chart.config.type !== "doughnut") return;
        chart.$centerHaloStart = performance.now();
        if (prefersReducedMotion()) return;

        const tick = () => {
            if (!chart.$centerHaloFrame) return;
            if (document.visibilityState !== "hidden") chart.draw();
            chart.$centerHaloFrame = requestAnimationFrame(tick);
        };

        chart.$centerHaloFrame = requestAnimationFrame(tick);
    },
    afterDestroy(chart) {
        if (chart.$centerHaloFrame) cancelAnimationFrame(chart.$centerHaloFrame);
        chart.$centerHaloFrame = null;
    },
    afterDraw(chart) {
        if (chart.config.type !== "doughnut") return;
        const meta = chart.getDatasetMeta(0);
        const arc = meta?.data?.[0];
        if (!arc) return;

        const { ctx } = chart;
        const { x, y, innerRadius } = arc;
        const scale = uiScale();
        const reducedMotion = prefersReducedMotion();
        const elapsed = reducedMotion
            ? 0
            : ((performance.now() - (chart.$centerHaloStart || performance.now())) / 1000);
        const breath = reducedMotion ? 0.58 : (Math.sin(elapsed * 1.9) + 1) / 2;
        const radius = Math.max(34 * scale, innerRadius * 0.54);
        const outerRadius = radius + (6 + breath * 2.4) * scale;
        const innerRadiusSoft = radius - 9 * scale;
        const color = allocationCenterColor(chart);
        const isLight = currentTheme() === "light";
        const angle = -Math.PI / 2 + elapsed * 0.82;
        const sweep = Math.PI * 0.54;

        ctx.save();
        ctx.lineCap = "round";
        ctx.lineJoin = "round";

        const ambient = ctx.createRadialGradient(x, y, 0, x, y, outerRadius + 18 * scale);
        ambient.addColorStop(0, withAlpha(color, isLight ? 0.15 : 0.18));
        ambient.addColorStop(0.55, withAlpha(color, isLight ? 0.055 : 0.085));
        ambient.addColorStop(1, withAlpha(color, 0));
        ctx.fillStyle = ambient;
        ctx.beginPath();
        ctx.arc(x, y, outerRadius + 18 * scale, 0, Math.PI * 2);
        ctx.fill();

        const glass = ctx.createRadialGradient(
            x - radius * 0.3,
            y - radius * 0.42,
            radius * 0.16,
            x,
            y,
            outerRadius
        );
        glass.addColorStop(0, isLight ? "rgba(255,255,255,0.72)" : "rgba(255,255,255,0.105)");
        glass.addColorStop(0.58, isLight ? "rgba(255,255,255,0.30)" : "rgba(255,255,255,0.035)");
        glass.addColorStop(1, isLight ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.012)");
        ctx.fillStyle = glass;
        ctx.beginPath();
        ctx.arc(x, y, outerRadius, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = isLight ? "rgba(255,255,255,0.78)" : "rgba(255,255,255,0.13)";
        ctx.lineWidth = 1 * scale;
        ctx.beginPath();
        ctx.arc(x, y, outerRadius - 0.5 * scale, 0, Math.PI * 2);
        ctx.stroke();

        ctx.strokeStyle = withAlpha(color, isLight ? 0.24 : 0.30);
        ctx.lineWidth = 1.15 * scale;
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.stroke();

        ctx.shadowBlur = 14 + breath * 10;
        ctx.shadowColor = withAlpha(color, isLight ? 0.32 : 0.50);
        ctx.strokeStyle = withAlpha(color, 0.50 + breath * 0.18);
        ctx.lineWidth = 2.2 * scale;
        ctx.beginPath();
        ctx.arc(x, y, radius, angle, angle + sweep);
        ctx.stroke();

        ctx.shadowBlur = 8 + breath * 6;
        ctx.strokeStyle = withAlpha(color, 0.20 + breath * 0.16);
        ctx.lineWidth = 1.25 * scale;
        ctx.beginPath();
        ctx.arc(x, y, innerRadiusSoft, angle + Math.PI * 1.08, angle + Math.PI * 1.08 + sweep * 0.72);
        ctx.stroke();

        ctx.shadowBlur = 0;
        ctx.strokeStyle = isLight ? "rgba(255,255,255,0.70)" : "rgba(255,255,255,0.22)";
        ctx.lineWidth = 0.8 * scale;
        ctx.beginPath();
        ctx.arc(x, y, radius + 3.5 * scale, angle - 0.45, angle + 0.18);
        ctx.stroke();

        ctx.restore();
    },
};

function centerHoldingName(ticker) {
    if (!ticker) return "";
    const holding = latestHoldings.find(h => h.ticker === ticker);
    return holding?.name || ticker;
}

function shortCenterName(name, maxChars = 22) {
    if (!name) return "";
    const cleaned = String(name).replace(/\s+/g, " ").trim();
    return cleaned.length > maxChars ? `${cleaned.slice(0, maxChars - 1)}…` : cleaned;
}

function easeOutCubic(t) {
    return 1 - Math.pow(1 - Math.min(Math.max(t, 0), 1), 3);
}

function drawFittedCenterText(ctx, text, x, y, maxWidth, font) {
    ctx.font = font;
    if (ctx.measureText(text).width <= maxWidth) {
        ctx.fillText(text, x, y);
        return;
    }

    let lo = 3;
    let hi = text.length;
    while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        const candidate = `${text.slice(0, mid)}…`;
        if (ctx.measureText(candidate).width <= maxWidth) lo = mid;
        else hi = mid - 1;
    }
    ctx.fillText(`${text.slice(0, lo)}…`, x, y);
}

// Draws portfolio total (or hovered segment info) in the doughnut hole, Apple-style.
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
        const scale = uiScale();

        // Resolve what to display: hover takes priority over selection.
        const displayLabel = hoveredCenterLabel || selectedAllocationTicker;
        let displayValue = hoveredCenterValue;
        let displayPct = hoveredCenterPct;
        if (!hoveredCenterLabel && selectedAllocationTicker) {
            const sidx = chart.data.labels.indexOf(selectedAllocationTicker);
            if (sidx >= 0) {
                const sv = toNumber(chart.data.datasets[0].data[sidx]);
                const sp = allocationTotal > 0 ? (sv / allocationTotal * 100).toFixed(1) : "0.0";
                displayValue = formatCompact(sv);
                displayPct = `${sp}%`;
            }
        }

        const displayKey = displayLabel
            ? `holding:${displayLabel}:${displayValue || ""}:${displayPct || ""}`
            : `total:${allocationTotal}`;
        if (chart.$centerTextKey !== displayKey) {
            chart.$centerTextKey = displayKey;
            chart.$centerTextChangedAt = performance.now();
        }

        const reducedMotion = prefersReducedMotion();
        const elapsed = performance.now() - (chart.$centerTextChangedAt || performance.now());
        const progress = reducedMotion ? 1 : easeOutCubic(elapsed / 360);
        const textAlpha = 0.45 + progress * 0.55;
        const yShift = (1 - progress) * 5 * scale;
        const maxTextWidth = Math.max(58 * scale, (arc.innerRadius || 70) * 1.22);

        ctx.globalAlpha = textAlpha;
        if (displayLabel) {
            const holdingName = shortCenterName(centerHoldingName(displayLabel));

            ctx.fillStyle = cssVar("--text-primary") || "#f5f5f7";
            drawFittedCenterText(
                ctx,
                displayLabel,
                x,
                y - (15 * scale) + yShift,
                maxTextWidth,
                `750 ${15.5 * scale}px -apple-system, 'SF Pro Display', sans-serif`
            );

            ctx.fillStyle = cssVar("--text-secondary") || "rgba(235,235,245,0.62)";
            drawFittedCenterText(
                ctx,
                holdingName,
                x,
                y - (1 * scale) + yShift,
                maxTextWidth,
                `500 ${8.5 * scale}px -apple-system, 'SF Pro Text', sans-serif`
            );

            ctx.fillStyle = allocationCenterColor(chart);
            drawFittedCenterText(
                ctx,
                displayPct || "",
                x,
                y + (14 * scale) + yShift,
                maxTextWidth,
                `720 ${13 * scale}px -apple-system, 'SF Pro Display', sans-serif`
            );

            ctx.fillStyle = cssVar("--text-tertiary") || "rgba(235,235,245,0.42)";
            drawFittedCenterText(
                ctx,
                displayValue || "",
                x,
                y + (27 * scale) + yShift,
                maxTextWidth,
                `500 ${8.2 * scale}px -apple-system, 'SF Pro Text', sans-serif`
            );
        } else {
            // Default: compact "TOTAL" label + compact value that fits the hole
            ctx.fillStyle = cssVar("--text-tertiary") || "rgba(235,235,245,0.42)";
            ctx.font = `600 ${9.5 * scale}px -apple-system, 'SF Pro Text', sans-serif`;
            ctx.fillText("TOTAL", x, y - (15 * scale) + yShift);

            ctx.fillStyle = cssVar("--text-primary") || "#f5f5f7";
            ctx.font = `700 ${20 * scale}px -apple-system, 'SF Pro Display', sans-serif`;
            ctx.fillText(formatCompact(allocationTotal), x, y + (5 * scale) + yShift);
        }
        ctx.restore();
    },
};

// Draws a colored glow aura around the active (hovered) doughnut segment.
// Double-draw trick: outer diffuse pass then a tighter inner pass for depth.
const segmentGlowPlugin = {
    id: "segmentGlow",
    beforeDatasetsDraw(chart) {
        if (chart.config.type !== "doughnut") return;
        const active = chart.getActiveElements();
        if (!active.length) return;
        const { ctx } = chart;
        const { datasetIndex, index } = active[0];
        const meta = chart.getDatasetMeta(datasetIndex);
        const arc = meta.data[index];
        const raw = chart.data.datasets[datasetIndex].backgroundColor[index];
        const glow = raw.replace(/[\d.]+\)$/, "0.80)");
        ctx.save();
        ctx.shadowBlur = 36;
        ctx.shadowColor = glow;
        arc.draw(ctx);
        ctx.shadowBlur = 16;
        ctx.shadowColor = glow;
        arc.draw(ctx);
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
        const history = data.history || [];

        // Decide if the user has meaningful portfolio data
        const lastEntry = history[history.length - 1];
        const hasUserData = history.length >= 2 && (lastEntry?.total_value ?? 0) > 0;
        const lastDate = lastEntry ? new Date(lastEntry.date + "T12:00:00") : null;
        const hoursOld = lastDate ? (Date.now() - lastDate.getTime()) / 3_600_000 : Infinity;
        const isStale = hoursOld > 24;

        if (!hasUserData) {
            updatePerfCallout("nodata");
            await loadMarketReferenceChart();
        } else if (isStale) {
            updatePerfCallout("stale", Math.floor(hoursOld / 24));
            renderPnlChart(history);
        } else {
            hidePerfCallout();
            renderPnlChart(history);
        }

        renderRealizedTable(data.trades || []);
    } catch (err) {
        console.warn("Unable to load P&L:", err);
    }
}

function updatePerfCallout(type, daysDiff = 0) {
    const el = document.getElementById("perf-stale-callout");
    if (!el) return;
    el.style.display = "";
    const icon  = el.querySelector(".perf-callout-icon");
    const title = el.querySelector(".perf-callout-title");
    const body  = el.querySelector(".perf-callout-body");
    if (type === "nodata") {
        if (icon)  icon.className = "bi bi-bar-chart-line perf-callout-icon";
        if (title) title.textContent = "No performance history yet";
        if (body)  body.textContent = "Set your share counts to track portfolio return over time. Showing S&P 500 as reference.";
    } else {
        if (icon)  icon.className = "bi bi-clock-history perf-callout-icon";
        if (title) title.textContent = `Last updated ${daysDiff} day${daysDiff !== 1 ? "s" : ""} ago`;
        if (body)  body.textContent = "Visit the dashboard daily to keep your performance history current.";
    }
}

function hidePerfCallout() {
    const el = document.getElementById("perf-stale-callout");
    if (el) el.style.display = "none";
}

async function loadMarketReferenceChart() {
    try {
        const params = new URLSearchParams({ tickers: "SPY", period: "1mo" });
        const res = await fetch(`/api/stocks/history/batch?${params}`);
        if (!res.ok) return;
        const data = await res.json();
        const hist = (data.data?.SPY || []).filter(h => h.close > 0);
        if (hist.length < 2) return;
        renderPnlChartMarketRef(hist);
    } catch (e) { /* silent */ }
}

function renderPnlChartMarketRef(history) {
    const canvas = document.getElementById("pnl-chart");
    if (!canvas) return;
    if (pnlChart) { pnlChart.destroy(); pnlChart = null; }

    const start  = toNumber(history[0].close);
    const labels = history.map(h => h.date);
    const values = history.map(h => ((toNumber(h.close) - start) / start) * 100);
    const isUp   = values[values.length - 1] >= 0;
    const line   = isUp ? "#3fb950" : "#f85149";
    const theme  = chartTheme();
    const scale  = uiScale();

    const ctx = canvas.getContext("2d");
    pnlChart = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "S&P 500",
                data: values,
                borderColor: line,
                borderWidth: 1.5,
                borderDash: [5, 4],
                backgroundColor: "transparent",
                fill: false,
                tension: 0.35,
                pointRadius: 0,
                pointHoverRadius: 3,
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
                    ...tooltipOptions(),
                    callbacks: {
                        label: (item) => `S&P 500 (30d): ${item.raw >= 0 ? "+" : ""}${item.raw.toFixed(2)}%`,
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: theme.tick, maxRotation: 0, autoSkip: true,
                             maxTicksLimit: 6, font: { size: 10 * scale } },
                },
                y: {
                    grid: { color: theme.grid },
                    ticks: { color: theme.tick, font: { size: 10 * scale },
                             callback: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%` }
                }
            }
        }
    });
}

function renderPnlChart(history) {
    const canvas = document.getElementById("pnl-chart");
    if (!canvas) return;

    const labels = history.map(h => h.date);
    const values = history.map(h => toNumber(h.total_return));
    const up = values.length < 2 || values[values.length - 1] >= values[0];
    const line = up ? "#30d158" : "#ff453a";
    const theme = chartTheme();
    const scale = uiScale();

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
                    ...tooltipOptions(),
                    callbacks: {
                        label: (item) => `Total return: ${formatSignedCurrency(item.raw)}`,
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: theme.tick, maxRotation: 0, autoSkip: true,
                             maxTicksLimit: 6, font: { size: 10 * scale } },
                },
                y: {
                    grid: { color: theme.grid },
                    ticks: { color: theme.tick, font: { size: 10 * scale },
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
        row.style.setProperty("--row-index", i);
        const up = h.day_change_pct >= 0;
        const exp = cachedExplanations[h.ticker];
        const badgeHtml = exp
            ? `<div class="move-badge ${exp.attribution_type}" title="${exp.confidence} confidence">${ATTRIBUTION_SHORT[exp.attribution_type] || "?"}</div>`
            : ``;

        const rec = cachedRecommendations[h.ticker];

        row.innerHTML = `
            <td class="fw-bold holding-ticker-cell">
                <span class="holding-ticker-wrap">
                    <span class="ticker-dot" style="background:${chartColor(i)}"></span>
                    <span class="holding-ticker-symbol">${h.ticker}</span>
                    <i class="bi bi-chevron-right row-chevron"></i>
                </span>
            </td>
            <td class="d-none d-md-table-cell text-secondary small holding-name-cell">${h.name.substring(0, 34)}</td>
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
            <td class="text-end d-none d-sm-table-cell" id="target-cell-${h.ticker}">${renderTargetCell(rec)}</td>
            <td class="text-center d-none d-lg-table-cell" id="rec-cell-${h.ticker}">${renderAnalystRecCell(rec)}</td>
            <td class="text-center d-none d-xl-table-cell trend-cell"></td>
        `;
        row.addEventListener("click", () => toggleSummaryRow(row));
        const canvas = document.createElement("canvas");
        canvas.className = "trend-sparkline";
        canvas.width = 150;
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

function _updateHoldingsCostCallout(show) {
    const card = document.getElementById("holdings-card");
    if (!card) return;
    const cardBody = card.querySelector(".card-body");
    if (!cardBody) return;

    let callout = document.getElementById("holdings-cost-callout");
    if (!show) {
        if (callout) callout.style.display = "none";
        return;
    }
    if (!callout) {
        callout = document.createElement("div");
        callout.id = "holdings-cost-callout";
        callout.className = "perf-callout";
        callout.style.margin = "0.75rem 0.75rem 0";
        callout.innerHTML = `
            <i class="bi bi-pencil-square perf-callout-icon"></i>
            <div class="perf-callout-text">
                <div class="perf-callout-title">Cost basis missing</div>
                <div class="perf-callout-body">Enter your average purchase price to track total return. Showing today's change as an estimate.</div>
            </div>
            <button class="btn perf-callout-btn" data-bs-toggle="modal"
                    data-bs-target="#portfolioModal" onclick="loadManageHoldings()">
                Update holdings
            </button>`;
        cardBody.insertBefore(callout, cardBody.firstChild);
    }
    callout.style.display = "";
}

function animateSummaryBody(body, opening) {
    if (opening) {
        // Measure natural height without constraint, then animate from 0
        body.style.maxHeight = "none";
        const targetHeight = body.scrollHeight;
        body.style.maxHeight = "0px";
        body.offsetHeight; // force reflow so browser sees 0 before transition starts
        body.classList.add("open");
        body.style.maxHeight = targetHeight + "px";
        // After transition, remove constraint so AI content updates don't clip
        const cleanup = (e) => {
            if (e.propertyName !== "max-height") return;
            body.removeEventListener("transitionend", cleanup);
            if (body.classList.contains("open")) body.style.maxHeight = "none";
        };
        body.addEventListener("transitionend", cleanup);
    } else {
        // Pin current rendered height, then animate to 0
        body.style.maxHeight = body.scrollHeight + "px";
        body.offsetHeight; // force reflow
        body.style.maxHeight = "0px";
        body.classList.remove("open");
    }
}

function toggleSummaryRow(mainRow) {
    const expandRow = mainRow.nextElementSibling;
    if (!expandRow || !expandRow.classList.contains("summary-expand-row")) return;
    const body = expandRow.querySelector(".summary-body");
    const isOpen = body.classList.contains("open");
    animateSummaryBody(body, !isOpen);
    mainRow.classList.toggle("summary-open", !isOpen);
    if (!isOpen) mainRow.classList.remove("has-intel-ready");
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
            <div class="intel-label"><i class="bi bi-layers"></i> What It Covers</div>
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

function renderMoveExplainerFallback(section) {
    section.innerHTML = `
        <div class="intel-move">
            <div class="intel-label">
                <i class="bi bi-lightning-charge-fill" style="color:var(--accent-yellow)"></i>
                Why It Moved
            </div>
            <p class="move-explanation-text" style="color:var(--text-tertiary);font-size:.75rem;margin-top:.2rem">
                <i class="bi bi-wifi-off" style="opacity:.5;margin-right:.3rem"></i>
                Move analysis couldn't be loaded. Click <strong style="color:var(--text-secondary)">Holding Intel</strong> to try again.
            </p>
        </div>`;
}

function renderKeyDriversSpecRows(keyDrivers = []) {
    if (!keyDrivers.length) return "";
    const driverRanks = ["Primary", "Secondary", "Supporting", "Ancillary"];
    return `<div class="intel-label"><i class="bi bi-bullseye"></i> Key Drivers</div>
       <div class="intel-spec-rows key-drivers">
         ${keyDrivers.slice(0, 4).map((d, i) =>
           `<div class="intel-spec-row"><span>${driverRanks[i] || `Driver ${i + 1}`}</span><strong>${escapeHtml(d)}</strong></div>`
         ).join("")}
       </div>`;
}

function animateMoveHeroNumber(el, targetText) {
    const match = targetText.match(/([+-]?\d+\.?\d*)%/);
    if (!match) return;
    const target = parseFloat(match[1]);
    const prefix = target >= 0 ? "+" : "";
    const absTarget = Math.abs(target);
    const duration = 720;
    const start = performance.now();
    function tick(now) {
        const t = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(2, -10 * t);
        const current = (target < 0 ? -1 : 1) * absTarget * eased;
        el.textContent = `${prefix}${current.toFixed(2)}%`;
        if (t < 1) requestAnimationFrame(tick);
        else el.textContent = targetText;
    }
    requestAnimationFrame(tick);
}

function renderMoveExplainer(section, data, coverageData = null) {
    if (!data) { renderMoveExplainerFallback(section); return; }

    const drivers = data.drivers || [];
    const macro   = data.macro_context;
    const isPos      = (data.day_change_pct || 0) >= 0;

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
            <span class="driver-text">${escapeHtml(d.description)}</span>
        </div>`).join("");

    const macroPillsHtml = macroPills.length
        ? `<div class="macro-pills">${macroPills.map(p =>
            `<span class="macro-pill ${p.pos ? "positive" : "negative"}">${escapeHtml(p.label)}</span>`
          ).join("")}</div>`
        : "";
    const keyDriversHtml = renderKeyDriversSpecRows(coverageData?.key_drivers || []);
    const moveStatStripHtml = renderMoveStatStrip(data);

    section.innerHTML = `
        <div class="intel-move">
            <div class="intel-label">
                <i class="bi bi-lightning-charge-fill" style="color:var(--accent-yellow)"></i>
                Why It Moved
            </div>
            <div class="move-explainer-header">
                <div class="move-hero">
                    <span class="move-hero-number ${isPos ? "positive" : "negative"}">${formatPct(data.day_change_pct)}</span>
                    <span class="move-hero-sub">${formatSignedCurrency(data.day_change_dollar || 0)}/share</span>
                </div>
            </div>
            <p class="move-explanation-text">${escapeHtml(data.explanation_text || "")}</p>
            ${driversHtml ? `<div class="move-drivers">${driversHtml}</div>` : ""}
            ${macroPillsHtml}
            ${keyDriversHtml}
            ${moveStatStripHtml}
        </div>`;
    const heroEl = section.querySelector('.move-hero-number');
    if (heroEl) animateMoveHeroNumber(heroEl, heroEl.textContent);
}

// ── Holding Coverage ("What It Covers") ──────────────────────────────────────

function formatFactWeight(value, decimals = 1) {
    if (!isFiniteNumber(value)) return "";
    const numeric = Number(value);
    return `${numeric.toFixed(decimals)}%`;
}

function compactFactLabel(label = "") {
    return String(label).replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+/g, " ").trim();
}

function buildHoldingFact(data) {
    if (!data) return "";
    const aum = data.aum;
    if (isFiniteNumber(aum) && Number(aum) > 0) {
        return `AUM: $${formatCompactNumber(aum)}`;
    }
    return "";
}

function formatSignalPct(value, decimals = 1) {
    if (!isFiniteNumber(value)) return "—";
    const numeric = Number(value);
    return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(decimals)}%`;
}

function signalTone(value) {
    if (!isFiniteNumber(value) || Number(value) === 0) return "neutral";
    return Number(value) > 0 ? "positive" : "negative";
}

function firstFiniteValue(...values) {
    return values.find(isFiniteNumber);
}

function renderFundTrendChip(label, value) {
    const tone = signalTone(value);
    return `
        <span class="fund-trend-chip ${tone}">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(formatSignalPct(value))}</strong>
        </span>`;
}

function renderFundScaleSpotlight(data, priceSignal = null) {
    const aum = data?.aum;
    const hasAum = isFiniteNumber(aum) && Number(aum) > 0;
    const change30 = firstFiniteValue(priceSignal?.vs30dChangePct, priceSignal?.vs30dPct);
    const change200 = firstFiniteValue(priceSignal?.vs200dChangePct, priceSignal?.vs200dPct);
    const hasTrends = isFiniteNumber(change30) || isFiniteNumber(change200);
    if (!hasAum && !hasTrends) return "";

    return `
        <div class="fund-scale-spotlight" aria-label="Fund scale and price trend">
            <div class="fund-scale-emblem" aria-hidden="true">
                <i class="bi bi-stars"></i>
            </div>
            <div class="fund-scale-copy">
                <span class="fund-scale-label">Fund scale</span>
                <strong class="fund-scale-value">${hasAum ? escapeHtml(formatCompact(aum)) : "AUM unavailable"}</strong>
                <span class="fund-scale-detail">Assets under management</span>
            </div>
            ${hasTrends ? `
                <div class="fund-trend-stack" aria-label="Price change versus history">
                    ${renderFundTrendChip("30D", change30)}
                    ${renderFundTrendChip("200D", change200)}
                </div>` : ""}
        </div>`;
}

function formatExpenseRatio(expenseRatio) {
    if (!isFiniteNumber(expenseRatio)) return "Unavailable";
    return `${(Number(expenseRatio) * 100).toFixed(2)}%`;
}

function formatPercentMetric(value, decimals = 1) {
    if (!isFiniteNumber(value)) return "Unavailable";
    const numeric = Number(value);
    const pct = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
    return `${pct >= 0 ? "+" : ""}${pct.toFixed(decimals)}%`;
}

function formatPositiveMultiple(value) {
    if (!isFiniteNumber(value) || Number(value) <= 0) return "Unavailable";
    return `${Number(value).toFixed(1)}×`;
}

function buildEquityMarketPulseItems(data) {
    const marketCap = isFiniteNumber(data.market_cap) ? Number(data.market_cap) : null;
    const enterpriseValue = isFiniteNumber(data.enterprise_value) ? Number(data.enterprise_value) : null;
    const revenueGrowth = isFiniteNumber(data.revenue_growth) ? Number(data.revenue_growth) : null;
    const fcfYield = isFiniteNumber(data.fcf_yield) ? Number(data.fcf_yield) : null;
    const dividendYield = isFiniteNumber(data.dividend_yield) ? Number(data.dividend_yield) : null;
    const profitMargin = isFiniteNumber(data.profit_margin) ? Number(data.profit_margin) : null;

    const valuationOptions = [
        {
            label: "EV / Sales",
            value: formatPositiveMultiple(data.enterprise_to_revenue),
            detail: "Banker valuation multiple",
            usable: isFiniteNumber(data.enterprise_to_revenue) && Number(data.enterprise_to_revenue) > 0,
            tone: "cyan",
            icon: "bi-building-check",
        },
        {
            label: "Forward P/E",
            value: formatPositiveMultiple(data.forward_pe),
            detail: "Forward earnings multiple",
            usable: isFiniteNumber(data.forward_pe) && Number(data.forward_pe) > 0,
            tone: "blue",
            icon: "bi-graph-up-arrow",
        },
        {
            label: "P/E ratio",
            value: formatPositiveMultiple(data.pe_ratio),
            detail: "Trailing earnings multiple",
            usable: isFiniteNumber(data.pe_ratio) && Number(data.pe_ratio) > 0,
            tone: "blue",
            icon: "bi-graph-up-arrow",
        },
    ];
    const valuation = valuationOptions.find(item => item.usable) || valuationOptions[0];

    const qualityOptions = [
        {
            label: "FCF yield",
            value: isFiniteNumber(fcfYield) ? `${fcfYield >= 0 ? "+" : ""}${fcfYield.toFixed(1)}%` : "Unavailable",
            detail: "Cash return on market cap",
            usable: isFiniteNumber(fcfYield),
            tone: fcfYield !== null && fcfYield >= 4 ? "positive" : fcfYield !== null && fcfYield < 0 ? "negative" : "gold",
            icon: "bi-cash-coin",
        },
        {
            label: "Revenue growth",
            value: formatPercentMetric(revenueGrowth),
            detail: "Top-line growth",
            usable: isFiniteNumber(revenueGrowth),
            tone: revenueGrowth !== null && revenueGrowth >= 0.15 ? "positive" : revenueGrowth !== null && revenueGrowth < 0 ? "negative" : "gold",
            icon: "bi-speedometer2",
        },
        {
            label: "Dividend yield",
            value: formatPercentMetric(dividendYield),
            detail: "Shareholder cash yield",
            usable: isFiniteNumber(dividendYield) && Number(dividendYield) > 0,
            tone: "positive",
            icon: "bi-piggy-bank",
        },
        {
            label: "Profit margin",
            value: formatPercentMetric(profitMargin),
            detail: "Net income margin",
            usable: isFiniteNumber(profitMargin),
            tone: profitMargin !== null && profitMargin >= 0.15 ? "positive" : profitMargin !== null && profitMargin < 0 ? "negative" : "gold",
            icon: "bi-percent",
        },
    ];
    const quality = qualityOptions.find(item => item.usable) || qualityOptions[0];

    return [
        {
            icon: "bi-bank",
            label: "Market cap",
            value: marketCap !== null ? formatCompact(marketCap) : "Unavailable",
            detail: enterpriseValue !== null ? `EV ${formatCompact(enterpriseValue)}` : "Equity value",
            tone: "cyan",
        },
        {
            icon: valuation.icon,
            label: valuation.label,
            value: valuation.value,
            detail: valuation.detail,
            tone: valuation.tone,
        },
        {
            icon: quality.icon,
            label: quality.label,
            value: quality.value,
            detail: quality.detail,
            tone: quality.tone,
        },
    ];
}

function buildMarketPulseItems(data) {
    if ((data.coverage_type || "") === "equity") {
        return buildEquityMarketPulseItems(data);
    }

    const items = [];
    const expenseRatio = isFiniteNumber(data.expense_ratio)
        ? Number(data.expense_ratio)
        : (isFiniteNumber(data.expense_ratio_bps) ? Number(data.expense_ratio_bps) / 10000 : null);
    const volume = isFiniteNumber(data.volume) ? Number(data.volume) : null;
    const avgVolume = isFiniteNumber(data.average_volume) ? Number(data.average_volume) : null;
    const volumeRatio = volume !== null && avgVolume && avgVolume > 0 ? volume / avgVolume : null;

    items.push({
        icon: "bi-receipt-cutoff",
        label: "Expense ratio",
        value: formatExpenseRatio(expenseRatio),
        detail: "Annual fund fee",
        tone: "cyan",
    });

    items.push({
        icon: "bi-bar-chart-line-fill",
        label: "Market volume",
        value: volume !== null ? formatCompactNumber(volume) : "Unavailable",
        detail: volumeRatio !== null ? `${volumeRatio.toFixed(1)}x average volume` : "Avg volume unavailable",
        tone: volumeRatio !== null && volumeRatio >= 1.5 ? "gold" : "blue",
    });

    // Bid-ask spread — institutional liquidity quality signal used by Goldman/JPMorgan trading desks
    const spreadPct = isFiniteNumber(data.bid_ask_spread_pct) ? Number(data.bid_ask_spread_pct) : null;
    const spreadLabel = spreadPct === null ? "Unavailable"
        : spreadPct < 0.05 ? "Premium liquidity"
        : spreadPct < 0.15 ? "Tight spread"
        : spreadPct < 0.5  ? "Normal spread"
        : "Wide spread";
    const spreadTone = spreadPct === null ? "neutral"
        : spreadPct < 0.05 ? "positive"
        : spreadPct < 0.15 ? "cyan"
        : spreadPct < 0.5  ? "blue"
        : "negative";

    items.push({
        icon: "bi-arrows-collapse",
        label: "Bid-ask spread",
        value: spreadPct !== null ? `${spreadPct.toFixed(3)}%` : "Unavailable",
        detail: spreadLabel,
        tone: spreadTone,
    });

    return items;
}

const MOVE_ATTR_ICONS = {
    "market-driven":    "bi-globe",
    "sector-driven":    "bi-pie-chart-fill",
    "holdings-driven":  "bi-stack",
    "macro-driven":     "bi-bank",
    "company-specific": "bi-building",
    "earnings-driven":  "bi-graph-up-arrow",
    "filing-driven":    "bi-file-earmark-text",
    "mixed":            "bi-layers-fill",
    "etf-index":        "bi-bar-chart-steps",
    "unclear":          "bi-question-circle",
};
const MOVE_ATTR_TONES = {
    "market-driven":    "blue",
    "sector-driven":    "cyan",
    "holdings-driven":  "positive",
    "macro-driven":     "cyan",
    "company-specific": "gold",
    "earnings-driven":  "gold",
    "filing-driven":    "cyan",
    "mixed":            "neutral",
    "etf-index":        "positive",
    "unclear":          "neutral",
};

function buildMoveStatItems(data) {
    const items = [];

    // 1. Flow Signal — price direction + volume conviction
    const dayChange = isFiniteNumber(data.day_change_pct) ? Number(data.day_change_pct) : null;
    const volRatio  = isFiniteNumber(data.volume_vs_avg)  ? Number(data.volume_vs_avg)  : null;
    const pressureType  = dayChange === null ? "neutral" : dayChange >= 0 ? "positive" : "negative";
    const pressureLabel = dayChange === null ? "Flow Unclear" : dayChange >= 0 ? "Buyers in Control" : "Sellers in Control";
    const pressureDetail = dayChange === null
        ? "No live price move"
        : `${formatPct(dayChange)}${volRatio !== null ? ` · ${volRatio.toFixed(1)}x vol` : ""}`;

    items.push({
        icon: pressureType === "positive" ? "bi-arrow-up-right-circle-fill"
            : pressureType === "negative" ? "bi-arrow-down-right-circle-fill"
            : "bi-circle-half",
        label: "Flow Signal",
        value: pressureLabel,
        detail: pressureDetail,
        tone: pressureType,
    });

    // 2. Volume Surge — institutional conviction signal (used by every Goldman equity desk)
    const surgeTone = volRatio === null ? "neutral"
        : volRatio >= 2.5 ? "gold"
        : volRatio >= 1.5 ? "cyan"
        : "blue";
    const surgeLabel = volRatio === null ? "Unavailable"
        : volRatio >= 3   ? "Heavy Activity"
        : volRatio >= 2   ? "High Activity"
        : volRatio >= 1.5 ? "Above Average"
        : volRatio >= 0.8 ? "Steady Volume"
        : "Thin Activity";

    items.push({
        icon: "bi-activity",
        label: "Volume Signal",
        value: volRatio !== null ? `${volRatio.toFixed(1)}× avg` : "Unavailable",
        detail: surgeLabel,
        tone: surgeTone,
    });

    // 3. Move Catalyst — attribution signal used by sell-side analysts to classify moves
    const attrType = data.attribution_type || "unclear";
    items.push({
        icon: MOVE_ATTR_ICONS[attrType] || "bi-question-circle",
        label: "Move Catalyst",
        value: ATTRIBUTION_SHORT[attrType] || "Unknown",
        detail: data.confidence ? `${data.confidence} confidence` : "Assessing…",
        tone: MOVE_ATTR_TONES[attrType] || "neutral",
    });

    return items;
}

function renderMoveStatStrip(data) {
    if (!data) return "";
    const items = buildMoveStatItems(data);
    return `
        <div class="market-pulse-strip move-stat-strip" aria-label="AI move stats">
            ${items.map((item, index) => `
                <div class="market-pulse-card ${escapeHtml(item.tone)}" style="--pulse-index:${index}">
                    <i class="bi ${escapeHtml(item.icon)} pulse-icon" aria-hidden="true"></i>
                    <span class="pulse-copy">
                        <span class="pulse-label">${escapeHtml(item.label)}</span>
                        <strong>${escapeHtml(item.value)}</strong>
                        <span class="pulse-detail">${escapeHtml(item.detail)}</span>
                    </span>
                </div>`).join("")}
        </div>`;
}

function renderMarketPulseStrip(data) {
    const items = buildMarketPulseItems(data);
    return `
        <div class="market-pulse-strip" aria-label="AI market pulse">
            ${items.map((item, index) => `
                <div class="market-pulse-card ${escapeHtml(item.tone)}" style="--pulse-index:${index}">
                    <i class="bi ${escapeHtml(item.icon)} pulse-icon" aria-hidden="true"></i>
                    <span class="pulse-copy">
                        <span class="pulse-label">${escapeHtml(item.label)}</span>
                        <strong>${escapeHtml(item.value)}</strong>
                        <span class="pulse-detail">${escapeHtml(item.detail)}</span>
                    </span>
                </div>`).join("")}
        </div>`;
}

function renderHoldingCoverage(section, data) {
    if (!data) {
        section.innerHTML = `<div class="intel-coverage"><span class="intel-na">Coverage data not available</span></div>`;
        return;
    }

    const coverageClass = (data.coverage_type || "equity").replace(/[^a-z-]/g, "");
    const rating = cachedRecommendations[data.ticker] || {};
    const quality = rating.etf_quality || null;
    const priceSignal = rating.price_signal || null;

    // Sector bars (top 5)
    const sectorBarsHtml = data.sectors && data.sectors.length
        ? `<div class="intel-label"><i class="bi bi-diagram-3"></i> Sectors</div>
           <div class="sector-bars">
             ${data.sectors.slice(0, 5).map((s, i) => `
               <div class="sector-bar-row">
                 <span class="sector-bar-swatch" style="--sector-color:${chartColor(i)}"></span>
                 <div class="sector-bar-label" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</div>
                 <div class="sector-bar-track"><div class="sector-bar-fill" style="--sector-color:${chartColor(i)};width:${Math.min(s.weight, 100)}%"></div></div>
                 <div class="sector-bar-pct">${s.weight.toFixed(1)}%</div>
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
                  <div class="holding-mini-weight">
                    <div class="holding-mini-bar-track">
                      <div class="holding-mini-bar-fill" style="width:${(h.weight / maxBarWeight * 100).toFixed(0)}%"></div>
                    </div>
                    <span class="holding-mini-pct">${h.weight.toFixed(1)}%</span>
                  </div>
                </div>`).join("")}
            </div>`;
    } else if (data.coverage_type === "equity" && data.peer_tickers && data.peer_tickers.length) {
        topHoldingsHtml = `
            <div class="intel-label"><i class="bi bi-people"></i> Peer Group</div>
            <div class="peer-chips">
              ${data.peer_tickers.slice(0, 6).map(p => `<span class="peer-chip">${escapeHtml(p)}</span>`).join("")}
            </div>`;
    }

    const etfProfileHtml = quality && (data.coverage_type || "").startsWith("etf")
        ? `<div class="intel-label"><i class="bi bi-sliders"></i> ETF Profile</div>
           <div class="intel-spec-rows">
             <div class="intel-spec-row"><span>ETF quality</span><strong><span class="spec-pill">${escapeHtml(quality.qualityLabel || "Insufficient Data")}</span></strong></div>
             <div class="intel-spec-row"><span>Cost</span><strong><span class="spec-pill">${escapeHtml(quality.costLabel || "Unknown")}</span></strong></div>
             <div class="intel-spec-row"><span>Liquidity</span><strong>${escapeHtml(quality.liquidityLabel || "Unknown")}</strong></div>
             <div class="intel-spec-row"><span>Diversification</span><strong>${escapeHtml(quality.diversificationLabel || "Unknown")}</strong></div>
             <div class="intel-spec-row"><span>Category risk</span><strong><span class="spec-pill risk">${escapeHtml(quality.categoryRiskLabel || "Unknown")}</span></strong></div>
           </div>`
        : "";

    // Metadata footer
    const marketPulseHtml = renderMarketPulseStrip(data);
    const fundScaleHtml = renderFundScaleSpotlight(data, priceSignal);
    const fact = buildHoldingFact(data);
    const missingPulse = data.load_status?.market_pulse?.missing || [];
    const pulseStatusHtml = !marketPulseLoaded(data) && intelligenceExhaustedTickers.has(data.ticker)
        ? `<span class="fact-tag intel-refresh-note"><i class="bi bi-arrow-repeat"></i>Some live metrics are still unavailable. Tap Holding Intel again; Claude can be selective and may need one more look for the full picture.</span>`
        : missingPulse.length && intelligenceRetryingTickers.has(data.ticker)
            ? `<span class="fact-tag intel-refresh-note"><i class="bi bi-arrow-repeat"></i>Refreshing ${escapeHtml(missingPulse.join(", "))}</span>`
            : "";
    const factTag = fact && !fundScaleHtml
        ? `<span class="fact-tag"><i class="bi bi-stars"></i>${escapeHtml(fact)}</span>` : "";

    section.innerHTML = `
        <div class="intel-coverage">
            <div class="intel-label"><i class="bi bi-layers"></i> What It Covers</div>
            <span class="coverage-type-badge ${escapeHtml(coverageClass)}">${escapeHtml(data.coverage_label || data.coverage_type)}</span>
            ${data.theme ? `<div class="intel-theme">${escapeHtml(data.theme)}</div>` : ""}
            <div class="intel-strategy">${escapeHtml(data.strategy || "")}</div>
            ${sectorBarsHtml}
            ${countryChipsHtml}
            ${topHoldingsHtml}
            ${etfProfileHtml}
            ${fundScaleHtml}
            ${marketPulseHtml}
            <div class="intel-meta-row">${factTag}${pulseStatusHtml}</div>
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
                <div class="intel-loading-overlay" aria-hidden="true">
                    <div class="intel-loading-content">
                        <img src="/static/img/brand/folio-orbit-icon.svg" alt="" class="intel-loading-orbit">
                        <div class="intel-loading-title">Sliding into Claude's DMs for your portfolio tea...</div>
                        <div class="intel-loading-sub">She read it. Now typing. Always delivers — just takes her 30–60s.</div>
                    </div>
                </div>
            </div></div>`;
            expandRow.appendChild(td);
            mainRow.after(expandRow);
        }

        const intelGrid = expandRow.querySelector(".intel-grid");
        if (intelGrid) {
            intelGrid.classList.toggle("is-intel-loading", !!(intelligenceLoading && !intelligenceLoaded));
        }

        const body          = expandRow.querySelector(".summary-body");
        const coverageSection = expandRow.querySelector(".intel-coverage-section");
        const moveSection   = expandRow.querySelector(".intel-move-section");

        if (!coverageSection || !moveSection) return;

        const tickerRetrying = intelligenceRetryingTickers.has(ticker);
        const hasCoverage = !!cachedIntelligence[ticker];
        const isCoveragePending = tickerRetrying || (intelligenceLoading && !hasCoverage);

        if (isCoveragePending) {
            renderCoverageShimmer(coverageSection);
            if (cachedExplanations[ticker]) {
                renderMoveExplainer(moveSection, cachedExplanations[ticker], cachedIntelligence[ticker]);
            } else {
                renderMoveExplainerShimmer(moveSection);
            }
        } else if (intelligenceLoaded) {
            renderHoldingCoverage(coverageSection, cachedIntelligence[ticker]);
            renderMoveExplainer(moveSection, cachedExplanations[ticker], cachedIntelligence[ticker]);
        } else if (hasCoverage) {
            renderHoldingCoverage(coverageSection, cachedIntelligence[ticker]);
            renderMoveExplainer(moveSection, cachedExplanations[ticker], cachedIntelligence[ticker]);
        }

        if (holdingIntelSettled(ticker)) {
            mainRow.classList.add("has-intel-ready");
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
        ctx.strokeStyle = cssVar("--text-tertiary") || "rgba(255,255,255,0.22)";
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
    const lineColor = isPositive
        ? (cssVar("--accent-green") || "#30d158")
        : (cssVar("--accent-red") || "#ff453a");

    const points = closes.map((close, index) => ({
        x: padding + (index * (width - padding * 2)) / (closes.length - 1),
        y: height - padding - ((close - min) / range) * (height - padding * 2),
    }));

    // Fill gradient beneath the line
    const fillGrad = ctx.createLinearGradient(0, 0, 0, height);
    fillGrad.addColorStop(0, isPositive ? "rgba(48,209,88,0.28)" : "rgba(255,69,58,0.28)");
    fillGrad.addColorStop(1, "rgba(0,0,0,0)");

    ctx.beginPath();
    points.forEach(({ x, y }, i) => i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y));
    ctx.lineTo(points[points.length - 1].x, height);
    ctx.lineTo(points[0].x, height);
    ctx.closePath();
    ctx.fillStyle = fillGrad;
    ctx.fill();

    // Line stroke
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.8;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    points.forEach(({ x, y }, i) => i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y));
    ctx.stroke();

    // Terminal dot at end of sparkline
    const last = points[points.length - 1];
    ctx.beginPath();
    ctx.arc(last.x, last.y, 2.2, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();
}


// ── Ratings ────────────────────────────────────────────────────────────────

const REC_ICONS = {
    "buy":       "bi-arrow-up-circle-fill",
    "hold":      "bi-dash-circle-fill",
    "sell":      "bi-arrow-down-circle-fill",
    "unavailable": "bi-question-circle",
    "etf-quality": "bi-layers-fill",
};

function renderTargetKind(kind, icon, label) {
    return `<div class="target-kind target-kind-${escapeHtml(kind)}">
                <i class="bi ${escapeHtml(icon)}"></i>
                <span>${escapeHtml(label)}</span>
            </div>`;
}

function renderTargetCell(rec) {
    if (!rec) {
        return `<div class="shimmer-line" style="width:56px;height:12px;border-radius:4px;margin:0 auto .25rem"></div>
                <div class="shimmer-line" style="width:38px;height:9px;border-radius:4px;margin:0 auto"></div>`;
    }
    // ETFs do not have useful analyst price targets. Show their price zone instead.
    if (rec.rating_type === "etf_quality" && rec.price_signal) {
        const signal = rec.price_signal;
        const label = signal.priceZoneLabel || "Unavailable";
        if (label !== "Unavailable" && signal.percentile != null) {
            const zoneClass = label.toLowerCase();
            const trend30 = firstFiniteValue(signal.vs30dChangePct, signal.vs30dPct);
            const trend200 = firstFiniteValue(signal.vs200dChangePct, signal.vs200dPct);
            const trendText = trend30 == null && trend200 == null
                ? escapeHtml(signal.basis || "Price zone")
                : `30D ${formatSignalPct(trend30)} · 200D ${formatSignalPct(trend200)}`;
            return `<div class="target-price-value price-zone-${escapeHtml(zoneClass)}">${escapeHtml(label)} · ${Number(signal.percentile).toFixed(0)}%</div>
                    <div class="target-upside" style="color:var(--text-tertiary)">${escapeHtml(trendText)}</div>
                    ${renderTargetKind("etf", "bi-activity", "ETF signal")}`;
        }
    }
    // Stocks with analyst consensus price target
    if (rec.target_price) {
        const upside = rec.target_upside_pct;
        const sign = upside >= 0 ? "+" : "";
        const color = upside >= 0 ? "var(--accent-green)" : "var(--accent-red)";
        return `<div class="target-price-value">${formatCurrency(rec.target_price)}</div>
                <div class="target-upside" style="color:${color}">${sign}${upside.toFixed(1)}%</div>
                ${renderTargetKind("stock", "bi-bullseye", "Stock target")}`;
    }
    // ETFs and stocks without analyst coverage — show Free Cash Flow Yield
    if (rec.fcf_yield != null) {
        const color = rec.fcf_yield >= 4
            ? "var(--accent-green)"
            : rec.fcf_yield >= 0
                ? "var(--text-secondary)"
                : "var(--accent-red)";
        const sign = rec.fcf_yield >= 0 ? "+" : "";
        return `<div class="target-price-value" style="color:${color}">${sign}${rec.fcf_yield.toFixed(1)}%</div>
                <div class="target-upside" style="color:var(--text-tertiary)">FCF Yield</div>
                ${renderTargetKind("fallback", "bi-cash-coin", "Fallback")}`;
    }
    return `<span style="color:var(--text-tertiary);font-size:.72rem">—</span>`;
}

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
            const targetCell = document.getElementById(`target-cell-${ticker}`);
            if (targetCell) targetCell.innerHTML = renderTargetCell(rec);
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

async function loadAiCostStats() {
    const valueEl = document.getElementById("brand-cost-value");
    const metaEl = document.getElementById("brand-cost-meta");
    const triggerLabel = document.getElementById("brand-cost-trigger-label");
    if (!valueEl || !metaEl) return;

    try {
        const res = await fetch("/api/ai/cache/stats");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const cost = formatUsdTiny(data.estimated_cost_usd);
        valueEl.textContent = cost;
        metaEl.textContent = `${toNumber(data.estimated_total_tokens).toLocaleString()} est. tokens across ${data.cached_summaries} cached summaries`;
        if (triggerLabel) triggerLabel.textContent = cost;
    } catch (err) {
        valueEl.textContent = "Unavailable";
        metaEl.textContent = "Could not load AI cost stats";
    }
}

function initBrandCostCallout() {
    const trigger = document.getElementById("brand-cost-trigger");
    const callout = document.getElementById("brand-cost-callout");
    if (!trigger || !callout) return;

    function openCallout() {
        callout.classList.add("is-visible");
        callout.setAttribute("aria-hidden", "false");
        trigger.setAttribute("aria-expanded", "true");
    }

    function closeCallout() {
        callout.classList.remove("is-visible");
        callout.setAttribute("aria-hidden", "true");
        trigger.setAttribute("aria-expanded", "false");
    }

    trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        callout.classList.contains("is-visible") ? closeCallout() : openCallout();
    });

    document.addEventListener("click", (e) => {
        if (!callout.contains(e.target) && !trigger.contains(e.target)) {
            closeCallout();
        }
    });

    loadAiCostStats();
}

document.addEventListener("DOMContentLoaded", () => { initDashboard(); HoldingsBg.init(); });

function refreshData() {
    const refreshButton = document.querySelector(".btn-refresh-data");
    refreshButton?.classList.remove("is-refreshing");
    if (refreshButton && !prefersReducedMotion()) {
        void refreshButton.offsetWidth;
        refreshButton.classList.add("is-refreshing");
    }

    Promise.allSettled([
        loadPortfolioValue(),
        loadPnl(),
        updateMarketStatus(),
    ]).finally(() => {
        window.setTimeout(() => refreshButton?.classList.remove("is-refreshing"), 260);
    });
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
            icon.style.color = data.is_open ? "var(--accent-green)" : "";
            icon.classList.toggle("market-open", !!data.is_open);
        }
    } catch(e) {}
}

const HUD_TOTAL = 300;
let _hudCountdown = HUD_TOTAL;

function updateHudPopoverCountdown() {
    const popCountdown = document.getElementById("hud-pop-countdown");
    const progress = document.getElementById("hud-pop-progress");
    if (!popCountdown || !progress) return;
    const soon = _hudCountdown <= 30;
    const mins = Math.floor(_hudCountdown / 60);
    const secs = _hudCountdown % 60;
    popCountdown.textContent = mins > 0
        ? `${mins}m ${secs}s`
        : `${secs} second${secs !== 1 ? "s" : ""}`;
    const pct = (_hudCountdown / HUD_TOTAL) * 100;
    progress.style.width = `${pct}%`;
    progress.classList.toggle("is-soon", soon);
}

function startCountdown() {
    _hudCountdown = HUD_TOTAL;
    const interval = setInterval(() => {
        _hudCountdown--;
        const el = document.getElementById("countdown");
        if (el) {
            const soon = _hudCountdown <= 30;
            el.textContent = soon ? `${_hudCountdown}s` : `↻ ${_hudCountdown}s`;
            el.classList.toggle("is-soon", soon);
        }
        updateHudPopoverCountdown();
        if (_hudCountdown <= 0) {
            clearInterval(interval);
            loadPortfolioValue().then(() => {
                loadPnl();
                updateMarketStatus();
                startCountdown();
            });
        }
    }, 1000);
}

function initHudPopover() {
    const pill = document.getElementById("hud-status-pill");
    const popover = document.getElementById("hud-popover");
    if (!pill || !popover) return;

    let clockInterval = null;

    function updatePopoverContent() {
        const updatedEl = document.getElementById("last-updated");
        const popUpdated = document.getElementById("hud-pop-updated");
        const popClock = document.getElementById("hud-pop-clock");
        if (popUpdated && updatedEl) popUpdated.textContent = updatedEl.textContent || "—";
        if (popClock) popClock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        updateHudPopoverCountdown();
    }

    function positionPopover() {
        const pillRect = pill.getBoundingClientRect();
        const popW = popover.offsetWidth || 224;
        let left = pillRect.left + pillRect.width / 2 - popW / 2;
        left = Math.max(8, Math.min(left, window.innerWidth - popW - 8));
        const top = pillRect.bottom + 10;
        popover.style.left = `${left}px`;
        popover.style.top = `${top}px`;
    }

    function showPopover() {
        updatePopoverContent();
        positionPopover();
        popover.classList.add("is-visible");
        popover.setAttribute("aria-hidden", "false");
        pill.setAttribute("aria-expanded", "true");
        clockInterval = setInterval(() => {
            const popClock = document.getElementById("hud-pop-clock");
            if (popClock) popClock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        }, 1000);
    }

    function hidePopover() {
        popover.classList.remove("is-visible");
        popover.setAttribute("aria-hidden", "true");
        pill.setAttribute("aria-expanded", "false");
        if (clockInterval) { clearInterval(clockInterval); clockInterval = null; }
    }

    pill.addEventListener("click", (e) => {
        e.stopPropagation();
        popover.classList.contains("is-visible") ? hidePopover() : showPopover();
    });

    document.addEventListener("click", (e) => {
        if (!popover.contains(e.target) && !pill.contains(e.target)) {
            hidePopover();
        }
    });
}

document.addEventListener("keydown", (e) => {
    const tag = e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) return;

    if (e.key === "Escape") { hideKeyboardHelp(); return; }
    if (e.key === "?")      { showKeyboardHelp(); return; }
    if (e.key === "r" || e.key === "R") { refreshData(); return; }
    if (e.key === "t" || e.key === "T") {
        applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
        return;
    }
    if (e.key === "s" || e.key === "S") {
        applyTextSize(currentTextSize() === "comfortable" ? "standard" : "comfortable", true);
        return;
    }
    if (e.key === "m" || e.key === "M") {
        const modal = document.getElementById("portfolioModal");
        if (modal) { loadManageHoldings(); new bootstrap.Modal(modal).show(); }
        return;
    }
    if (e.key === "i" || e.key === "I") { loadHoldingIntelligence(); return; }
});

async function initDashboard() {
    initThemeToggle();
    initTextSizeToggle();
    initBrandCostCallout();
    initPerformanceTabs();
    await loadPortfolioValue();
    await loadPnl();
    await updateMarketStatus();
    // Fire without blocking — prices and P&L are already visible
    loadAnalystRecommendations();
    loadWorldMarkets();
    startCountdown();
    initHudPopover();
    initTips();
    initKeyboardHelp();
}

// ── World Markets ─────────────────────────────────────────────────────────────

function _marketPrice(price) {
    if (!price || price === 0) return "—";
    // Omit decimals for large indices (Nikkei, Hang Seng, etc.)
    const opts = price > 999
        ? { minimumFractionDigits: 0, maximumFractionDigits: 0 }
        : { minimumFractionDigits: 2, maximumFractionDigits: 2 };
    return new Intl.NumberFormat("en-US", opts).format(price);
}

const _REGION_ORDER = ["US", "Europe", "Asia", "Pacific"];

async function loadWorldMarkets() {
    try {
        const res = await fetch("/api/stocks/world-markets");
        if (!res.ok) return;
        const { markets } = await res.json();
        const strip = document.getElementById("world-markets-strip");
        if (!strip) return;
        strip.innerHTML = "";

        // Group by region, preserve defined order
        const byRegion = {};
        markets.forEach(m => {
            if (!byRegion[m.region]) byRegion[m.region] = [];
            byRegion[m.region].push(m);
        });

        _REGION_ORDER.forEach((region, regionIdx) => {
            const group = byRegion[region] || [];
            if (!group.length) return;

            if (regionIdx > 0) {
                const div = document.createElement("div");
                div.className = "market-region-divider";
                strip.appendChild(div);
            }

            group.forEach((m, marketIdx) => {
                const up   = m.day_change_pct >= 0;
                const cls  = up ? "text-success" : "text-danger";
                const icon = up ? "bi-caret-up-fill" : "bi-caret-down-fill";
                const sign = up ? "+" : "";

                const tile = document.createElement("div");
                tile.className = `market-tile ${up ? "is-positive" : "is-negative"}`;
                tile.style.setProperty("--tile-index", regionIdx * 3 + marketIdx);
                tile.innerHTML = `
                    <div class="market-tile-top">
                        <span class="market-tile-flag">${m.flag}</span>
                        <span class="market-tile-region">${m.region}</span>
                    </div>
                    <div class="market-tile-name">${escapeHtml(m.name)}</div>
                    <div class="market-tile-price">${_marketPrice(m.price)}</div>
                    <div class="market-tile-change ${cls}">
                        <i class="bi ${icon}"></i>
                        ${sign}${m.day_change_pct.toFixed(2)}%
                    </div>
                `;
                strip.appendChild(tile);
            });
        });
    } catch (err) {
        console.warn("World markets unavailable:", err);
        const strip = document.getElementById("world-markets-strip");
        if (strip) strip.innerHTML = `<span style="padding:1rem;color:var(--text-tertiary);font-size:.8rem">Market data unavailable</span>`;
    }
}

// ── Holding Intelligence ────────────────────────────────────────────────────

function fallbackIntelligenceForTicker(ticker) {
    const holding = latestHoldings.find(h => h.ticker === ticker) || {};
    return {
        ticker,
        coverage_type: "equity",
        coverage_label: "Holding",
        strategy: holding.name
            ? `${holding.name} market data is temporarily unavailable. Tap Holding Intel again; Claude can be selective and may need one more look for the full picture.`
            : "Market data is temporarily unavailable. Tap Holding Intel again; Claude can be selective and may need one more look for the full picture.",
        asset_class: "equities",
        theme: null,
        sectors: [],
        countries: [],
        top_holdings: [],
        benchmark_tickers: ["SPY"],
        benchmark_labels: { SPY: "S&P 500" },
        peer_tickers: [],
        key_drivers: [],
        concentration_level: "medium",
        concentration_label: "",
        expense_ratio: null,
        expense_ratio_bps: null,
        day_change_pct: holding.day_change_pct ?? null,
        volume: null,
        average_volume: null,
        bid: null,
        ask: null,
        bid_ask_spread_pct: null,
        market_cap: null,
        enterprise_value: null,
        total_revenue: null,
        ebitda: null,
        free_cashflow: null,
        fcf_yield: null,
        pe_ratio: null,
        forward_pe: null,
        price_to_sales: null,
        enterprise_to_revenue: null,
        enterprise_to_ebitda: null,
        revenue_growth: null,
        gross_margin: null,
        operating_margin: null,
        profit_margin: null,
        dividend_yield: null,
        aum: null,
        data_quality: "unavailable",
        data_sources: [],
        load_status: {
            coverage: false,
            market_pulse: { loaded: false, missing: ["market_data"] },
        },
    };
}

async function fetchSingleIntelligenceWithRetry(ticker) {
    const currentAttempt = (intelligenceRetryState[ticker] || 0) + 1;
    intelligenceRetryState[ticker] = currentAttempt;
    intelligenceRetryingTickers.add(ticker);
    renderHoldings();

    try {
        await delay(INTELLIGENCE_RETRY_BASE_DELAY_MS * currentAttempt);
        const params = new URLSearchParams({ retry: String(Date.now()) });
        const res = await fetch(`/api/ai/intelligence/${encodeURIComponent(ticker)}?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const intel = await res.json();
        cachedIntelligence[ticker] = intel;
        if (marketPulseLoaded(intel)) {
            intelligenceExhaustedTickers.delete(ticker);
        } else if (currentAttempt >= INTELLIGENCE_MAX_RETRIES) {
            intelligenceExhaustedTickers.add(ticker);
        }
    } catch (err) {
        console.warn(`Intelligence retry failed for ${ticker}:`, err);
        if (currentAttempt >= INTELLIGENCE_MAX_RETRIES) {
            if (!cachedIntelligence[ticker]) cachedIntelligence[ticker] = fallbackIntelligenceForTicker(ticker);
            intelligenceExhaustedTickers.add(ticker);
        }
    } finally {
        intelligenceRetryingTickers.delete(ticker);
        updateIntelligenceLoadedState();
        renderHoldings();
    }
}

async function verifyAndRefreshIncompleteIntelligence() {
    let pending = incompleteIntelligenceTickers()
        .filter(ticker => (intelligenceRetryState[ticker] || 0) < INTELLIGENCE_MAX_RETRIES);

    while (pending.length) {
        setAgentLine(`Refreshing ${pending.length} missing metric${pending.length === 1 ? "" : "s"}`);
        await Promise.allSettled(pending.map(fetchSingleIntelligenceWithRetry));
        pending = incompleteIntelligenceTickers()
            .filter(ticker => (intelligenceRetryState[ticker] || 0) < INTELLIGENCE_MAX_RETRIES);
    }

    incompleteIntelligenceTickers().forEach(ticker => {
        if (!cachedIntelligence[ticker]) cachedIntelligence[ticker] = fallbackIntelligenceForTicker(ticker);
        intelligenceExhaustedTickers.add(ticker);
    });
    return updateIntelligenceLoadedState();
}

async function loadHoldingIntelligence() {
    const tbody = document.getElementById("holdings-table");
    const btn = document.querySelector('[onclick="loadHoldingIntelligence()"]');

    const hasMoveExplanations = Object.keys(cachedExplanations).length > 0;
    if (intelligenceLoaded && hasMoveExplanations && intelligenceRetryingTickers.size === 0) {
        // Toggle expand rows open/closed on repeated click
        const allBodies = tbody.querySelectorAll(".summary-body");
        const anyOpen = Array.from(allBodies).some(b => b.classList.contains("open"));
        allBodies.forEach(b => animateSummaryBody(b, !anyOpen));
        tbody.querySelectorAll("tr[data-ticker]").forEach(r => {
            r.classList.toggle("summary-open", !anyOpen);
            if (!anyOpen) r.classList.remove("has-intel-ready");
        });
        return;
    }

    intelligenceLoading = true;
    intelligenceRetryState = {};
    intelligenceRetryingTickers = new Set();
    intelligenceExhaustedTickers = new Set();
    setAiChecking(true, "Reading positions");
    injectSummaryRows(tbody);
    if (btn) {
        btn.innerHTML = INTEL_BUTTON_LOADING_HTML;
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
            (intelData.incomplete_tickers || []).forEach(ticker => {
                if (!intelligenceRetryState[ticker]) intelligenceRetryState[ticker] = 0;
            });
        }

        if (moveRes.ok) {
            const moveData = await moveRes.json();
            Object.entries(moveData.explanations || {}).forEach(([ticker, exp]) => {
                cachedExplanations[ticker] = exp;
            });
        }

        await verifyAndRefreshIncompleteIntelligence();
        intelligenceLoaded = updateIntelligenceLoadedState();
        intelligenceLoading = false;
        setAiChecking(false, intelligenceLoaded ? "Insights ready" : "Watching holdings", intelligenceLoaded);

        // Render all expanded rows
        Array.from(tbody.querySelectorAll("tr[data-ticker]")).forEach(mainRow => {
            const ticker = mainRow.dataset.ticker;
            const expandRow = mainRow.nextElementSibling;
            if (!expandRow || !expandRow.classList.contains("summary-expand-row")) return;
            const coverageSection = expandRow.querySelector(".intel-coverage-section");
            const moveSection     = expandRow.querySelector(".intel-move-section");
            if (coverageSection) renderHoldingCoverage(coverageSection, cachedIntelligence[ticker]);
            if (moveSection)     renderMoveExplainer(moveSection, cachedExplanations[ticker], cachedIntelligence[ticker]);
        });

        // If any rows were open during load, re-sync their max-height to the new content size
        requestAnimationFrame(() => {
            tbody.querySelectorAll(".summary-body.open").forEach(body => {
                if (body.style.maxHeight && body.style.maxHeight !== "none") {
                    body.style.maxHeight = body.scrollHeight + "px";
                }
            });
        });

        renderHoldings();

    } catch (err) {
        intelligenceLoading = false;
        holdingTickers().forEach(ticker => {
            if (!cachedIntelligence[ticker]) cachedIntelligence[ticker] = fallbackIntelligenceForTicker(ticker);
            intelligenceExhaustedTickers.add(ticker);
        });
        intelligenceLoaded = updateIntelligenceLoadedState();
        setAiChecking(false, "Check paused", false);
        injectSummaryRows(tbody);
        Array.from(tbody.querySelectorAll(".intel-move-section")).forEach(renderMoveExplainerFallback);
    } finally {
        if (intelligenceLoading) setAiChecking(false, "Watching holdings", false);
        if (btn) {
            btn.innerHTML = INTEL_BUTTON_READY_HTML;
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
    document.querySelectorAll(".toast-apple").forEach(t => t.remove());
    const icons = {
        success: "bi-check-circle-fill",
        warning: "bi-exclamation-triangle-fill",
        danger:  "bi-x-circle-fill",
        info:    "bi-info-circle-fill",
    };
    const toast = document.createElement("div");
    toast.className = `toast-apple toast-${type}`;
    toast.innerHTML = `<i class="bi ${icons[type] || icons.info} toast-icon"></i><span>${escapeHtml(message)}</span>`;
    document.body.appendChild(toast);
    void toast.offsetWidth;
    toast.classList.add("toast-show");
    setTimeout(() => {
        toast.classList.remove("toast-show");
        setTimeout(() => toast.remove(), 420);
    }, 2800);
}

// Flash a DOM element's content (used on data refresh)
function flashValue(el) {
    if (!el) return;
    el.classList.remove("value-updating");
    void el.offsetWidth;
    el.classList.add("value-updating");
    el.addEventListener("animationend", () => el.classList.remove("value-updating"), { once: true });
}

// Scroll to and briefly highlight a holding row
function highlightHolding(ticker) {
    if (!ticker || ticker === "--") return;
    const row = document.querySelector(`tr[data-ticker="${CSS.escape(ticker)}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    const tds = Array.from(row.querySelectorAll("td"));
    tds.forEach(td => {
        td.style.transition = "background-color 0.32s ease";
        td.style.backgroundColor = "rgba(10, 132, 255, 0.16)";
    });
    setTimeout(() => {
        tds.forEach(td => { td.style.backgroundColor = "rgba(10, 132, 255, 0.06)"; });
    }, 350);
    setTimeout(() => {
        tds.forEach(td => { td.style.backgroundColor = ""; td.style.transition = ""; });
    }, 1700);
}

// Called by stat cards — reads ticker from the element's data attribute
function highlightHoldingFromCard(elId) {
    const ticker = document.getElementById(elId)?.dataset?.ticker;
    if (ticker) highlightHolding(ticker);
}

// Open portfolio manager from the Holdings count card click
function openManageFromCard() {
    const modal = document.getElementById("portfolioModal");
    if (modal) {
        loadManageHoldings();
        new bootstrap.Modal(modal).show();
    }
}

// ── Keyboard shortcut overlay ──────────────────────────────────────────────

function showKeyboardHelp() {
    const overlay = document.getElementById("kbd-overlay");
    if (!overlay) return;
    overlay.classList.add("kbd-visible");
    overlay.setAttribute("aria-hidden", "false");
}

function hideKeyboardHelp() {
    const overlay = document.getElementById("kbd-overlay");
    if (!overlay) return;
    overlay.classList.remove("kbd-visible");
    overlay.setAttribute("aria-hidden", "true");
}

function initKeyboardHelp() {
    const overlay = document.getElementById("kbd-overlay");
    if (!overlay) return;
    overlay.addEventListener("click", hideKeyboardHelp);
    overlay.querySelector(".kbd-panel")?.addEventListener("click", e => e.stopPropagation());
}

// ── Section tip popover system ─────────────────────────────────────────────

function initTips() {
    const popover = document.getElementById("tip-popover");
    if (!popover) return;

    let hideTimeout = null;

    document.querySelectorAll(".tip-trigger").forEach(trigger => {
        trigger.addEventListener("mouseenter", () => {
            clearTimeout(hideTimeout);
            const title   = trigger.dataset.tipTitle   || "";
            const body    = trigger.dataset.tipBody    || "";
            const hint    = trigger.dataset.tipHint    || "";
            const icon    = trigger.dataset.tipIcon    || "bi-info-circle-fill";
            const variant = trigger.dataset.tipVariant || "";

            // Clear previous variant classes
            popover.classList.remove("tip-variant-ai");

            if (variant === "ai") {
                popover.classList.add("tip-variant-ai");
                popover.innerHTML = `
                    <div class="tip-ai-header">
                        <span class="tip-ai-orbit" aria-hidden="true">
                            <img src="/static/img/brand/folio-orbit-icon.svg" alt="">
                        </span>
                        <span class="tip-ai-title-wrap">
                            <div class="tip-ai-name">${escapeHtml(title)}</div>
                            <div class="tip-ai-badge">AI</div>
                        </span>
                    </div>
                    <div class="tip-ai-body">${escapeHtml(body)}</div>
                    <div class="tip-ai-footer">
                        <span class="tip-ai-footer-dot" aria-hidden="true"></span>
                        <span class="tip-ai-footer-label">Powered by Claude</span>
                    </div>
                `;
            } else {
                popover.innerHTML = `
                    <i class="bi ${escapeHtml(icon)} tip-popover-icon" aria-hidden="true"></i>
                    <div class="tip-popover-title">${escapeHtml(title)}</div>
                    <div class="tip-popover-body">${escapeHtml(body)}</div>
                    ${hint ? `<div class="tip-popover-hint"><i class="bi bi-hand-index-thumb" style="font-size:.6rem"></i> ${escapeHtml(hint)}</div>` : ""}
                `;
            }

            // Position below trigger, viewport-clamped
            const rect = trigger.getBoundingClientRect();
            const popW = variant === "ai" ? 260 : 252;
            const popH = popover.offsetHeight || 120;
            let left   = rect.left + rect.width / 2 - popW / 2;
            let top    = rect.bottom + 10;
            left = Math.max(10, Math.min(left, window.innerWidth - popW - 10));
            if (top + popH > window.innerHeight - 14) top = rect.top - popH - 10;

            popover.style.left = `${left}px`;
            popover.style.top  = `${top}px`;
            popover.setAttribute("aria-hidden", "false");
            void popover.offsetWidth;
            popover.classList.add("tip-visible");
        });

        trigger.addEventListener("mouseleave", () => {
            hideTimeout = setTimeout(() => {
                popover.classList.remove("tip-visible");
                popover.setAttribute("aria-hidden", "true");
            }, 160);
        });

        // Keyboard: show on focus, hide on blur
        trigger.addEventListener("focus",  () => trigger.dispatchEvent(new MouseEvent("mouseenter")));
        trigger.addEventListener("blur",   () => trigger.dispatchEvent(new MouseEvent("mouseleave")));

        // Prevent card click when clicking the trigger icon
        trigger.addEventListener("click", e => e.stopPropagation());
    });
}

/* ── Holdings table canvas — active only during AI scan ─────────────────── */
const HoldingsBg = (() => {
    const MIN_DOTS      = 18;
    const MAX_DOTS      = 36;
    const CONN_DIST     = 128;
    const CONN_DIST_SQ  = CONN_DIST * CONN_DIST;
    let canvas, ctx, W = 0, H = 0, dpr = 1, dots = [], raf, running = false, tick = 0;
    let frameCount = 0, washGrad = null, lastTheme = null, inView = true, observer = null;
    let resizeTimer = null;

    function targetDotCount() {
        const area = Math.max(W * H, 1);
        return Math.max(MIN_DOTS, Math.min(MAX_DOTS, Math.round(area / 16500)));
    }

    function mkDot() {
        const angle = Math.random() * Math.PI * 2;
        const speed = 0.12 + Math.random() * 0.18;
        return {
            x:  Math.random() * W,
            y:  Math.random() * H,
            vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed,
            r:  1.1 + Math.random() * 1.9,
            op: 0.45 + Math.random() * 0.38,
            phase: Math.random() * Math.PI * 2,
        };
    }

    function buildGradients() {
        const dark = document.documentElement.dataset.bsTheme !== "light";
        lastTheme = dark;
        const cyan  = dark ? "111,214,240" : "10,120,180";
        const green = dark ? "122,241,205"  : "20,135,92";
        washGrad = ctx.createLinearGradient(0, 0, W, H);
        washGrad.addColorStop(0,    `rgba(${cyan},${dark ? 0.075 : 0.045})`);
        washGrad.addColorStop(0.55, "rgba(151,172,236,0.035)");
        washGrad.addColorStop(1,    `rgba(${green},${dark ? 0.045 : 0.025})`);
    }

    function resize() {
        const card = canvas.closest(".card-body") || canvas.parentElement;
        const rect = card.getBoundingClientRect();
        const nextW = Math.max(1, Math.floor(rect.width));
        const nextH = Math.max(1, Math.floor(rect.height));
        dpr = Math.min(window.devicePixelRatio || 1, 2);

        if (nextW === W && nextH === H && canvas.width === Math.floor(nextW * dpr)) return;

        W = nextW;
        H = nextH;
        canvas.width = Math.floor(W * dpr);
        canvas.height = Math.floor(H * dpr);
        canvas.style.width = `${W}px`;
        canvas.style.height = `${H}px`;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        buildGradients();

        const count = targetDotCount();
        if (!dots.length) {
            dots = Array.from({ length: count }, mkDot);
        } else if (dots.length < count) {
            dots.push(...Array.from({ length: count - dots.length }, mkDot));
        } else if (dots.length > count) {
            dots = dots.slice(0, count);
        }
    }

    function frame() {
        if (!running) return;

        // ~30fps: skip every other RAF tick
        frameCount++;
        if (frameCount % 2 !== 0) {
            raf = requestAnimationFrame(frame);
            return;
        }

        // Pause rendering when tab hidden or card out of view
        if (document.hidden || !inView) {
            return; // loop will resume via visibilitychange / IntersectionObserver
        }

        tick += 0.024; // doubled vs original because we render every other frame

        const dark = document.documentElement.dataset.bsTheme !== "light";
        if (dark !== lastTheme) buildGradients(); // rebuild only on theme switch
        const cyan = dark ? "111,214,240" : "10,120,180";

        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = washGrad;
        ctx.fillRect(0, 0, W, H);

        for (const d of dots) {
            d.x += d.vx;
            d.y += d.vy;
            if (d.x < -10)  d.x = W + 10;
            if (d.x > W+10) d.x = -10;
            if (d.y < -10)  d.y = H + 10;
            if (d.y > H+10) d.y = -10;
        }

        // connections — squared-distance check avoids Math.sqrt, no shadowBlur
        ctx.lineWidth = 0.8;
        for (let i = 0; i < dots.length; i++) {
            for (let j = i + 1; j < dots.length; j++) {
                const dx = dots[i].x - dots[j].x;
                const dy = dots[i].y - dots[j].y;
                const distSq = dx * dx + dy * dy;
                if (distSq < CONN_DIST_SQ) {
                    const a = (dark ? 0.34 : 0.20) * (1 - Math.sqrt(distSq) / CONN_DIST);
                    ctx.strokeStyle = `rgba(${cyan},${a.toFixed(3)})`;
                    ctx.beginPath();
                    ctx.moveTo(dots[i].x, dots[i].y);
                    ctx.lineTo(dots[j].x, dots[j].y);
                    ctx.stroke();
                }
            }
        }

        // nodes — no shadowBlur
        for (const d of dots) {
            const pulse = 0.78 + Math.sin(tick * 2.4 + d.phase) * 0.22;
            ctx.beginPath();
            ctx.arc(d.x, d.y, d.r * pulse, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${cyan},${(dark ? d.op * 0.9 : d.op * 0.62).toFixed(3)})`;
            ctx.fill();
        }

        const sweepX = (Math.sin(tick * 0.9) * 0.5 + 0.5) * W;
        const sweep = ctx.createLinearGradient(sweepX - 160, 0, sweepX + 160, H);
        sweep.addColorStop(0,   "rgba(255,255,255,0)");
        sweep.addColorStop(0.5, `rgba(${cyan},${dark ? 0.10 : 0.055})`);
        sweep.addColorStop(1,   "rgba(255,255,255,0)");
        ctx.fillStyle = sweep;
        ctx.fillRect(0, 0, W, H);

        raf = requestAnimationFrame(frame);
    }

    function resume() {
        if (running && !document.hidden && inView) {
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(frame);
        }
    }

    return {
        init() {
            canvas = document.getElementById("holdings-bg-canvas");
            if (!canvas) return;
            ctx = canvas.getContext("2d");

            window.addEventListener("resize", () => {
                clearTimeout(resizeTimer);
                resizeTimer = setTimeout(() => { if (running) resize(); }, 200);
            });

            document.addEventListener("visibilitychange", resume);

            observer = new IntersectionObserver(entries => {
                inView = entries[0].isIntersecting;
                resume();
            }, { threshold: 0 });
            observer.observe(canvas.closest(".card") || canvas.parentElement);
        },
        start() {
            if (!canvas || prefersReducedMotion()) return;
            resize();
            dots = Array.from({ length: targetDotCount() }, mkDot);
            tick = 0;
            frameCount = 0;
            running = true;
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(frame);
        },
        stop() {
            running = false;
            cancelAnimationFrame(raf);
            if (ctx) ctx.clearRect(0, 0, W, H);
        },
    };
})();
