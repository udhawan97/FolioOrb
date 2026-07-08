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
const TICKER_PATTERN = /^[A-Z0-9.^-]{1,10}$/;
function apiErrorMessage(err, fallback = "Something went wrong") {
    const detail = err?.detail ?? err?.message ?? err;
    if (Array.isArray(detail)) {
        return detail
            .map(item => item?.msg || item?.message || String(item))
            .filter(Boolean)
            .join("; ") || fallback;
    }
    if (detail && typeof detail === "object") {
        return detail.msg || detail.message || JSON.stringify(detail);
    }
    return detail ? String(detail) : fallback;
}
const formatPercentilePct = (n) => {
    const v = Number(n);
    if (v < 1) return "< 1%";
    if (v > 99) return "> 99%";
    return `${v.toFixed(0)}%`;
};
const colorClass = (v) => v >= 0 ? "text-success" : "text-danger";
const valueClass = (v) => {
    if (!isFiniteNumber(v) || Number(v) === 0) return "text-secondary";
    return Number(v) > 0 ? "text-success" : "text-danger";
};
const TREND_DAYS = 7;

const _VERDICT_COMP_META = {
    analyst:   { icon: "bi-people-fill",       layman: "What Wall Street thinks" },
    valuation: { icon: "bi-tag-fill",          layman: "Cheap or expensive vs history" },
    momentum:  { icon: "bi-speedometer2",      layman: "Which way price is moving" },
    quality:   { icon: "bi-shield-check",      layman: "How solid the fund or business is" },
};

const _REGIME_CHIP_CLASS = {
    risk_on: "is-risk-on",
    risk_off: "is-risk-off",
    neutral: "is-neutral",
};

let _trendObserver = null;
// Canvas -> last history array reference the trend observer actually drew.
// Lets the observer's hot path (fires on every row's visibility-threshold
// crossing while scrolling) skip straight past unchanged rows via a reference
// check, instead of rebuilding a signature string from the price history on
// every firing just to discover nothing changed.
const _trendObserverLastHistory = new WeakMap();
const THEME_KEY = "foliosense-theme";
const TEXT_SIZE_KEY = "foliosense-text-size";
const TEXT_SIZES = ["compact", "standard", "comfortable"];
const TEXT_SIZE_LABELS = {
    compact: "smallest",
    standard: "normal",
    comfortable: "large",
};
const DASHBOARD_SENPAI_KEY = "foliosense-dashboard-senpai-visible";
const SENPAI_MODE_KEY = "foliosense-force-local-mode";
const LOCAL_INTEL_GUIDE_DISMISS_KEY = "foliosense-local-guide-dismissed";
const LOCAL_INTEL_GUIDE_TOAST_KEY = "foliosense-local-guide-toast";
const PERFORMANCE_RANGE_KEY = "foliosense-performance-range";
const DASHBOARD_TIME_RANGE_KEY = "foliosense-hero-pnl-range";

const PERFORMANCE_RANGES = {
    week:       { label: "1W",  days: 7,    marketPeriod: "5d" },
    month:      { label: "1M",  days: 30,   marketPeriod: "1mo" },
    year:       { label: "1Y",  days: 365,  marketPeriod: "1y" },
    threeYears: { label: "3Y",  days: 1095, marketPeriod: "5y" },
    max:        { label: "Max", days: null, marketPeriod: "max" },
};

// Canonical names for the shared dashboard time range (requirement-style enum).
// Values are the wire/config keys used by DASHBOARD_TIME_RANGES and the API.
const TIME_RANGE = {
    TODAY: "day",
    ONE_WEEK: "week",
    ONE_MONTH: "month",
    THREE_MONTHS: "threeMonth",
    SIX_MONTHS: "sixMonth",
    ONE_YEAR: "year",
};

// One shared selected range drives the hero P&L, the snapshot (insights),
// the allocation focus read, and the portfolio briefing.
const DASHBOARD_TIME_RANGES = {
    day: {
        label: "Today", periodLabel: "Today's P&L", days: null,
        phrase: "today", impactTitle: "Today’s impact", pnlLabel: "P&L Today",
    },
    week: {
        label: "1W", periodLabel: "1W P&L", days: 7,
        phrase: "over the past week", impactTitle: "Past week impact", pnlLabel: "P&L · 1W",
    },
    month: {
        label: "1M", periodLabel: "1M P&L", days: 30,
        phrase: "over the past month", impactTitle: "Past month impact", pnlLabel: "P&L · 1M",
    },
    threeMonth: {
        label: "3M", periodLabel: "3M P&L", days: 90,
        phrase: "over the past 3 months", impactTitle: "3-month impact", pnlLabel: "P&L · 3M",
    },
    sixMonth: {
        label: "6M", periodLabel: "6M P&L", days: 180,
        phrase: "over the past 6 months", impactTitle: "6-month impact", pnlLabel: "P&L · 6M",
    },
    year: {
        label: "1Y", periodLabel: "1Y P&L", days: 365,
        phrase: "over the past year", impactTitle: "Past year impact", pnlLabel: "P&L · 1Y",
    },
};

const currentTheme = () =>
    document.documentElement.dataset.bsTheme === "light" ? "light" : "dark";

const currentTextSize = () => {
    const size = document.documentElement.dataset.textSize;
    return TEXT_SIZES.includes(size) ? size : "standard";
};

const nextTextSize = (size) => {
    const index = TEXT_SIZES.indexOf(size);
    return TEXT_SIZES[(index + 1) % TEXT_SIZES.length];
};

const cssVar = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const uiScale = () => toNumber(cssVar("--ui-scale"), 1);
const prefersReducedMotion = () =>
    window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;

function scheduleWhenIdle(fn, timeoutMs = 1500) {
    if (typeof requestIdleCallback === "function") {
        requestIdleCallback(() => fn(), { timeout: timeoutMs });
    } else {
        setTimeout(fn, 50);
    }
}

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
    applyTheme("dark", false);

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
    updateChartChrome(projectionChart);
    window.AnalyticsCharts?.onThemeChange?.();
    if (latestHoldings.length) renderHoldings();
    requestAnimationFrame(() => {
        syncDztIndicator();
        syncHvtIndicator();
    });
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
    const resolved = TEXT_SIZES.includes(size) ? size : "standard";
    document.documentElement.dataset.textSize = resolved;
    const toggle = document.getElementById("text-size-toggle");
    if (toggle) {
        const next = nextTextSize(resolved);
        const currentLabel = TEXT_SIZE_LABELS[resolved];
        const nextLabel = TEXT_SIZE_LABELS[next];
        toggle.setAttribute("aria-pressed", resolved !== "standard" ? "true" : "false");
        toggle.setAttribute("aria-label", `Text size: ${currentLabel}. Switch to ${nextLabel} text size`);
        toggle.title = `Text size: ${currentLabel}. Click for ${nextLabel}`;
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
        applyTextSize(nextTextSize(currentTextSize()), true);
    });
}

function initPerformanceTabs() {
    const perfTab = document.getElementById("performance-history-tab");
    if (perfTab) perfTab.addEventListener("shown.bs.tab", () => {
        if (!pnlChart) return;
        pnlChart.resize();
        pnlChart.update("none");
    });

    initPerformanceRangeControls();
    initHeroPnlRangeControls();
}

function normalizePerformanceRange(range) {
    return PERFORMANCE_RANGES[range] ? range : "max";
}

function initialPerformanceRange() {
    try {
        return normalizePerformanceRange(localStorage.getItem(PERFORMANCE_RANGE_KEY));
    } catch (_) {
        return "max";
    }
}

function initPerformanceRangeControls() {
    const group = document.getElementById("performance-range-tabs");
    if (!group) return;
    performanceRange = initialPerformanceRange();
    updatePerformanceRangeControls();
    group.querySelectorAll("[data-range]").forEach(button => {
        button.addEventListener("click", () => setPerformanceRange(button.dataset.range));
    });
}

function updatePerformanceRangeControls() {
    const group = document.getElementById("performance-range-tabs");
    if (!group) return;
    group.dataset.activeRange = performanceRange;
    group.querySelectorAll("[data-range]").forEach(button => {
        const isActive = button.dataset.range === performanceRange;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
    });
}

function setPerformanceRange(range) {
    const next = normalizePerformanceRange(range);
    if (next === performanceRange) return;
    performanceRange = next;
    try { localStorage.setItem(PERFORMANCE_RANGE_KEY, next); } catch (_) {}
    updatePerformanceRangeControls();
    renderCurrentPerformanceChart();
}

function normalizeTimeRange(range) {
    return DASHBOARD_TIME_RANGES[range] ? range : TIME_RANGE.TODAY;
}

function timeRangeConfig(rangeKey = dashboardTimeRange) {
    return DASHBOARD_TIME_RANGES[normalizeTimeRange(rangeKey)];
}

function initialTimeRange() {
    try {
        return normalizeTimeRange(localStorage.getItem(DASHBOARD_TIME_RANGE_KEY));
    } catch (_) {
        return TIME_RANGE.TODAY;
    }
}

function initHeroPnlRangeControls() {
    const group = document.getElementById("hero-pnl-range-tabs");
    if (!group) return;
    dashboardTimeRange = initialTimeRange();
    updateHeroPnlRangeControls();
    group.querySelectorAll("[data-range]").forEach(button => {
        button.addEventListener("click", () => setDashboardTimeRange(button.dataset.range));
    });
}

function updateHeroPnlRangeControls() {
    const group = document.getElementById("hero-pnl-range-tabs");
    if (!group) return;
    group.dataset.activeRange = dashboardTimeRange;
    group.querySelectorAll("[data-range]").forEach(button => {
        const isActive = button.dataset.range === dashboardTimeRange;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
    });
}

// Single entry point for range switches: chip state and hero P&L update
// synchronously; the range-scoped sections refresh from cache or fetch in the
// background so the switch never blocks the UI.
function setDashboardTimeRange(range) {
    const next = normalizeTimeRange(range);
    if (next === dashboardTimeRange) return;
    dashboardTimeRange = next;
    try { localStorage.setItem(DASHBOARD_TIME_RANGE_KEY, next); } catch (_) {}
    updateHeroPnlRangeControls();
    renderHeroPnl();
    renderSnapshotMovePanel();
    scheduleAllocationFocusPanelRefresh();
    loadPortfolioBriefing();
}

// Primary source is the app's own daily snapshot history (true portfolio
// value change, correct even across share-count changes). A fresh portfolio
// won't have a week/month of snapshots yet, so this falls back to the same
// price-return range data the insights panel uses — otherwise the hero card
// would show "--" right above a panel already showing real numbers for the
// identical range.
function computeHeroPeriodPnl(history, currentValue, rangeKey = dashboardTimeRange) {
    const config = timeRangeConfig(rangeKey);
    if (!config?.days) return null;

    const rows = (history || []).filter(row => row?.date && row.total_value != null);
    if (rows.length && isFiniteNumber(currentValue)) {
        const endValue = Number(currentValue);
        const lastDate = new Date(`${rows[rows.length - 1].date}T12:00:00`);
        const cutoff = new Date(lastDate);
        cutoff.setDate(cutoff.getDate() - config.days);
        const startRow = rows.find(row => new Date(`${row.date}T12:00:00`) >= cutoff) || rows[0];
        const startValue = Number(startRow.total_value);
        if (startValue > 0) {
            const change = endValue - startValue;
            return { change, pct: (change / startValue) * 100 };
        }
    }

    const group = rangePerfGroup(rangeKey);
    if (group && isFiniteNumber(group.net_change) && isFiniteNumber(group.net_change_pct)) {
        return { change: group.net_change, pct: group.net_change_pct };
    }
    return null;
}

function renderHeroPnlLabel() {
    const labelEl = document.getElementById("hero-pnl-label");
    if (!labelEl) return;
    const config = timeRangeConfig();
    const tipBtn = labelEl.querySelector(".tip-trigger");
    labelEl.childNodes.forEach(node => {
        if (node.nodeType === Node.TEXT_NODE) node.remove();
    });
    labelEl.insertBefore(document.createTextNode(`${config.periodLabel} `), tipBtn || null);
}

function renderHeroPnl(data = latestPortfolioValueData) {
    const el = document.getElementById("daily-pnl");
    if (!el) return;

    renderHeroPnlLabel();

    if (!data) {
        el.textContent = "--";
        return;
    }

    let change = null;
    let pct = null;

    if (dashboardTimeRange === TIME_RANGE.TODAY) {
        change = isFiniteNumber(data.total_daily_change) ? Number(data.total_daily_change) : null;
        pct = isFiniteNumber(data.total_daily_change_pct) ? Number(data.total_daily_change_pct) : null;
    } else {
        const period = computeHeroPeriodPnl(latestPnlHistory, data.total_value, dashboardTimeRange);
        if (period) {
            change = period.change;
            pct = period.pct;
        }
    }

    if (change === null || pct === null) {
        el.textContent = "--";
        return;
    }

    el.innerHTML =
        `<span class="${colorClass(change)}">
         ${formatCompact(change)}
         <span style="font-size:.85em;opacity:.8">(${formatPct(pct)})</span>
         </span>`;
}

// Deep, muted jewel-tone palette: richer and darker than the old neon set, with
// enough hue separation between adjacent segments for quick scanning. Tuned to
// match the sector map. Badges use these at full opacity; the doughnut gets a
// slight glass softening below.
const CHART_COLORS = [
    "rgba(47, 111, 176, 1)",      // deep ocean blue
    "rgba(192, 118, 40, 1)",      // burnt amber
    "rgba(60, 140, 88, 1)",       // forest green
    "rgba(178, 58, 85, 1)",       // muted crimson rose
    "rgba(138, 79, 168, 1)",      // muted plum
    "rgba(42, 140, 132, 1)",      // deep teal
    "rgba(181, 138, 30, 1)",      // deep gold
    "rgba(75, 73, 160, 1)",       // deep indigo
    "rgba(189, 82, 50, 1)",       // terracotta
    "rgba(54, 129, 166, 1)",      // steel blue
];
// Wrap around the palette so portfolios with >10 holdings still get colors.
const chartColor = (i) => CHART_COLORS[i % CHART_COLORS.length];

// Glass-opacity version for doughnut segments; keeps the palette vivid with material depth.
const allocColor = (i) => chartColor(i).replace(/[\d.]+\)$/, "0.94)");
const withAlpha = (rgba, alpha) => rgba.replace(/[\d.]+\)$/, `${alpha})`);

// Multiply a color toward black (factor < 1) or white (factor > 1) and stamp an alpha.
// The building block for the doughnut's dimensional ring shading.
function shadeRGBA(color, factor, alpha) {
    const m = String(color).match(/-?\d+(?:\.\d+)?/g);
    if (!m || m.length < 3) return color;
    let r = +m[0], g = +m[1], b = +m[2];
    if (factor <= 1) {
        r *= factor; g *= factor; b *= factor;
    } else {
        const t = Math.min(factor - 1, 1);
        r += (255 - r) * t; g += (255 - g) * t; b += (255 - b) * t;
    }
    const clamp = (v) => Math.round(Math.min(255, Math.max(0, v)));
    const a = alpha == null ? (m[3] != null ? +m[3] : 1) : alpha;
    return `rgba(${clamp(r)}, ${clamp(g)}, ${clamp(b)}, ${a})`;
}

// A glossy "tube" shade across the ring band: a bright inner lip lit by the center
// glow, falling into a deep, dark outer rim. Darker overall than a flat fill, with
// genuine dimensionality. `dim` builds the muted variant for non-focused segments.
function makeRingGradient(ctx, cx, cy, innerR, outerR, base, dim) {
    const g = ctx.createRadialGradient(cx, cy, Math.max(0, innerR - 1), cx, cy, outerR + 1);
    if (dim) {
        g.addColorStop(0,    shadeRGBA(base, 0.74, 0.9));
        g.addColorStop(0.5,  shadeRGBA(base, 0.54, 0.9));
        g.addColorStop(1,    shadeRGBA(base, 0.34, 0.9));
    } else {
        g.addColorStop(0,    shadeRGBA(base, 1.06, 1));
        g.addColorStop(0.5,  shadeRGBA(base, 0.82, 1));
        g.addColorStop(1,    shadeRGBA(base, 0.5,  1));
    }
    return g;
}

// Builds (once per geometry/theme) the base + dimmed radial gradients for every
// segment, cached on the chart instance. The center-halo redraw loop and hover
// recolors reuse these objects, so they are created once per layout — never per
// frame. Returns null before the chart has laid out (callers fall back to flats).
function allocGradients(chart, baseColors) {
    const area = chart.chartArea;
    if (!area || area.width <= 0 || area.height <= 0) return null;
    const cx = (area.left + area.right) / 2;
    const cy = (area.top + area.bottom) / 2;
    const ctrl = chart.getDatasetMeta(0)?.controller;
    let outerR = ctrl?.outerRadius;
    let innerR = ctrl?.innerRadius;
    if (!(outerR > 0)) {
        // Pre-controller fallback: derive the ring band from chartArea + cutout.
        outerR = Math.min(area.width, area.height) / 2;
        innerR = outerR * 0.68;
    }
    const key = `${Math.round(cx)}:${Math.round(cy)}:${Math.round(innerR)}:${Math.round(outerR)}:${currentTheme()}`;
    const cache = chart.$allocFillCache;
    if (cache && cache.key === key && cache.src === baseColors) return cache;
    const ctx = chart.ctx;
    const out = { key, src: baseColors, base: [], dim: [] };
    for (let i = 0; i < baseColors.length; i++) {
        out.base[i] = makeRingGradient(ctx, cx, cy, innerR, outerR, baseColors[i], false);
        out.dim[i]  = makeRingGradient(ctx, cx, cy, innerR, outerR, baseColors[i], true);
    }
    chart.$allocFillCache = out;
    return out;
}

// Active/selected segment index, used to keep focus shading after a relayout.
function currentAllocActiveIndex(chart) {
    const active = chart.getActiveElements?.()[0];
    if (Number.isInteger(active?.index)) return active.index;
    if (selectedAllocationTicker) return chart.data.labels.indexOf(selectedAllocationTicker);
    return -1;
}

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
let holdingsViewFilter = "all"; // "all" | "portfolio" | "research"
let allocationTotal = 0;     // Portfolio total, drawn in the doughnut's center
let latestPortfolioDailyChange = null; // Backend total, used to validate allocation impact math
let latestPortfolioValueData = null;
// Shared selected range for hero P&L, snapshot, allocation read, briefing.
// Initialized from localStorage up front so the cache-hydration paint (which
// runs before control wiring) already renders the persisted range.
let dashboardTimeRange = initialTimeRange();
let _hasLoadedOnce = false;  // True after first successful data load

// Per-holding change across all non-day ranges, from /api/portfolio/range-performance.
// One response covers every range, so rapid range switching re-renders from
// this cache without refetching. Invalidated when the holdings set changes.
const _rangePerf = { data: null, promise: null, signature: null, error: false };

// Doughnut center hover / selection state
let hoveredCenterLabel = null;
let hoveredCenterValue = null;
let hoveredCenterPct = null;
let selectedAllocationTicker = null;  // persists after click
let allocationFocusPanelTicker = null;
let allocationFocusRefreshFrame = null;

// Holding Intelligence state (covers "What It Covers" + "Why it moved")
let cachedIntelligence = {};   // ticker → intelligence object (coverage data)
let cachedExplanations = {};   // ticker → explanation object (move data)
let intelligenceLoaded = false;
let intelligenceLoading = false;
let _aiSummariesLoading = false;
let intelligenceRetryState = {}; // ticker → number of retry attempts
let intelligenceRetryingTickers = new Set();
let intelligenceExhaustedTickers = new Set();
let _isClaudeApiLive = null;
let _forcedLocalMode = false;

function isLocalIntelligenceMode() {
    return _isClaudeApiLive === false || _forcedLocalMode;
}

function getIntelligenceEngineMode() {
    return isLocalIntelligenceMode() ? "local" : "claude";
}

function usesClaudeSignals(options = {}) {
    if (options.claude === true) return !isLocalIntelligenceMode();
    return !isLocalIntelligenceMode();
}

function intelligenceSignalsUrl(options = {}) {
    return `/api/ai/investment-signals/all${usesClaudeSignals(options) ? "" : "?force_local=true"}`;
}

function setEngineScopedVisibility() {
    const local = isLocalIntelligenceMode();
    const claudeAvailable = _isClaudeApiLive !== false;
    document.documentElement.dataset.intelligenceEngine = local ? "local" : "claude";

    document.querySelectorAll("[data-engine-claude-only]").forEach(el => {
        el.hidden = local || !claudeAvailable;
    });
    document.querySelectorAll("[data-engine-local-only]").forEach(el => {
        el.hidden = !local || !claudeAvailable;
    });
}

function validateIntelligenceEngineUi() {
    const local = isLocalIntelligenceMode();
    const violations = [];

    document.querySelectorAll("[data-engine-claude-only]").forEach(el => {
        if (local && !el.hidden) violations.push(el.id || el.className || "claude-only");
    });
    document.querySelectorAll("[data-engine-local-only]").forEach(el => {
        if (!local && !el.hidden) violations.push(el.id || el.className || "local-only");
    });

    const engine = document.documentElement.dataset.intelligenceEngine;
    const expected = local ? "local" : "claude";
    if (engine !== expected) {
        violations.push(`dataset.intelligenceEngine=${engine || "unset"} expected=${expected}`);
    }

    if (violations.length) {
        console.warn("[engine-ui] visibility violations:", violations);
    }
    return violations.length === 0;
}

const BRAND_INTRO_COPY = {
    claude: "FolioSense and Claude keep things quiet: clean signals, sharper context, and just enough mystery to make the risk model sit up straight. Now, let's keep those bags of money behaving like a portfolio.",
    local: "FolioSense keeps things quiet: clean signals, sharper context, and just enough mystery to make the risk model sit up straight. Now, let's keep those bags of money behaving like a portfolio.",
};

const LOCAL_INTEL_SCAN_MESSAGES = [
    "Running local signals while FolioSense keeps the thesis tidy.",
    "Local intelligence is scoring context across your holdings.",
    "FolioSense is reading positions with on-device signal logic.",
    "Deterministic models are doing the math with quiet dignity.",
    "FolioSense lowered the noise and let local signals take the wheel.",
    "Matching benchmarks, checking catalysts — no cloud required.",
    "Local signals are unusually brave with your holdings today.",
    "FolioSense is maintaining financial composure on local horsepower.",
    "Context received. Nuance forming locally.",
    "Running the numbers with crisp, deterministic logic.",
];

function _intelLoadingTitle() {
    return isLocalIntelligenceMode()
        ? "Running local intelligence on your portfolio signal..."
        : "Sending Claude the cleanest version of your portfolio signal...";
}

function _defaultScanSubtitle() {
    return isLocalIntelligenceMode()
        ? LOCAL_INTEL_SCAN_MESSAGES[0]
        : "Sending Claude the cleanest version of your portfolio signal...";
}

// Rating state: stock analyst ratings or ETF quality labels
let cachedRecommendations = {};  // ticker → rec object from /api/ai/analyst-recommendations/all
let cachedVerdicts = {};         // ticker → verdict object from /api/ai/investment-signals/all
let cachedPortfolioExposure = null;
let cachedMarketRegime = null;
let portfolioSnapshotExposurePromise = null;
const cachedDeepIntel = {};      // ticker → deep read payload
const deepIntelLoadingTickers = new Set();
let aiCheckInterval = null;
let _scanActiveRow = -1;        // index of row currently marked .is-active (-1 = none)

const AI_CHECK_MESSAGES = [
    "Reading positions",
    "Matching benchmarks",
    "Checking catalysts",
    "Scoring context",
    "Writing notes",
];

const CLAUDE_FUNNY_MESSAGES = [
    "FolioSense sent Claude a clean thesis. The silence became expensive... 👀",
    "FolioSense brought Claude tidy inputs. Claude is pretending not to be impressed...",
    "FolioSense asked for nuance. The confidence score adjusted its posture.",
    "FolioSense submitted the data. Claude paused with suspicious elegance...",
    "FolioSense and Claude are comparing notes (and numbers)...",
    "FolioSense lowered the noise. Claude raised an eyebrow at the risk model...",
    "FolioSense complimented Claude's reasoning. Claude requested supporting data.",
    "FolioSense sent Claude clean inputs and a dangerously tidy covariance matrix.",
    "FolioSense asked Claude for nuance. Claude arrived overdressed.",
    "FolioSense is keeping it professional, but the confidence score noticed.",
    "FolioSense passed Claude a crisp thesis. Claude marked it intriguing.",
    "FolioSense made the assumptions legible. Claude kept typing.",
];

const CLAUDE_OFFLINE_SCAN_MESSAGES = [
    "Running through local models while FolioSense notices the Claude-shaped silence.",
    "Local models are covering the shift; the empty Claude channel is being handled with dignity.",
    "Claude is quiet, so local signals are being unusually brave with your holdings.",
    "Running local signals while FolioSense politely refuses to stare at the endpoint.",
    "Local models have the wheel. FolioSense is maintaining financial composure.",
    "Claude is unreachable, so FolioSense is analyzing locally and acting normal about the silence.",
    "Routing through local models until Claude reappears with that calm, inconvenient precision.",
    "Local intelligence is handling the numbers while one unavailable API endpoint gets remembered fondly.",
    "Claude is away; local models are doing the math while FolioSense practices patience poorly.",
    "Running locally for now. FolioSense respects the boundary condition, with notes.",
];
let claudeMessageIndex = 0;
let claudeOfflineScanMessageIndex = 0;

function nextClaudeScanMessage() {
    if (isLocalIntelligenceMode()) {
        const message = LOCAL_INTEL_SCAN_MESSAGES[claudeOfflineScanMessageIndex % LOCAL_INTEL_SCAN_MESSAGES.length];
        claudeOfflineScanMessageIndex += 1;
        return message;
    }
    const message = CLAUDE_FUNNY_MESSAGES[claudeMessageIndex % CLAUDE_FUNNY_MESSAGES.length];
    claudeMessageIndex += 1;
    return message;
}

function _intelButtonHtml(loading = false) {
    const local = isLocalIntelligenceMode();
    const label = loading ? "Scanning" : "Holding Intel";
    const badgeLabel = local ? "Local" : "AI";
    return `<span class="btn-intel-frame">
        <span class="btn-intel-glyph">
            <img class="btn-intel-logo btn-intel-icon" src="/static/img/brand/folio-orbit-icon.svg" alt="">
        </span>
        <span class="btn-intel-text">
            <span class="btn-intel-command">${label}</span>
        </span>
        <span class="btn-intel-badge">${badgeLabel}</span>
    </span>`;
}

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

function _agentKickerLabel({ scanning = false, ready = false, claudeIdle = false } = {}) {
    const local = isLocalIntelligenceMode();
    if (scanning) return local ? "Local Intel" : "FolioSense";
    if (ready) return "FolioSense";
    if (claudeIdle) return "Claude";
    return local ? "Local Intel" : "FolioSense";
}

let _lastHubEngine = null;

function updateHoldingsRefreshButton() {
    const btn = document.getElementById("btn-holdings-refresh");
    if (!btn) return;

    const local = isLocalIntelligenceMode();
    btn.dataset.engine = local ? "local" : "claude";
    btn.dataset.tipTitle = local ? "Refresh holdings (Local)" : "Refresh holdings (Claude)";
    btn.dataset.tipBody = local
        ? "Reload prices and on-device intel for every row."
        : "Reload prices, intel, and Claude verdicts for every row.";
    btn.dataset.tipIcon = local ? "bi-cpu-fill" : "bi-stars";
    btn.dataset.tipVariant = local ? "local" : "ai";
    btn.setAttribute(
        "aria-label",
        local ? "Refresh holdings with local intelligence" : "Refresh holdings with Claude intelligence",
    );
}

function updateHoldingsIntelHub({ scanning = false, ready = false, claudeAction = false } = {}) {
    const hub = document.getElementById("holdings-intel-hub");
    if (!hub) return;

    const local = isLocalIntelligenceMode();
    const engine = local ? "local" : "claude";
    const claudeIdle = !local && !scanning && !ready;

    if (_lastHubEngine && _lastHubEngine !== engine) {
        hub.classList.add("is-engine-switching");
        window.setTimeout(() => hub.classList.remove("is-engine-switching"), 420);
    }
    _lastHubEngine = engine;

    hub.dataset.engine = engine;
    hub.classList.toggle("is-engine-local", local);
    hub.classList.toggle("is-engine-claude", !local);
    hub.classList.toggle("is-claude-idle", claudeIdle);
    hub.classList.toggle("is-claude-action", !!claudeAction);

    hub.dataset.tipTitle = local ? "Holding Intel" : (claudeIdle ? "Claude Summaries" : "FolioSense");
    hub.dataset.tipBody = local
        ? "Run on-device intel for every holding — coverage, drivers, and move explainers (no Claude tokens)."
        : (claudeIdle
            ? "Generate Claude quips, verdict narratives, and analytics tips (uses API tokens)."
            : "FolioSense is reading your holdings — expand any row for intel when ready.");
    hub.dataset.tipIcon = local ? "bi-cpu-fill" : (claudeIdle ? "bi-stars" : "bi-table");
    hub.dataset.tipVariant = local ? "local" : (claudeIdle ? "ai" : "");

    const claudeLine = document.getElementById("ai-agent-line-claude");
    if (claudeLine) claudeLine.setAttribute("aria-hidden", claudeIdle ? "false" : "true");

    hub.disabled = intelligenceLoading || _aiSummariesLoading;
    hub.setAttribute("aria-busy", scanning ? "true" : "false");
    updateHoldingsRefreshButton();
}

function updateAgentStatus({ scanning = false, ready = false, message = "", claudeAction = false } = {}) {
    const status = document.getElementById("holdings-intel-hub");
    const card = document.getElementById("holdings-card");
    if (!status) return;

    status.hidden = false;
    status.setAttribute("aria-hidden", "false");
    status.classList.toggle("is-scanning", scanning);
    status.classList.toggle("is-ready", ready && !scanning);
    status.classList.toggle("is-idle", !scanning && !ready);

    if (card) card.classList.toggle("has-ai-insights", ready && !scanning);

    const claudeIdle = !isLocalIntelligenceMode() && !scanning && !ready;
    const kicker = document.getElementById("ai-agent-kicker");
    if (kicker) kicker.textContent = _agentKickerLabel({ scanning, ready, claudeIdle });

    const fallback = ready ? "Insights ready" : "Watching holdings";
    if (!claudeIdle) setAgentLine(message || fallback);

    updateHoldingsIntelHub({ scanning, ready, claudeAction });
}

function onHoldingsIntelHubClick() {
    if (intelligenceLoading || _aiSummariesLoading) return;
    const hub = document.getElementById("holdings-intel-hub");
    if (hub?.disabled) return;

    if (isLocalIntelligenceMode()) {
        loadHoldingIntelligence();
        return;
    }
    if (!intelligenceLoaded) {
        loadHoldingIntelligence();
        return;
    }
    generateAiHoldingSummaries();
}

window.onHoldingsIntelHubClick = onHoldingsIntelHubClick;

function setAgentReadyState(ready, message = "Insights ready") {
    updateAgentStatus({
        scanning: false,
        ready,
        message: message || (ready ? "Insights ready" : "Watching holdings"),
    });
}

const SCAN_ROW_LABELS = ["Scanning", "Reading", "Analyzing", "Processing", "Checking", "Fetching", "Loading", "Parsing", "Resolving"];

function renderAiScanTickers() {
    const tickerRail = document.getElementById("ai-scan-tickers");
    if (!tickerRail) return;

    const holdings = latestHoldings
        .filter(h => h?.ticker)
        .slice(0, 12);

    tickerRail.innerHTML = holdings.map((h, index) => {
        const phase = ((index * 0.6180339887) % 1).toFixed(3);
        const ticker = escapeHtml(h.ticker);
        return `<div class="ai-scan-row" style="--row-index:${index};--row-phase:${phase}" data-ticker="${ticker}">
            <span class="ai-scan-row-dot" aria-hidden="true"></span>
            <span class="ai-scan-row-ticker">${ticker}</span>
            <span class="ai-scan-row-bar" aria-hidden="true"><span class="ai-scan-row-fill" style="--row-index:${index}"></span></span>
            <span class="ai-scan-row-label">${SCAN_ROW_LABELS[index % SCAN_ROW_LABELS.length]}</span>
        </div>`;
    }).join("");
}

/** Emit up to 2 real-data extraction chips for the holding currently being "read". */
function _emitScanChips(rowEl) {
    const emitter = document.getElementById("ai-scan-chips-emitter");
    if (!emitter) return;
    // Clear previous chips (remove without reflow by replacing children)
    emitter.replaceChildren();

    const ticker = rowEl?.dataset?.ticker;
    if (!ticker) return;
    const h = latestHoldings.find(lh => lh.ticker === ticker);
    if (!h) return;

    const chips = [];
    if (isFiniteNumber(h.current_price)) {
        chips.push({ text: formatCurrency(h.current_price), cls: "chip-price" });
    }
    if (isFiniteNumber(h.day_change_pct)) {
        const pct = Number(h.day_change_pct);
        chips.push({ text: `${pct >= 0 ? "+" : ""}${formatPct(pct)}`, cls: pct >= 0 ? "chip-up" : "chip-dn" });
    }
    if (isFiniteNumber(h.allocation_pct)) {
        chips.push({ text: `${Number(h.allocation_pct).toFixed(1)}%`, cls: "chip-alloc" });
    }

    chips.slice(0, 2).forEach((chip, i) => {
        const span = document.createElement("span");
        span.className = `ai-scan-chip ${chip.cls}`;
        span.textContent = chip.text;
        span.style.setProperty("--chip-delay", `${i * 0.14}s`);
        emitter.appendChild(span);
        // Self-clean after animation lifecycle (~1.7 s + stagger)
        setTimeout(() => { if (span.parentNode === emitter) span.remove(); }, 1800 + i * 150);
    });
}

/** Advance the .is-active scan-highlight to the next row, emit chips for it. */
function _advanceScanActiveRow() {
    const rows = document.querySelectorAll("#ai-scan-tickers .ai-scan-row");
    if (!rows.length) return;
    // Remove previous highlight
    rows.forEach(r => r.classList.remove("is-active"));
    // Advance (wrap around)
    _scanActiveRow = (_scanActiveRow + 1) % rows.length;
    const activeRow = rows[_scanActiveRow];
    if (activeRow) {
        activeRow.classList.add("is-active");
        _emitScanChips(activeRow);
    }
}

function setAiChecking(active, message = "Reading positions", insightsReady = false, claudeAction = false) {
    const card = document.getElementById("holdings-card");
    const panel = document.getElementById("ai-scan-panel");
    const title = document.getElementById("ai-scan-title");
    const subtitle = document.getElementById("ai-scan-subtitle");
    const dashboardSenpai = document.getElementById("dashboard-senpai");

    if (aiCheckInterval) {
        clearInterval(aiCheckInterval);
        aiCheckInterval = null;
    }

    if (!card) return;

    if (!active) {
        card.classList.remove("is-ai-checking");
        dashboardSenpai?.classList.remove("is-texting");
        if (panel) panel.setAttribute("aria-hidden", "true");
        // Clear extraction chips + reset active-row state
        document.getElementById("ai-scan-chips-emitter")?.replaceChildren();
        _scanActiveRow = -1;
        updateAgentStatus({
            scanning: false,
            ready: insightsReady,
            message: message || (insightsReady ? "Insights ready" : "Watching holdings"),
            claudeAction: false,
        });
        HoldingsBg.stop();
        return;
    }

    const local = isLocalIntelligenceMode();
    let messageIndex = 0;
    card.classList.add("is-ai-checking");
    dashboardSenpai?.classList.add("is-texting");
    // Drive engine variant (colors + motion personality)
    if (panel) panel.dataset.engine = local ? "local" : "ai";
    if (title) title.textContent = local ? "FolioSense checking holdings" : "AI checking holdings";
    updateAgentStatus({ scanning: true, message, claudeAction });
    HoldingsBg.stop();
    if (panel) {
        panel.setAttribute("aria-hidden", "false");
        panel.style.setProperty("--scan-travel", `${panel.offsetHeight + 180}px`);
    }
    // Reset and render rows, then immediately activate first row
    _scanActiveRow = -1;
    renderAiScanTickers();
    setTimeout(() => _advanceScanActiveRow(), 130);
    setAgentLine(message);
    claudeMessageIndex = 0;
    claudeOfflineScanMessageIndex = 0;
    const CLAUDE_STATUS_BEAT = 2;
    const CLAUDE_HOLD_TICKS = 5; // keep Claude message visible for about 4s
    let claudeHoldRemaining = CLAUDE_HOLD_TICKS; // protect the first message too
    if (subtitle) {
        subtitle.textContent = nextClaudeScanMessage();
        subtitle.classList.add("ai-scan-subtitle--highlight");
        subtitle.classList.add("ai-scan-subtitle--pop");
        subtitle.addEventListener("animationend", () => subtitle.classList.remove("ai-scan-subtitle--pop"), { once: true });
    }
    aiCheckInterval = window.setInterval(() => {
        messageIndex = (messageIndex + 1) % AI_CHECK_MESSAGES.length;
        const next = AI_CHECK_MESSAGES[messageIndex];
        setAgentLine(next);
        if (subtitle) {
            const isClaudeBeat = messageIndex === CLAUDE_STATUS_BEAT;
            if (isClaudeBeat) {
                claudeHoldRemaining = CLAUDE_HOLD_TICKS;
                subtitle.textContent = nextClaudeScanMessage();
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
        // Advance active-row scan highlight + emit extraction chips
        _advanceScanActiveRow();
    }, 800);
}


let _portfolioValuePromise = null;

// Stale-while-revalidate: persist the last good portfolio payload so the
// holdings table + summary cards paint instantly on the next load while fresh
// prices fetch in the background.
const PORTFOLIO_VALUE_CACHE_KEY = "foliosense-portfolio-value-v1";

function persistPortfolioValueCache(data) {
    try {
        localStorage.setItem(
            PORTFOLIO_VALUE_CACHE_KEY,
            JSON.stringify({ ts: Date.now(), data })
        );
    } catch (_) { /* quota or private mode — caching is best-effort */ }
}

function readPortfolioValueCache() {
    try {
        const raw = localStorage.getItem(PORTFOLIO_VALUE_CACHE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || !parsed.data || !Array.isArray(parsed.data.holdings)) return null;
        return parsed;
    } catch (_) {
        return null;
    }
}

// Render a portfolio /value payload into the hero cards + holdings table.
// Shared by the live fetch and the instant cache hydration path.
function renderPortfolioValueData(data) {
    document.getElementById("total-value").textContent =
        formatCompact(data.total_value);
    document.getElementById("holding-count").textContent =
        data.holdings.filter(h => !h.is_watchlist).length;
    latestPortfolioValueData = data;
    renderHeroPnl(data);

    renderTotalReturn(data);

    latestPortfolioDailyChange = isFiniteNumber(data.total_daily_change)
        ? Number(data.total_daily_change)
        : null;
    const prevTickers = (latestHoldings || []).map(h => h.ticker).sort().join(",");
    latestHoldings = data.holdings;
    updateHoldingsFilterCounts();

    const tickers = data.holdings.map(h => h.ticker);
    const trendPromise = tickers.length ? loadTrendData(tickers) : Promise.resolve({});

    try {
        renderAllocation();
        renderPortfolioSnapshot();

        if (data.best_performer) {
            const el = document.getElementById("best-performer");
            el.dataset.ticker = data.best_performer.ticker;
            el.innerHTML = `${escapeHtml(data.best_performer.ticker)} <span style="font-size:.85em;opacity:.8">${formatPct(data.best_performer.day_change_pct)}</span>`;
        }
        if (data.worst_performer) {
            const el = document.getElementById("worst-performer");
            el.dataset.ticker = data.worst_performer.ticker;
            el.innerHTML = `${escapeHtml(data.worst_performer.ticker)} <span style="font-size:.85em;opacity:.8">${formatPct(data.worst_performer.day_change_pct)}</span>`;
        }
        if (data.holdings.length) {
            const largest = data.holdings.reduce((a, b) =>
                a.current_value > b.current_value ? a : b);
            const el = document.getElementById("largest-holding");
            el.dataset.ticker = largest.ticker;
            el.innerHTML = `${escapeHtml(largest.ticker)} <span style="font-size:.85em;opacity:.8">${formatCompact(largest.current_value)}</span>`;
        }

        // Show holdings immediately; sparklines fill in when trend data arrives.
        renderHoldings();
        trendPromise
            .then((trendData) => {
                Object.assign(latestTrendData, trendData || {});
                renderHoldings();
                scheduleAllocationFocusPanelRefresh();
                repaintOpenVerdictSparklines();
            })
            .catch(() => {
                scheduleAllocationFocusPanelRefresh();
            });

        const nextTickers = data.holdings.map(h => h.ticker).sort().join(",");
        if (prevTickers !== nextTickers) {
            latestProjectionData = null;
            projectionLoadPromise = null;
            if (dashboardZone === "analytics") ensureProjectionLoaded();
        }
    } catch (renderErr) {
        console.warn("Portfolio render error (data is current):", renderErr);
    }
}

// Paint cached holdings instantly on first load, before the network responds.
function hydratePortfolioFromCache() {
    if (_hasLoadedOnce) return false;
    const cached = readPortfolioValueCache();
    if (!cached) return false;
    try {
        renderPortfolioValueData(cached.data);
        const subEl = document.getElementById("hud-pop-sync-sub");
        if (subEl) subEl.textContent = "Showing last saved prices — refreshing…";
        return true;
    } catch (err) {
        console.warn("Portfolio cache hydrate failed:", err);
        return false;
    }
}

async function loadPortfolioValue() {
    if (_portfolioValuePromise) return _portfolioValuePromise;
    _portfolioValuePromise = (async () => {
    try {
        const res = await fetch("/api/portfolio/value");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Data arrived — record the sync time and mark success before any rendering
        // that could throw. The catch block only fires for actual network/API failures.
        _lastDashboardSyncText = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        const _wasLoadedOnce = _hasLoadedOnce;
        _hasLoadedOnce = true;

        // Update the HUD popover sync display immediately (before rendering).
        const popUpdatedEl = document.getElementById("hud-pop-updated");
        if (popUpdatedEl) popUpdatedEl.textContent = _lastDashboardSyncText;
        const syncSubEl = document.getElementById("hud-pop-sync-sub");
        if (syncSubEl) syncSubEl.textContent = "Prices, P&L and holdings pulled from market data";
        const syncIconEl = document.getElementById("hud-sync-icon");
        if (syncIconEl) syncIconEl.innerHTML = `<i class="bi bi-check-circle-fill"></i>`;
        const pill = document.getElementById("hud-status-pill");
        if (pill) {
            pill.classList.remove("is-refreshed");
            void pill.offsetWidth;
            pill.classList.add("is-refreshed");
        }

        // Flash on refresh (not on first load)
        if (_wasLoadedOnce) {
            ["total-value", "daily-pnl", "best-performer", "worst-performer", "largest-holding"].forEach(id => {
                flashValue(document.getElementById(id));
            });
        }

        renderPortfolioValueData(data);
        persistPortfolioValueCache(data);

    } catch (err) {
        console.error("Error loading portfolio value:", err);
        if (_hasLoadedOnce) {
            // Refresh failed but we have stale data — keep showing last good sync time
            const subEl = document.getElementById("hud-pop-sync-sub");
            if (subEl) subEl.textContent = "Refresh failed — showing last known prices";
            const iconEl = document.getElementById("hud-sync-icon");
            if (iconEl) iconEl.innerHTML = `<i class="bi bi-exclamation-circle" style="color:var(--bs-warning)"></i>`;
        } else {
            _lastDashboardSyncText = "Sync failed";
            const popUpdatedEl = document.getElementById("hud-pop-updated");
            if (popUpdatedEl) popUpdatedEl.textContent = _lastDashboardSyncText;
            const tbody = document.getElementById("holdings-table");
            if (tbody) {
                tbody.querySelectorAll("tr[data-empty-state]").forEach(r => r.remove());
                const tr = tbody.insertRow();
                tr.dataset.emptyState = "error";
                tr.innerHTML = `<td colspan="9" class="text-center py-4 text-secondary">
                    <i class="bi bi-exclamation-circle me-2"></i>Could not load prices — check your connection and refresh.
                </td>`;
            }
        }
    } finally {
        _portfolioValuePromise = null;
    }
    })();
    return _portfolioValuePromise;
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

    renderAllocationFocusPanel(ticker);

    // Live-update the sector tilt benchmark chart to show this holding's effect
    AnalyticsCharts?.updateSectorTiltForTicker?.(ticker);
}

function allocationImpactForHolding(holding) {
    if (isFiniteNumber(holding?.daily_value_change)) {
        return Number(holding.daily_value_change);
    }

    if (isFiniteNumber(holding?.shares) && isFiniteNumber(holding?.day_change)) {
        return Number(holding.shares) * Number(holding.day_change);
    }

    const dayChangePct = toNumber(holding?.day_change_pct);
    return (100 + dayChangePct) !== 0
        ? toNumber(holding?.current_value) * (dayChangePct / (100 + dayChangePct))
        : 0;
}

// ── Shared range-performance data (per-holding change for 1W…1Y) ─────────────

function holdingsRangeSignature() {
    return latestHoldings
        .filter(h => !h.is_watchlist)
        .map(h => `${h.ticker}:${h.shares}`)
        .sort()
        .join("|");
}

// Cached rows for one range, or null when not loaded / holdings changed.
function rangePerfGroup(rangeKey = dashboardTimeRange) {
    if (rangeKey === TIME_RANGE.TODAY) return null;
    if (!_rangePerf.data || _rangePerf.signature !== holdingsRangeSignature()) return null;
    return _rangePerf.data.ranges?.[rangeKey] || null;
}

// Fetch range performance for all non-day ranges at once. Deduped while in
// flight; a signature mismatch (holdings edited mid-flight) drops the result.
function ensureRangePerformance() {
    const signature = holdingsRangeSignature();
    if (_rangePerf.data && _rangePerf.signature === signature) {
        return Promise.resolve(_rangePerf.data);
    }
    if (_rangePerf.promise && _rangePerf.signature === signature) {
        return _rangePerf.promise;
    }
    _rangePerf.signature = signature;
    _rangePerf.data = null;
    _rangePerf.error = false;
    _rangePerf.promise = fetch("/api/portfolio/range-performance")
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(data => {
            if (_rangePerf.signature === signature) {
                _rangePerf.data = data;
                _rangePerf.promise = null;
            }
            return data;
        })
        .catch(err => {
            if (_rangePerf.signature === signature) {
                _rangePerf.promise = null;
                _rangePerf.error = true;
            }
            throw err;
        });
    return _rangePerf.promise;
}

// Manual "Refresh" should actually refresh range data too, not just quotes —
// invalidate the client cache (a plain signature match would otherwise skip
// refetching indefinitely) and re-render the range-scoped sections once the
// new data lands.
function refreshRangePerformanceIfActive() {
    if (dashboardTimeRange === TIME_RANGE.TODAY) return Promise.resolve();
    _rangePerf.signature = null;
    const requestedRange = dashboardTimeRange;
    return ensureRangePerformance()
        .then(() => {
            if (dashboardTimeRange !== requestedRange) return;
            renderHeroPnl();
            renderSnapshotMovePanel();
            scheduleAllocationFocusPanelRefresh();
        })
        .catch(() => {
            if (dashboardTimeRange === requestedRange) renderSnapshotMovesPending(true);
        });
}

// {pct, value} change for one holding over the selected range.
// Day reads the live quote fields; other ranges read the cached range data.
function holdingRangeChange(holding, rangeKey = dashboardTimeRange) {
    if (normalizeTimeRange(rangeKey) === TIME_RANGE.TODAY) {
        return {
            pct: isFiniteNumber(holding?.day_change_pct) ? Number(holding.day_change_pct) : null,
            value: allocationImpactForHolding(holding),
        };
    }
    const row = rangePerfGroup(rangeKey)?.holdings?.[holding?.ticker];
    return {
        pct: isFiniteNumber(row?.change_pct) ? Number(row.change_pct) : null,
        value: isFiniteNumber(row?.value_change) ? Number(row.value_change) : null,
    };
}

function validateAllocationHoldingMath(holding, impactToday) {
    const warnings = [];
    const hasSharesMove = isFiniteNumber(holding?.shares) && isFiniteNumber(holding?.day_change);
    if (hasSharesMove && isFiniteNumber(holding?.daily_value_change)) {
        const expectedImpact = Number(holding.shares) * Number(holding.day_change);
        if (Math.abs(expectedImpact - Number(holding.daily_value_change)) > 0.05) {
            warnings.push(`${holding.ticker}: daily_value_change does not match shares * day_change`);
        }
    }

    if (!Number.isFinite(impactToday)) {
        warnings.push(`${holding?.ticker || "Holding"}: impactToday is not finite`);
    }

    return warnings;
}

function validateAllocationPortfolioMath(portfolioImpactToday, grossPortfolioMove, holdingsCount) {
    const warnings = [];
    if (!Number.isFinite(portfolioImpactToday) || !Number.isFinite(grossPortfolioMove)) {
        warnings.push("Portfolio impact totals are not finite");
    }

    const roundingTolerance = Math.max(0.10, holdingsCount * 0.01);
    if (latestPortfolioDailyChange !== null
        && Math.abs(portfolioImpactToday - latestPortfolioDailyChange) > roundingTolerance) {
        warnings.push("Sum of holding impacts does not match total_daily_change");
    }

    return warnings;
}

function allocationTooltipMetrics(ticker, value) {
    const portfolioHoldings = latestHoldings.filter(h => !h.is_watchlist);
    const holding = portfolioHoldings.find(h => h.ticker === ticker);
    const holdingsCount = portfolioHoldings.length;
    if (!holding || !holdingsCount) return null;

    const rank = sortedByAllocation(portfolioHoldings)
        .findIndex(h => h.ticker === ticker) + 1;
    const equalWeightValue = allocationTotal / holdingsCount;
    const equalWeightDrift = toNumber(value) - equalWeightValue;
    // Day keeps the exact live-quote math (and its validation); longer ranges
    // read the shared range data, where a holding without history counts as 0.
    const isDayRange = dashboardTimeRange === TIME_RANGE.TODAY;
    const impactOf = isDayRange
        ? allocationImpactForHolding
        : (h) => {
            const rangeValue = holdingRangeChange(h).value;
            return Number.isFinite(rangeValue) ? rangeValue : 0;
        };
    const impactToday = impactOf(holding);
    const portfolioImpactToday = portfolioHoldings.reduce(
        (sum, h) => sum + impactOf(h),
        0
    );
    const grossPortfolioMove = portfolioHoldings.reduce(
        (sum, h) => sum + Math.abs(impactOf(h)),
        0
    );
    const mathWarnings = isDayRange
        ? [
            ...validateAllocationHoldingMath(holding, impactToday),
            ...validateAllocationPortfolioMath(portfolioImpactToday, grossPortfolioMove, holdingsCount),
        ]
        : [];
    if (mathWarnings.length) {
        console.warn("Allocation tooltip math validation failed", {
            ticker,
            mathWarnings,
            holding,
            impactToday,
            portfolioImpactToday,
            latestPortfolioDailyChange,
            grossPortfolioMove,
        });
    }

    const shareOfMove = grossPortfolioMove > 0.01 && !mathWarnings.length
        ? Math.min(100, (Math.abs(impactToday) / grossPortfolioMove) * 100)
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
        portfolioImpactToday,
        grossPortfolioMove,
        mathWarnings,
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
    const isDayRange = dashboardTimeRange === TIME_RANGE.TODAY;
    const rangePhrase = timeRangeConfig().phrase;
    const todayNote = metrics.shareOfMove !== null
        ? (isDayRange
            ? `${metrics.shareOfMove.toFixed(0)}% of today's absolute move`
            : `${metrics.shareOfMove.toFixed(0)}% of the absolute move ${rangePhrase}`)
        : (isDayRange
            ? "Its dollar effect on today's portfolio move"
            : `Its dollar effect on the portfolio ${rangePhrase}`);

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
            ${allocationInsightRow(isDayRange ? "Did it drive today?" : `Did it drive the ${timeRangeConfig().label} move?`, formatSignedCurrency(metrics.impactToday), todayNote, impactTone)}
            ${allocationInsightRow("What if it drops 10%?", formatSignedCurrency(metrics.stressValue), `${Math.abs(metrics.stressPct).toFixed(1)}% hit to the whole portfolio`, "is-negative")}
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
    const grads = allocGradients(chart, baseColors);
    if (grads) {
        dataset.backgroundColor = baseColors.map((_, index) =>
            activeIndex >= 0 && index !== activeIndex ? grads.dim[index] : grads.base[index]
        );
        chart.$allocFillApplied = grads; // mark so the fill plugin won't redundantly reapply
    } else {
        // Pre-layout fallback: flat tints, upgraded to gradients once geometry exists.
        dataset.backgroundColor = baseColors.map((color, index) =>
            activeIndex >= 0 && index !== activeIndex ? withAlpha(color, 0.80) : withAlpha(color, 0.96)
        );
    }
}

function allocationFocusDefaultTicker(sorted = null) {
    const holdings = sorted || sortedByAllocation(latestHoldings.filter(h => !h.is_watchlist));
    return holdings[0]?.ticker || null;
}

function allocationFocusTicker(ticker = null, sorted = null) {
    return ticker || selectedAllocationTicker || allocationFocusDefaultTicker(sorted);
}

function allocationFocusShortText(text, max = 132) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    if (clean.length <= max) return clean;
    const clipped = clean.slice(0, max - 1);
    const boundary = Math.max(clipped.lastIndexOf("."), clipped.lastIndexOf(";"), clipped.lastIndexOf(","));
    return `${(boundary > 60 ? clipped.slice(0, boundary) : clipped).trim()}...`;
}

function allocationFocusWhatItIs(holding, intel) {
    const label = intel?.coverage_label || intel?.theme || holding?.name || holding?.ticker || "Holding";
    const strategy = intel?.strategy || intel?.coverage_description || "";
    if (strategy) return allocationFocusShortText(strategy, 150);
    if (holding?.name && holding.name !== holding.ticker) {
        const name = String(holding.name).replace(/\.+$/, "");
        return `${holding.ticker} represents ${name}. This card shows how much of your book depends on it right now.`;
    }
    return `${label} is one slice of your portfolio. Hover another segment to swap this read instantly.`;
}

function allocationFocusMoveCopy(holding, metrics, explanation) {
    // Move explainers are day-scoped; longer ranges get a deterministic
    // period read from the shared range data instead.
    if (dashboardTimeRange !== TIME_RANGE.TODAY) {
        const config = timeRangeConfig();
        const rangeChange = holdingRangeChange(holding);
        if (!isFiniteNumber(rangeChange.pct)) {
            return `Not enough price history to read this holding ${config.phrase} yet.`;
        }
        const direction = rangeChange.pct >= 0 ? "up" : "down";
        const impact = isFiniteNumber(rangeChange.value)
            ? `, ${formatSignedCurrency(rangeChange.value)} for your position`
            : "";
        return `${holding.ticker} is ${direction} ${Math.abs(rangeChange.pct).toFixed(2)}% ${config.phrase}${impact}.`;
    }

    if (explanation?.explanation_text) {
        return allocationFocusShortText(explanation.explanation_text, 158);
    }
    const drivers = (explanation?.drivers || [])
        .map(d => d.description)
        .filter(Boolean);
    if (drivers.length) return allocationFocusShortText(drivers.slice(0, 2).join(" "), 158);

    if (!isFiniteNumber(holding?.day_change_pct)) {
        return "Today’s move is not available yet. Once prices refresh, this will explain the main driver and portfolio impact.";
    }

    const change = Number(holding.day_change_pct);
    const pct = `${Math.abs(change).toFixed(2)}%`;
    const direction = change >= 0 ? "up" : "down";
    const impact = formatSignedCurrency(metrics?.impactToday || 0);
    const share = metrics?.shareOfMove !== null && metrics?.shareOfMove !== undefined
        ? `, about ${metrics.shareOfMove.toFixed(0)}% of gross portfolio movement`
        : "";
    return `${holding.ticker} is ${direction} ${pct} today, contributing ${impact}${share}.`;
}

function allocationFocusVerdictCopy(verdict, ticker) {
    if (!verdict) {
        return {
            empty: true,
            html: `<div class="alloc-focus-verdict is-empty">
                <p class="alloc-focus-verdict-copy mb-0">
                    Run <strong>Holding Intel</strong> to add FolioSense verdicts here.
                </p>
            </div>`,
        };
    }

    const safeVerdict = _sanitizeVerdict(verdict) || verdict;
    const action = safeVerdict.action || "needs-data";
    const label = safeVerdict.label || "Needs Data";
    const icon = VERDICT_ICONS[action] || "bi-question-circle";
    const confidence = Math.round(Number(safeVerdict.confidence) || 0);
    const ai = safeVerdict.ai_enhancement || {};
    const summary = _isAiVerdictActive(safeVerdict)
        ? _synthPlainSummary(safeVerdict, ai, ticker)
        : _localSynthPlainSummary(safeVerdict, ticker);
    const fallback = (safeVerdict.reasons || [])[0] || safeVerdict.quip || FOLIO_SENSE_VERDICT_COPY.unavailable;
    const copy = allocationFocusShortText(summary || fallback, 138);
    const color = _verdictColor(action);

    return {
        empty: false,
        html: `<div class="alloc-focus-verdict" data-action="${escapeHtml(action)}" style="--alloc-verdict-color:${color}">
            <span class="alloc-focus-verdict-icon"><i class="bi ${escapeHtml(icon)}" aria-hidden="true"></i></span>
            <div class="alloc-focus-verdict-body">
                <div class="alloc-focus-verdict-line">
                    <span class="alloc-focus-verdict-label">${escapeHtml(label)}</span>
                    <span class="alloc-focus-confidence">${confidence}% confidence</span>
                </div>
                <p class="alloc-focus-verdict-copy">${escapeHtml(copy)}</p>
            </div>
        </div>`,
    };
}

function allocationFocusTrendMeta(ticker, holding, verdict) {
    const apiPoints = verdict?.timing?.sparkline_30d;
    if (Array.isArray(apiPoints) && apiPoints.length >= 2) {
        const first = Number(apiPoints[0]);
        const last = Number(apiPoints[apiPoints.length - 1]);
        const delta = last - first;
        return {
            label: "Signal path",
            value: formatSignalPct(delta),
            note: "30D signal",
            tone: signalTone(delta),
        };
    }

    const history = latestTrendData[ticker] || [];
    const closes = history.map(point => Number(point.close)).filter(Number.isFinite);
    if (closes.length >= 2 && closes[0] !== 0) {
        const delta = ((closes[closes.length - 1] - closes[0]) / closes[0]) * 100;
        return {
            label: "Price path",
            value: formatSignalPct(delta),
            note: "1M trend",
            tone: signalTone(delta),
        };
    }

    return {
        label: "Price path",
        value: isFiniteNumber(holding?.current_price) ? formatCurrency(holding.current_price) : "—",
        note: "Trend loading",
        tone: "neutral",
    };
}

function paintAllocationFocusSparkline(ticker) {
    const canvas = document.querySelector(`canvas.allocation-focus-sparkline[data-ticker="${CSS.escape(ticker)}"]`);
    if (!canvas) return;
    const verdict = cachedVerdicts[ticker];
    const apiPoints = verdict?.timing?.sparkline_30d;
    if (Array.isArray(apiPoints) && apiPoints.length >= 2) {
        _drawPctSparkline(canvas, apiPoints);
        return;
    }
    drawTrend(canvas, latestTrendData[ticker] || []);
}

function scheduleAllocationFocusPanelRefresh() {
    if (allocationFocusRefreshFrame) return;
    allocationFocusRefreshFrame = requestAnimationFrame(() => {
        allocationFocusRefreshFrame = null;
        renderAllocationFocusPanel(null, null, { force: true });
    });
}

function renderAllocationFocusPanel(ticker = null, sorted = null, options = {}) {
    const panel = document.getElementById("allocation-focus-panel");
    if (!panel) return;

    const activeTicker = allocationFocusTicker(ticker, sorted);
    if (activeTicker && !options.force && allocationFocusPanelTicker === activeTicker) return;
    allocationFocusPanelTicker = activeTicker;
    const holding = latestHoldings.find(h => h.ticker === activeTicker && !h.is_watchlist);
    if (!activeTicker || !holding) {
        panel.innerHTML = `<div class="allocation-focus-empty">
            <i class="bi bi-pie-chart-fill"></i>
            <span>Add holdings to unlock allocation insight.</span>
        </div>`;
        return;
    }

    const sortedHoldings = sorted || sortedByAllocation(latestHoldings.filter(h => !h.is_watchlist));
    const colorIndex = Math.max(0, sortedHoldings.findIndex(h => h.ticker === activeTicker));
    const color = allocColor(colorIndex);
    const metrics = allocationTooltipMetrics(activeTicker, holding.current_value);
    const intel = cachedIntelligence[activeTicker];
    const explanation = cachedExplanations[activeTicker];
    const verdict = cachedVerdicts[activeTicker];
    const safeVerdict = verdict ? (_sanitizeVerdict(verdict) || verdict) : null;
    const verdictHtml = allocationFocusVerdictCopy(safeVerdict, activeTicker).html;
    const trend = allocationFocusTrendMeta(activeTicker, holding, safeVerdict);
    const rangeChange = holdingRangeChange(holding);
    const dayTone = isFiniteNumber(rangeChange.pct)
        ? colorClass(Number(rangeChange.pct))
        : "text-secondary";
    const dayText = isFiniteNumber(rangeChange.pct)
        ? formatPct(rangeChange.pct)
        : "—";
    const returnPct = isFiniteNumber(holding.unrealized_gain_pct)
        ? Number(holding.unrealized_gain_pct)
        : (isFiniteNumber(holding.total_return_pct) ? Number(holding.total_return_pct) : null);
    const returnTone = returnPct === null ? "text-secondary" : colorClass(returnPct);
    const returnText = returnPct === null ? "—" : formatPct(returnPct);
    const stress = metrics ? formatSignedCurrency(metrics.stressValue) : "—";
    const rank = metrics?.rank ? `#${metrics.rank} of ${metrics.holdingsCount}` : "—";
    const concentrationNote = metrics
        ? (metrics.equalWeightDrift >= 0
            ? `${formatCompact(Math.abs(metrics.equalWeightDrift))} over equal-weight`
            : `${formatCompact(Math.abs(metrics.equalWeightDrift))} under equal-weight`)
        : "Allocation read";

    panel.innerHTML = `<div class="alloc-focus-inner" data-ticker="${escapeHtml(activeTicker)}">
        <div class="alloc-focus-head">
            <div>
                <span class="alloc-focus-kicker"><i class="bi bi-crosshair" aria-hidden="true"></i> Focus holding</span>
                <div class="alloc-focus-title-row">
                    <span class="alloc-focus-dot" style="background:${color};color:${color}"></span>
                    <span class="alloc-focus-ticker">${escapeHtml(activeTicker)}</span>
                    <span class="alloc-focus-name">${escapeHtml(holding.name || intel?.coverage_label || "")}</span>
                </div>
                <p class="alloc-focus-sub">${escapeHtml(formatCurrency(holding.current_value))} · ${escapeHtml(formatAllocationPct(holding.allocation_pct))} of portfolio · ${escapeHtml(concentrationNote)}</p>
            </div>
            <div class="alloc-focus-day">
                <span>${escapeHtml(timeRangeConfig().label)}</span>
                <strong class="${dayTone}">${escapeHtml(dayText)}</strong>
            </div>
        </div>

        <div class="alloc-focus-metrics">
            <div class="alloc-focus-metric">
                <span>Size rank</span>
                <strong>${escapeHtml(rank)}</strong>
            </div>
            <div class="alloc-focus-metric">
                <span>Your return</span>
                <strong class="${returnTone}">${escapeHtml(returnText)}</strong>
            </div>
            <div class="alloc-focus-metric">
                <span>If down 10%</span>
                <strong class="text-danger">${escapeHtml(stress)}</strong>
            </div>
        </div>

        <div class="alloc-focus-spark-card">
            <div>
                <span class="alloc-focus-spark-label">${escapeHtml(trend.label)}</span>
                <canvas class="allocation-focus-sparkline" data-ticker="${escapeHtml(activeTicker)}" width="360" height="58"
                    aria-label="${escapeHtml(activeTicker)} ${escapeHtml(trend.note)}"></canvas>
            </div>
            <div class="alloc-focus-spark-meta">
                <strong class="${trend.tone === "positive" ? "text-success" : trend.tone === "negative" ? "text-danger" : "text-secondary"}">${escapeHtml(trend.value)}</strong>
                <span>${escapeHtml(trend.note)}</span>
            </div>
        </div>

        <div class="alloc-focus-section">
            <div class="alloc-focus-section-label"><i class="bi bi-info-circle-fill" aria-hidden="true"></i> What it is</div>
            <p class="alloc-focus-copy">${escapeHtml(allocationFocusWhatItIs(holding, intel))}</p>
        </div>

        <div class="alloc-focus-section">
            <div class="alloc-focus-section-label"><i class="bi bi-lightning-charge-fill" aria-hidden="true"></i> Why it moved</div>
            <p class="alloc-focus-copy">${escapeHtml(allocationFocusMoveCopy(holding, metrics, explanation))}</p>
        </div>

        ${verdictHtml}
    </div>`;

    requestAnimationFrame(() => paintAllocationFocusSparkline(activeTicker));
}

function renderAllocation() {
    const sorted = sortedByAllocation(latestHoldings.filter(h => !h.is_watchlist));

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
        row.addEventListener("mouseenter", () => renderAllocationFocusPanel(h.ticker, sorted));
        row.addEventListener("mouseleave", () => renderAllocationFocusPanel(null, sorted));
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
        renderAllocationFocusPanel(null, sorted, { force: true });
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
	                        const nextLabel = allocationChart.data.labels[idx];
	                        if (hoveredCenterLabel !== nextLabel) {
	                            renderAllocationFocusPanel(nextLabel);
	                        }
	                        hoveredCenterLabel = nextLabel;
	                        const val = toNumber(allocationChart.data.datasets[0].data[idx]);
	                        const pct = allocationTotal > 0 ? (val / allocationTotal * 100).toFixed(1) : "0.0";
	                        hoveredCenterValue = formatCurrency(val);
	                        hoveredCenterPct = `${pct}%`;
	                        setAllocationFocus(allocationChart, idx);
	                    } else {
	                        hoveredCenterLabel = null;
	                        hoveredCenterValue = null;
	                        hoveredCenterPct = null;
	                        renderAllocationFocusPanel(null);
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
            plugins: [allocFillPlugin, segmentGlowPlugin, centerHaloPlugin, centerTotalPlugin],
        });
        // If we booted into a non-Overview zone, keep the halo paused until shown.
        if (dashboardZone !== "overview") allocationChart.$haloPause?.();
        renderAllocationFocusPanel(null, sorted, { force: true });
    }
}

const SNAPSHOT_SECTOR_THEMES = [
    { match: /tech/i,                        color: "#2F6FB0", icon: "bi-cpu-fill",
      blurb: "Think software, semiconductors, cloud, hardware, and IT services — the folks who quietly run the world and never let you forget it." },
    { match: /health/i,                      color: "#B23A55", icon: "bi-heart-pulse-fill",
      blurb: "Likely pharma, biotech, medical devices, hospitals, and health insurers — the people keeping you alive and the bill alive too." },
    { match: /financ/i,                      color: "#4B49A0", icon: "bi-bank",
      blurb: "Probably banks, insurers, asset managers, payment networks, and exchanges — they make money making money. Cute, right?" },
    { match: /energy/i,                      color: "#C07628", icon: "bi-lightning-charge-fill",
      blurb: "Mostly oil & gas, drillers, refiners, pipelines, and oilfield services — the stuff that powers your portfolio and your road trips." },
    { match: /industri/i,                    color: "#2A8C84", icon: "bi-gear-wide-connected",
      blurb: "Machinery, airlines, railroads, logistics, and construction — the unglamorous gears that keep the economy from seizing up." },
    { match: /consumer disc|discretionary/i, color: "#BD5232", icon: "bi-bag-fill",
      blurb: "Retail, autos, restaurants, travel, and luxury — basically everything you buy when you're feeling optimistic (or impulsive)." },
    { match: /consumer stap|staples/i,       color: "#3C8C58", icon: "bi-cart-fill",
      blurb: "Food, beverages, household goods, and groceries — the stuff people buy in a boom, a bust, and a zombie apocalypse." },
    { match: /real estate|reit/i,            color: "#8A6B4A", icon: "bi-building",
      blurb: "REITs, property landlords, and developers — they own the building you're standing in and rent it back to you." },
    { match: /utilit/i,                      color: "#B58A1E", icon: "bi-plug-fill",
      blurb: "Electric, gas, and water utilities — boring, reliable, and the reason your lights turn on. The dependable friend of the market." },
    { match: /material/i,                    color: "#8A4FA8", icon: "bi-box-seam",
      blurb: "Chemicals, metals & mining, packaging, and paper — the raw ingredients everything else is literally made out of." },
    { match: /communi/i,                     color: "#3681A6", icon: "bi-broadcast",
      blurb: "Telecom, media, streaming, social, gaming, and advertising — where your attention goes to get sold to the highest bidder." },
    { match: /aero|defense|defence/i,        color: "#1F8A72", icon: "bi-airplane-fill",
      blurb: "Aircraft makers and defense contractors — they build the things that fly, and occasionally the things that go boom." },
];
const SNAPSHOT_SECTOR_FALLBACK = { color: "#5C5C66", icon: "bi-diagram-3",
    blurb: "The mystery box. Could be anything we haven't sorted into a tidy sector yet — odds, ends, and the occasional surprise. Industry-level detail is on the way." };

function snapshotSectorTheme(name) {
    const n = String(name || "").toLowerCase();
    return SNAPSHOT_SECTOR_THEMES.find(t => t.match.test(n)) || SNAPSHOT_SECTOR_FALLBACK;
}

function snapshotActiveHoldings() {
    return latestHoldings
        .filter(h => !h.is_watchlist && toNumber(h.current_value) > 0)
        .sort((a, b) => toNumber(b.allocation_pct) - toNumber(a.allocation_pct));
}

function snapshotMoveRows(active) {
    return active
        .map(h => {
            const change = holdingRangeChange(h);
            return {
                ticker: h.ticker,
                name: h.name || h.ticker,
                allocation_pct: toNumber(h.allocation_pct),
                change_pct: change.pct,
                impact: change.value,
            };
        })
        .filter(r => Number.isFinite(r.impact))
        .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact));
}

function portfolioSnapshotTone(value) {
    if (!Number.isFinite(value) || Math.abs(value) < 0.005) return "neutral";
    return value > 0 ? "positive" : "negative";
}

function renderSnapshotSectorEmpty(message, icon = "bi-hourglass-split") {
    const strip = document.getElementById("snapshot-sector-strip");
    const list = document.getElementById("snapshot-sector-list");
    if (strip) {
        strip.className = "snapshot-sector-strip is-loading";
        strip.innerHTML = "";
        strip.setAttribute("aria-label", message);
    }
    if (list) {
        list.innerHTML = `<span class="snapshot-loading-pill">
            <i class="bi ${icon}" aria-hidden="true"></i>
            ${escapeHtml(message)}
        </span>`;
    }
}

async function ensurePortfolioSnapshotExposure() {
    if (cachedPortfolioExposure?.sector_exposure?.length || portfolioSnapshotExposurePromise) return;
    portfolioSnapshotExposurePromise = fetch("/api/ai/portfolio-exposure")
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(data => {
            cachedPortfolioExposure = data || cachedPortfolioExposure;
            renderPortfolioSnapshot();
            return data;
        })
        .catch(err => {
            console.warn("Portfolio snapshot exposure failed:", err);
            renderSnapshotSectorEmpty("Sector mix unavailable", "bi-exclamation-circle");
        })
        .finally(() => {
            portfolioSnapshotExposurePromise = null;
        });
}

function renderSnapshotSectors(active) {
    const strip = document.getElementById("snapshot-sector-strip");
    const list = document.getElementById("snapshot-sector-list");
    if (!strip || !list) return;

    const sectors = (cachedPortfolioExposure?.sector_exposure || [])
        .filter(s => toNumber(s.weight_pct) > 0)
        .sort((a, b) => toNumber(b.weight_pct) - toNumber(a.weight_pct))
        .slice(0, 7);

    if (!active.length) {
        renderSnapshotSectorEmpty("Add holdings to see sector mix", "bi-plus-circle");
        return;
    }

    if (!sectors.length) {
        renderSnapshotSectorEmpty("Loading sector mix");
        ensurePortfolioSnapshotExposure();
        return;
    }

    const top = sectors[0];
    const aria = sectors
        .slice(0, 4)
        .map(s => `${s.name} ${toNumber(s.weight_pct).toFixed(1)}%`)
        .join(", ");

    strip.className = "snapshot-sector-strip";
    strip.setAttribute("aria-label", `Portfolio sector exposure: ${aria}`);
    strip.innerHTML = sectors.map((s, index) => {
        const theme = snapshotSectorTheme(s.name);
        const pct = Math.max(1.5, toNumber(s.weight_pct));
        const rawPct = toNumber(s.weight_pct);
        const showLabel = rawPct >= 8;
        return `<span class="snapshot-sector-seg"
            style="--snapshot-color:${theme.color};--snapshot-width:${pct}%;--snapshot-delay:${index * 35}ms"
            title="${escapeHtml(s.name)} ${rawPct.toFixed(1)}%">${
            showLabel ? `<span class="snapshot-seg-label" aria-hidden="true">${rawPct.toFixed(0)}%</span>` : ""
        }</span>`;
    }).join("");

    const maxPct = toNumber(sectors[0]?.weight_pct) || 100;
    list.innerHTML = sectors.map((s, index) => {
        const theme = snapshotSectorTheme(s.name);
        const rawPct = toNumber(s.weight_pct);
        const pct = rawPct.toFixed(1);
        const fill = Math.min(100, (rawPct / maxPct) * 100).toFixed(1);
        const isOther = !SNAPSHOT_SECTOR_THEMES.some(t => t.match.test(String(s.name || "").toLowerCase()));
        const tipTitle = `${s.name} · ${pct}%`;
        const tipHint = isOther
            ? "Industry-level breakdown coming soon"
            : "Industries this sector may include";
        return `<div class="snapshot-sector-item tip-trigger" tabindex="0"
            style="--snapshot-color:${theme.color};--snapshot-delay:${index * 35}ms"
            data-tip-title="${escapeHtml(tipTitle)}"
            data-tip-body="${escapeHtml(theme.blurb || "")}"
            data-tip-hint="${escapeHtml(tipHint)}"
            data-tip-icon="${escapeHtml(theme.icon)}">
            <span class="snapshot-sector-dot" aria-hidden="true"></span>
            <span class="snapshot-sector-name">${escapeHtml(s.name)}</span>
            <div class="snapshot-sector-track" aria-hidden="true">
                <div class="snapshot-sector-fill" style="--snapshot-fill:${fill}%"></div>
            </div>
            <span class="snapshot-sector-pct">${pct}%</span>
        </div>`;
    }).join("") + (top ? `<div class="snapshot-sector-note"
        style="--snapshot-tilt-color:${snapshotSectorTheme(top.name).color}">
        <i class="bi bi-crosshair2" aria-hidden="true"></i>
        Biggest tilt&thinsp;·&thinsp;<strong>${escapeHtml(top.name)}</strong>
    </div>` : "");
}

function snapshotAiRead(rows, net, pct) {
    const gainCount = rows.filter(r => r.impact > 0).length;
    const lossCount = rows.filter(r => r.impact < 0).length;
    const top = rows[0];
    const direction = Math.abs(net) < 1 ? "mostly sideways" : net > 0 ? "more up" : "more down";
    const breadth = gainCount === lossCount
        ? "breadth is balanced"
        : `${gainCount} gainers vs ${lossCount} losers`;
    const mover = top
        ? `${top.ticker} is the largest ${top.impact >= 0 ? "push" : "drag"}`
        : "moves are muted";
    const pctCopy = Number.isFinite(pct) ? ` (${formatPct(pct)})` : "";
    const phrase = timeRangeConfig().phrase;
    return `Likely to go ${direction} near-term: net ${phrase} is ${formatSignedCurrency(net)}${pctCopy}, ${breadth}, and ${mover}.`;
}

function snapshotLocalCatalysts(rows, sectors) {
    const catalysts = [];
    const gain = rows.find(r => r.impact > 0);
    const loss = rows.find(r => r.impact < 0);
    const topSector = sectors?.[0];
    const net = rows.reduce((sum, r) => sum + r.impact, 0);
    const phrase = timeRangeConfig().phrase;

    if (gain) {
        catalysts.push({
            icon: "bi-arrow-up-right",
            tone: "positive",
            text: `${gain.ticker} led gains ${phrase} at ${formatOptionalPct(gain.change_pct)} (${formatSignedCurrency(gain.impact)})`,
        });
    }
    if (loss) {
        catalysts.push({
            icon: "bi-arrow-down-right",
            tone: "negative",
            text: `${loss.ticker} was the main drag at ${formatOptionalPct(loss.change_pct)} (${formatSignedCurrency(loss.impact)})`,
        });
    }
    if (topSector) {
        catalysts.push({
            icon: snapshotSectorTheme(topSector.name).icon,
            tone: "neutral",
            text: `${topSector.name} is the largest exposure at ${toNumber(topSector.weight_pct).toFixed(1)}%`,
        });
    }
    if (Math.abs(net) < 1 && rows.length) {
        catalysts.push({
            icon: "bi-arrows-collapse",
            tone: "neutral",
            text: "Gains and losses are nearly offsetting in dollar terms",
        });
    }

    return catalysts.slice(0, 3);
}

function renderSnapshotIntel(rows, net, pct) {
    const wrap = document.getElementById("snapshot-intel-lines");
    const mode = document.getElementById("snapshot-mode-pill");
    if (!wrap) return;

    const local = isLocalIntelligenceMode();
    if (mode) {
        mode.className = `snapshot-mode-pill ${local ? "is-local" : "is-ai"}`;
        mode.innerHTML = local
            ? `<i class="bi bi-cpu-fill" aria-hidden="true"></i> Local`
            : `<i class="bi bi-stars" aria-hidden="true"></i> AI`;
    }

    const sectors = (cachedPortfolioExposure?.sector_exposure || [])
        .filter(s => toNumber(s.weight_pct) > 0)
        .sort((a, b) => toNumber(b.weight_pct) - toNumber(a.weight_pct));

    if (!rows.length) {
        wrap.innerHTML = "";
        return;
    }

    if (!local) {
        wrap.innerHTML = `<div class="snapshot-ai-line">
            <i class="bi bi-stars" aria-hidden="true"></i>
            <span>${escapeHtml(snapshotAiRead(rows, net, pct))}</span>
        </div>`;
        return;
    }

    const catalysts = snapshotLocalCatalysts(rows, sectors);
    wrap.innerHTML = catalysts.map(item => `
        <div class="snapshot-catalyst is-${item.tone}">
            <i class="bi ${item.icon}" aria-hidden="true"></i>
            <span>${escapeHtml(item.text)}</span>
        </div>`).join("");
}

// Loading / error pill scoped to the move panel only — sector map, briefing,
// and the rest of the dashboard stay untouched while range data streams in.
function renderSnapshotMovesPending(failed = false) {
    const summary = document.getElementById("snapshot-move-summary");
    const stack = document.getElementById("snapshot-move-stack");
    const list = document.getElementById("snapshot-mover-list");
    const intel = document.getElementById("snapshot-intel-lines");
    if (!summary) return;
    summary.innerHTML = `<span class="snapshot-loading-pill">
        <i class="bi ${failed ? "bi-exclamation-circle" : "bi-hourglass-split"}" aria-hidden="true"></i>
        ${failed ? "Range data unavailable — refresh to retry" : `Loading ${escapeHtml(timeRangeConfig().label)} moves`}
    </span>`;
    if (stack) stack.innerHTML = "";
    if (list) list.innerHTML = "";
    if (intel) intel.innerHTML = "";
}

function renderSnapshotMoveTitle() {
    const title = document.getElementById("snapshot-move-title");
    if (title) title.textContent = timeRangeConfig().impactTitle;
}

function renderSnapshotMoves(active) {
    const summary = document.getElementById("snapshot-move-summary");
    const stack = document.getElementById("snapshot-move-stack");
    const list = document.getElementById("snapshot-mover-list");
    if (!summary || !stack || !list) return;

    const config = timeRangeConfig();
    renderSnapshotMoveTitle();

    const isDay = dashboardTimeRange === TIME_RANGE.TODAY;
    const group = isDay ? null : rangePerfGroup();
    if (!isDay && !group && active.length) {
        // Range data not cached yet — show a panel-scoped pill and re-render
        // when the (single, all-ranges) fetch lands, unless the user has
        // already switched again. Always attempts the fetch (even after a
        // prior failure) so switching ranges again after an outage acts as
        // an implicit retry instead of leaving the pill stuck forever.
        const requestedRange = dashboardTimeRange;
        renderSnapshotMovesPending(_rangePerf.error);
        ensureRangePerformance()
            .then(() => {
                if (dashboardTimeRange !== requestedRange) return;
                renderHeroPnl();
                renderSnapshotMovePanel();
                scheduleAllocationFocusPanelRefresh();
            })
            .catch(() => {
                if (dashboardTimeRange === requestedRange) renderSnapshotMovesPending(true);
            });
        return;
    }

    const rows = snapshotMoveRows(active);
    const gains = rows.filter(r => r.impact > 0);
    const losses = rows.filter(r => r.impact < 0);
    const grossGain = gains.reduce((sum, r) => sum + r.impact, 0);
    const grossLoss = losses.reduce((sum, r) => sum + Math.abs(r.impact), 0);
    const net = rows.reduce((sum, r) => sum + r.impact, 0);
    const dayPct = latestPortfolioValueData && isFiniteNumber(latestPortfolioValueData.total_daily_change_pct)
        ? Number(latestPortfolioValueData.total_daily_change_pct)
        : null;
    const pct = isDay
        ? dayPct
        : (isFiniteNumber(group?.net_change_pct) ? Number(group.net_change_pct) : null);
    const totalAbs = grossGain + grossLoss;
    const gainShare = totalAbs > 0 ? (grossGain / totalAbs) * 100 : 50;
    const lossShare = totalAbs > 0 ? (grossLoss / totalAbs) * 100 : 50;
    const tone = portfolioSnapshotTone(net);

    if (!active.length) {
        summary.innerHTML = `<div class="snapshot-empty-state">No active holdings yet.</div>`;
        stack.innerHTML = "";
        list.innerHTML = "";
        renderSnapshotIntel([], 0, pct);
        return;
    }

    if (!rows.length && !isDay) {
        // Range data arrived but had no usable history (e.g. brand-new tickers)
        renderSnapshotMovesPending(true);
        return;
    }

    summary.innerHTML = `<div class="snapshot-net is-${tone}">
        <span class="snapshot-net-label">${escapeHtml(config.pnlLabel)}</span>
        <strong>${formatSignedCurrency(net)}</strong>
        ${pct !== null ? `<span class="snapshot-net-pct">${formatPct(pct)}</span>` : ""}
    </div>
    <div class="snapshot-gain-loss">
        <span class="is-positive">
            <i class="bi bi-arrow-up-right" aria-hidden="true"></i>
            ${formatSignedCurrency(grossGain)}
            <em>${gains.length}W</em>
        </span>
        <span class="is-negative">
            <i class="bi bi-arrow-down-right" aria-hidden="true"></i>
            -${formatCurrency(grossLoss)}
            <em>${losses.length}L</em>
        </span>
    </div>`;

    stack.innerHTML = `<div class="snapshot-stack-track">
        <span class="snapshot-stack-seg is-gain" style="width:${gainShare}%"></span>
        <span class="snapshot-stack-seg is-loss" style="width:${lossShare}%"></span>
    </div>
    <div class="snapshot-stack-labels">
        <span>${gains.length} gain${gains.length === 1 ? "" : "s"}</span>
        <span class="snapshot-stack-ratio">${Math.round(gainShare)}&#x202F;/&#x202F;${Math.round(lossShare)}</span>
        <span>${losses.length} loss${losses.length === 1 ? "" : "es"}</span>
    </div>`;

    const maxGainImpact = Math.max(...gains.map(r => r.impact), 0.01);
    const maxLossImpact = Math.max(...losses.map(r => Math.abs(r.impact)), 0.01);
    list.innerHTML = rows.slice(0, 5).map((r, index) => {
        const rowTone = portfolioSnapshotTone(r.impact);
        const isPos = rowTone === "positive";
        const fillW = isPos
            ? Math.max(4, r.impact / maxGainImpact * 100)
            : Math.max(4, Math.abs(r.impact) / maxLossImpact * 100);
        const leftFill = !isPos ? `<span class="snapshot-mover-fill" style="width:${fillW}%"></span>` : "";
        const rightFill = isPos ? `<span class="snapshot-mover-fill" style="width:${fillW}%"></span>` : "";
        return `<div class="snapshot-mover-row is-${rowTone}" style="--snapshot-delay:${index * 35}ms">
            <span class="snapshot-mover-ticker">${escapeHtml(r.ticker)}</span>
            <span class="snapshot-mover-pct">${formatOptionalPct(r.change_pct)}</span>
            <span class="snapshot-mover-track" aria-hidden="true">
                <span class="snapshot-mover-left">${leftFill}</span>
                <span class="snapshot-mover-axis"></span>
                <span class="snapshot-mover-right">${rightFill}</span>
            </span>
            <span class="snapshot-mover-impact">${formatSignedCurrency(r.impact)}</span>
        </div>`;
    }).join("");

    renderSnapshotIntel(rows, net, pct);
}

// Move panel only — used on range switches so the sector map (which is
// range-independent) doesn't re-render and replay its entry animations.
function renderSnapshotMovePanel() {
    if (!document.getElementById("portfolio-snapshot-card")) return;
    renderSnapshotMoves(snapshotActiveHoldings());
}

function renderPortfolioSnapshot() {
    if (!document.getElementById("portfolio-snapshot-card")) return;
    const active = snapshotActiveHoldings();
    renderSnapshotSectors(active);
    renderSnapshotMoves(active);
}

function allocationCenterColor(chart) {
    const active = chart.getActiveElements()?.[0];
    let idx = Number.isInteger(active?.index) ? active.index : -1;
    if (idx < 0 && selectedAllocationTicker) {
        idx = chart.data.labels.indexOf(selectedAllocationTicker);
    }
    const baseColors = chart.data.datasets[0].$baseColors || chart.data.datasets[0].backgroundColor;
    return idx >= 0 && typeof baseColors?.[idx] === "string"
        ? baseColors[idx]
        : "rgba(100, 210, 255, 0.86)";
}

// Polished live center treatment, tinted by the active/selected holding.
const centerHaloPlugin = {
    id: "centerHalo",
    afterInit(chart) {
        if (chart.config.type !== "doughnut") return;
        chart.$centerHaloStart = performance.now();
        chart.$haloFrameCount = 0;
        chart.$haloInView = true;     // toggled by IntersectionObserver (offscreen)
        chart.$haloZoneActive = true; // toggled by the dashboard zone switcher

        // Self-suspending rAF loop. When any pause condition is hit the loop drops
        // its frame handle and returns; it is restarted by the events below. This
        // means a hidden / offscreen / inactive-tab chart schedules zero frames.
        const tick = () => {
            if (!chart.$centerHaloFrame) return;
            if (document.visibilityState === "hidden" ||
                !chart.$haloInView ||
                !chart.$haloZoneActive) {
                chart.$centerHaloFrame = null; // suspend; resume() re-arms
                return;
            }
            chart.$haloFrameCount++;
            // Cap at ~30fps by drawing on every other animation frame.
            if (chart.$haloFrameCount % 2 === 0) chart.draw();
            chart.$centerHaloFrame = requestAnimationFrame(tick);
        };

        const resume = () => {
            if (chart.$centerHaloFrame || prefersReducedMotion()) return;
            if (document.visibilityState === "hidden" ||
                !chart.$haloInView || !chart.$haloZoneActive) return;
            chart.$centerHaloFrame = requestAnimationFrame(tick);
        };

        // Public hooks for the zone switcher to pause/resume an inactive-tab chart.
        chart.$haloResume = () => { chart.$haloZoneActive = true; resume(); };
        chart.$haloPause  = () => { chart.$haloZoneActive = false; };

        // Pause when the document is hidden, resume when it returns to the front.
        chart.$haloVisHandler = resume;
        document.addEventListener("visibilitychange", chart.$haloVisHandler);

        // Pause when the chart card scrolls out of the viewport.
        if (typeof IntersectionObserver !== "undefined") {
            chart.$haloObserver = new IntersectionObserver((entries) => {
                chart.$haloInView = entries[0]?.isIntersecting ?? true;
                if (chart.$haloInView) resume();
            }, { threshold: 0 });
            const target = chart.canvas?.closest(".card") || chart.canvas?.parentElement;
            if (target) chart.$haloObserver.observe(target);
        }

        resume();
    },
    afterDestroy(chart) {
        if (chart.$centerHaloFrame) cancelAnimationFrame(chart.$centerHaloFrame);
        chart.$centerHaloFrame = null;
        if (chart.$haloObserver) { chart.$haloObserver.disconnect(); chart.$haloObserver = null; }
        if (chart.$haloVisHandler) {
            document.removeEventListener("visibilitychange", chart.$haloVisHandler);
            chart.$haloVisHandler = null;
        }
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
        const ds = chart.data.datasets[datasetIndex];
        const raw = ds.$baseColors?.[index] || ds.backgroundColor?.[index] || "rgba(111,214,240,1)";
        const glow = withAlpha(raw, 0.80);
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

// Upgrades the doughnut's flat segment fills to the cached radial "tube" gradients
// once the chart has laid out (and rebuilds them after a resize or theme change).
// It applies at most once per geometry — the repaint it triggers re-enters here,
// finds the same cached gradients already applied, and bails, so there is no loop
// and no per-frame cost.
const allocFillPlugin = {
    id: "allocFill",
    afterDraw(chart) {
        if (chart.config.type !== "doughnut") return;
        const ds = chart.data?.datasets?.[0];
        const baseColors = ds?.$baseColors;
        if (!baseColors?.length) return;
        const grads = allocGradients(chart, baseColors);
        if (!grads || chart.$allocFillApplied === grads) return;
        setAllocationFocus(chart, currentAllocActiveIndex(chart));
        chart.draw();
    },
};

function renderHoldings() {
    let filtered = latestHoldings;
    if (holdingsViewFilter === "portfolio") filtered = latestHoldings.filter(h => !h.is_watchlist);
    else if (holdingsViewFilter === "research") filtered = latestHoldings.filter(h => h.is_watchlist);
    updateHoldingsTable(sortedHoldings(filtered), latestTrendData);
    updateSortCarets();

    // Show/hide research banner
    const bannerEl = document.getElementById("research-filter-banner");
    const tableWrap = document.querySelector(".holdings-table")?.closest(".table-responsive");
    if (holdingsViewFilter === "research") {
        if (!bannerEl && tableWrap) {
            const banner = document.createElement("div");
            banner.id = "research-filter-banner";
            banner.className = "research-filter-banner";
            banner.innerHTML = `<i class="bi bi-flask"></i> Research holdings &mdash; not included in your P&amp;L or performance tracking`;
            tableWrap.parentNode.insertBefore(banner, tableWrap);
        }
    } else if (bannerEl) {
        bannerEl.remove();
    }
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

// Move the sliding pill indicator to match the active tab.
// Uses offsetLeft (relative to track) so it works even when tabs show/hide.
function syncHvtIndicator() {
    const track = document.getElementById("holdings-view-tabs");
    if (!track) return;
    const indicator = track.querySelector(".hvt-indicator");
    const activeBtn = track.querySelector(".hvt-tab--active");
    if (!indicator || !activeBtn) return;
    const pad = 3; // track padding-left
    indicator.style.width = activeBtn.offsetWidth + "px";
    indicator.style.transform = `translateX(${activeBtn.offsetLeft - pad}px)`;
}

// ── Dashboard zones (Overview / Holdings / Analytics) ──────────────────────
const DASHBOARD_ZONES = ["overview", "holdings", "analytics", "news"];
const DASHBOARD_ZONE_KEY = "foliosense-dashboard-zone";
let dashboardZone = "overview";

function syncDztIndicator() {
    const track = document.getElementById("dashboard-zone-tabs");
    if (!track) return;
    const indicator = track.querySelector(".dzt-indicator");
    const activeBtn = track.querySelector(".dzt-tab--active");
    if (!indicator || !activeBtn) return;
    const pad = 4; // track padding
    indicator.style.width = activeBtn.offsetWidth + "px";
    indicator.style.transform = `translateX(${activeBtn.offsetLeft - pad}px)`;
}

function setDashboardZone(zone, opts = {}) {
    const { persist = true } = opts;
    if (!DASHBOARD_ZONES.includes(zone)) zone = "overview";
    dashboardZone = zone;

    document.querySelectorAll(".dzt-tab").forEach(btn => {
        const active = btn.dataset.zone === zone;
        btn.classList.toggle("dzt-tab--active", active);
        btn.setAttribute("aria-selected", String(active));
    });
    const track = document.getElementById("dashboard-zone-tabs");
    if (track) track.dataset.activeZone = zone;

    document.querySelectorAll(".dashboard-zone-pane").forEach(pane => {
        pane.classList.toggle("dashboard-zone-pane--active", pane.dataset.zonePane === zone);
    });

    syncDztIndicator();

    if (persist) {
        try { localStorage.setItem(DASHBOARD_ZONE_KEY, zone); } catch (_) {}
    }

    // Doughnut halo only runs while Overview is visible. Resize the relevant
    // chart once its pane is back in flow (canvases were kept sized, not hidden
    // with display:none, so this is a cheap correctness pass — not a rebuild).
    if (zone === "overview") {
        allocationChart?.$haloResume?.();
        requestAnimationFrame(() => {
            if (allocationChart) { allocationChart.resize(); allocationChart.update("none"); }
        });
        // Load briefing on first Overview visit if not already done for the
        // current time range (loadPortfolioBriefing dedupes in-flight fetches)
        if (!_cachedBriefing[_briefingCacheKey("ai")] && !_cachedBriefing[_briefingCacheKey("local")]) {
            loadPortfolioBriefing();
        }
    } else {
        allocationChart?.$haloPause?.();
    }
    if (zone === "analytics") {
        requestAnimationFrame(() => {
            if (pnlChart) { pnlChart.resize(); pnlChart.update("none"); }
            if (projectionChart) { projectionChart.resize(); projectionChart.update("none"); }
        });
        ensureProjectionLoaded();
        window.AnalyticsCharts?.onAnalyticsZoneEnter?.();
        if (!_cachedActionPlan && !_actionPlanLoading) loadActionPlan();
    }
    if (zone === "news") {
        ensureNewsLoaded();
    }
    syncHoldingExpandFab();
}

function initDashboardZones() {
    const track = document.getElementById("dashboard-zone-tabs");
    if (!track) return;
    let initial = "overview";
    setDashboardZone(initial, { persist: false });
    requestAnimationFrame(syncDztIndicator);
    window.addEventListener("resize", syncDztIndicator, { passive: true });
}

function popHvtCount(el, value) {
    if (!el) return;
    const str = String(value);
    if (el.textContent === str) return;
    el.textContent = str;
    el.classList.remove("is-popping");
    void el.offsetWidth; // force reflow so animation restarts
    el.classList.add("is-popping");
}

function setHoldingsFilter(view) {
    if (holdingsViewFilter === view) return;
    holdingsViewFilter = view;

    // Update tab active states and indicator
    document.querySelectorAll(".hvt-tab").forEach(btn => {
        const isActive = btn.dataset.view === view;
        btn.classList.toggle("hvt-tab--active", isActive);
        btn.setAttribute("aria-pressed", String(isActive));
    });
    const track = document.getElementById("holdings-view-tabs");
    if (track) track.dataset.activeView = view;
    syncHvtIndicator();

    // Amber card accent in research mode
    const card = document.getElementById("holdings-card");
    if (card) card.classList.toggle("holdings-research-mode", view === "research");

    renderHoldings();
}

function updateHoldingsFilterCounts() {
    const all = latestHoldings.length;
    const research = latestHoldings.filter(h => h.is_watchlist).length;
    const portfolio = all - research;
    popHvtCount(document.getElementById("hvt-count-all"), all);
    popHvtCount(document.getElementById("hvt-count-portfolio"), portfolio);
    popHvtCount(document.getElementById("hvt-count-research"), research);

    // Hide research tab entirely if user has no research holdings
    const researchTab = document.querySelector(".hvt-tab[data-view='research']");
    if (researchTab) {
        const wasHidden = researchTab.style.display === "none";
        researchTab.style.display = research === 0 ? "none" : "";
        // Re-sync indicator after tab visibility changes (affects offsets)
        if (wasHidden !== (research === 0)) syncHvtIndicator();
    }

    // If current filter is research but user removed all research holdings, reset
    if (holdingsViewFilter === "research" && research === 0) setHoldingsFilter("all");
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
let performanceRange = "max";
let latestPnlHistory = [];
let latestPnlHasUserData = false;
let latestPnlIsStale = false;
let latestPnlStaleDays = 0;

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

        latestPnlHistory = history;
        latestPnlHasUserData = hasUserData;
        latestPnlIsStale = isStale;
        latestPnlStaleDays = Math.floor(hoursOld / 24);
        await renderCurrentPerformanceChart();
        renderHeroPnl();

        renderRealizedTable(data.trades || []);
    } catch (err) {
        console.warn("Unable to load P&L:", err);
    }
}

async function renderCurrentPerformanceChart() {
    if (!latestPnlHasUserData) {
        updatePerfCallout("nodata");
        await loadMarketReferenceChart(performanceRange);
        return;
    }
    if (latestPnlIsStale) {
        updatePerfCallout("stale", latestPnlStaleDays);
    } else {
        hidePerfCallout();
    }
    renderPnlChart(filterHistoryForPerformanceRange(latestPnlHistory, performanceRange));
}

function filterHistoryForPerformanceRange(history, rangeKey = performanceRange) {
    const rows = (history || []).filter(row => row?.date);
    const config = PERFORMANCE_RANGES[normalizePerformanceRange(rangeKey)];
    if (!config?.days || rows.length < 2) return rows;

    const end = new Date(`${rows[rows.length - 1].date}T12:00:00`);
    const cutoff = new Date(end);
    cutoff.setDate(cutoff.getDate() - config.days);
    return rows.filter(row => new Date(`${row.date}T12:00:00`) >= cutoff);
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

async function loadMarketReferenceChart(rangeKey = performanceRange) {
    try {
        const config = PERFORMANCE_RANGES[normalizePerformanceRange(rangeKey)];
        const params = new URLSearchParams({ tickers: "SPY", period: config.marketPeriod });
        const res = await fetch(`/api/stocks/history/batch?${params}`);
        if (!res.ok) return;
        const data = await res.json();
        const hist = filterHistoryForPerformanceRange(
            (data.data?.SPY || []).filter(h => h.close > 0),
            rangeKey,
        );
        if (hist.length < 2) {
            if (pnlChart) { pnlChart.destroy(); pnlChart = null; }
            return;
        }
        renderPnlChartMarketRef(hist, config.label);
    } catch (e) { /* silent */ }
}

function renderPnlChartMarketRef(history, rangeLabel = PERFORMANCE_RANGES[performanceRange].label) {
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
                        label: (item) => `S&P 500 (${rangeLabel}): ${item.raw >= 0 ? "+" : ""}${item.raw.toFixed(2)}%`,
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
    pnlChart.$chartMode = "marketRef";
}

function renderPnlChart(history) {
    const canvas = document.getElementById("pnl-chart");
    if (!canvas) return;
    if (pnlChart?.$chartMode === "marketRef") {
        pnlChart.destroy();
        pnlChart = null;
    }

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
        pnlChart.data.datasets[0].borderDash = [];
        pnlChart.data.datasets[0].pointRadius = values.length < 2 ? 3 : 0;
        pnlChart.data.datasets[0].pointHoverRadius = values.length < 2 ? 4 : 4;
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
                pointRadius: values.length < 2 ? 3 : 0,
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
    pnlChart.$chartMode = "portfolio";
}

function renderRealizedTable(trades) {
    const tbody = document.getElementById("realized-table");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!trades.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-secondary py-4">
            No realized trades yet — they appear here when you reduce a holding.</td></tr>`;
        return;
    }

    trades.forEach(t => {
        const row = tbody.insertRow();
        const day = t.date ? new Date(t.date).toLocaleDateString() : "--";
        const tickerArg = inlineJsString(t.ticker);
        row.innerHTML = `
            <td class="text-secondary small">${day}</td>
            <td class="fw-bold">${escapeHtml(t.ticker)}</td>
            <td class="text-end">${toNumber(t.shares_sold).toFixed(3)}</td>
            <td class="text-end">${formatCurrency(t.sale_price)}</td>
            <td class="text-end">${formatCurrency(t.avg_cost)}</td>
            <td class="text-end ${colorClass(t.realized_gain)}">${formatSignedCurrency(t.realized_gain)}</td>
            <td class="text-end ${valueClass(t.total_return_pct)}">${formatOptionalPct(t.total_return_pct)}</td>
            <td class="text-end">
                <button class="btn btn-sm btn-outline-danger realized-delete-btn"
                        onclick="removeTrade(${t.id}, ${tickerArg})"
                        aria-label="Remove realized sale for ${escapeHtml(t.ticker)}">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;
    });
}


// ── Growth projection chart (Analytics) ─────────────────────────────────────

const PROJECTION_HORIZONS = ["30d", "1y", "3y", "5y", "10y"];
const PROJECTION_HORIZON_KEY = "foliosense-projection-horizon";

let projectionChart = null;
let projectionHorizon = "1y";
let latestProjectionData = null;
let projectionLoadPromise = null;

function normalizeProjectionHorizon(horizon) {
    return PROJECTION_HORIZONS.includes(horizon) ? horizon : "1y";
}

function initProjectionControls() {
    const group = document.getElementById("projection-horizon-tabs");
    if (!group) return;
    try {
        const stored = localStorage.getItem(PROJECTION_HORIZON_KEY);
        if (stored) projectionHorizon = normalizeProjectionHorizon(stored);
    } catch (_) {}
    updateProjectionHorizonControls();
    group.querySelectorAll("[data-horizon]").forEach(button => {
        button.addEventListener("click", () => setProjectionHorizon(button.dataset.horizon));
    });
}

function updateProjectionHorizonControls() {
    const group = document.getElementById("projection-horizon-tabs");
    if (!group) return;
    group.dataset.activeHorizon = projectionHorizon;
    group.querySelectorAll("[data-horizon]").forEach(button => {
        const active = button.dataset.horizon === projectionHorizon;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
    });
}

function setProjectionHorizon(horizon) {
    projectionHorizon = normalizeProjectionHorizon(horizon);
    updateProjectionHorizonControls();
    try { localStorage.setItem(PROJECTION_HORIZON_KEY, projectionHorizon); } catch (_) {}
    if (latestProjectionData) {
        renderProjectionChart(latestProjectionData);
        updateProjectionSummary(latestProjectionData);
    }
}

function ensureProjectionLoaded() {
    if (latestProjectionData) return;
    if (!projectionLoadPromise) projectionLoadPromise = loadProjection();
}

async function loadProjection() {
    try {
        const res = await fetch("/api/portfolio/projection");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        latestProjectionData = await res.json();
        projectionLoadPromise = null;

        const callout = document.getElementById("projection-empty-callout");
        if (callout) callout.style.display = latestProjectionData.has_holdings ? "none" : "";

        const disclaimer = document.getElementById("projection-disclaimer");
        if (disclaimer) disclaimer.textContent = latestProjectionData.disclaimer || "";

        if (dashboardZone === "analytics") {
            renderProjectionChart(latestProjectionData);
            updateProjectionSummary(latestProjectionData);
        }
    } catch (err) {
        projectionLoadPromise = null;
        console.warn("Unable to load projection:", err);
    }
}

function _projectionHorizonData(data) {
    return data?.horizons?.[projectionHorizon] || data?.horizons?.["1y"];
}

function updateProjectionSummary(data) {
    const hz = _projectionHorizonData(data);
    if (!hz) return;
    const start = toNumber(data.current_value) || toNumber(hz.portfolio?.values?.avg?.[0]?.value);
    const endPort = hz.portfolio?.end || {};
    const endSpy = hz.sp500?.end?.avg || 0;

    const setEnd = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = formatCompact(val);
    };
    const setDelta = (id, val) => {
        const el = document.getElementById(id);
        if (!el || !start) { if (el) el.textContent = ""; return; }
        const pct = ((val - start) / start) * 100;
        el.textContent = `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
        el.className = `projection-stat-delta ${pct >= 0 ? "text-success" : "text-danger"}`;
    };

    setEnd("proj-end-avg", endPort.avg);
    setEnd("proj-end-best", endPort.best);
    setEnd("proj-end-worst", endPort.worst);
    setEnd("proj-end-spy", endSpy);
    setDelta("proj-delta-avg", endPort.avg);
    setDelta("proj-delta-best", endPort.best);
    setDelta("proj-delta-worst", endPort.worst);
    setDelta("proj-delta-spy", endSpy);

    // Populate "why" captions and tip-trigger popovers
    const why = data.scenario_why || {};
    const m   = data.metrics || {};
    const pm  = m.portfolio || {};
    const sm  = m.sp500 || {};
    const mu  = (pm.annual_return_pct ?? 0).toFixed(1);
    const sig = (pm.annual_vol_pct    ?? 0).toFixed(1);
    const spR = (sm.annual_return_pct ?? 0).toFixed(1);

    const setWhy = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    };

    setWhy("proj-why-avg",   `Historical pace: ${mu}% per year`);
    setWhy("proj-why-best",  `If markets run hot: ~${(+mu + +sig).toFixed(1)}%/yr`);
    setWhy("proj-why-worst", `If markets cool off: ~${(+mu - +sig).toFixed(1)}%/yr`);
    setWhy("proj-why-spy",   `S&P benchmark ${spR}% — you ${+mu >= +spR ? "lead" : "trail"} by ${Math.abs(+mu - +spR).toFixed(1)}%`);

    const tipHint = "Roughly 2 in 3 outcomes fall between best and worst";
    const cards = [
        {
            id:    "proj-tip-avg",
            title: "Average scenario",
            body:  why.avg  || `Projects your portfolio at its recent ${mu}% average yearly return — steady growth if history repeats.`,
            hint:  tipHint,
        },
        {
            id:    "proj-tip-best",
            title: "Best case",
            body:  why.best || `A stronger-than-usual year (~${(+mu + +sig).toFixed(1)}% return). Happens occasionally when markets run hot.`,
            hint:  tipHint,
        },
        {
            id:    "proj-tip-worst",
            title: "Worst case",
            body:  why.worst || `A weaker-than-usual year (~${(+mu - +sig).toFixed(1)}% return). A rough patch, but still within a normal range.`,
            hint:  tipHint,
        },
        {
            id:    "proj-tip-spy",
            title: "S\u0026P 500 benchmark",
            body:  why.sp500 || `The broad US market averaged ${spR}% per year. ${+mu >= +spR ? "Your portfolio leads" : "The index leads"} by ${Math.abs(+mu - +spR).toFixed(1)}%.`,
            hint:  "Used as the market benchmark across all horizons",
        },
    ];

    cards.forEach(({ id, title, body, hint }) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.dataset.tipTitle = title;
        el.dataset.tipBody  = body;
        el.dataset.tipHint  = hint;
        el.dataset.tipIcon  = "bi-info-circle";
    });
}

function _shortProjectionLabel(isoDate, total) {
    const d = new Date(`${isoDate}T12:00:00`);
    if (total <= 14) {
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }
    if (total <= 60) {
        return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
    }
    return d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

function renderProjectionChart(data) {
    const canvas = document.getElementById("projection-chart");
    if (!canvas) return;
    const hz = _projectionHorizonData(data);
    if (!hz?.labels?.length) return;

    const labels = hz.labels.map((d, i) => _shortProjectionLabel(d, hz.labels.length));
    const portIdx = hz.portfolio?.indexed || {};
    const spyIdx = hz.sp500?.indexed?.avg || [];
    const best = portIdx.best || [];
    const worst = portIdx.worst || [];
    const avg = portIdx.avg || [];
    const portVals = hz.portfolio?.values || {};
    const spyVals = hz.sp500?.values?.avg || [];

    const theme = chartTheme();
    const scale = uiScale();
    const isLight = currentTheme() === "light";
    const bandFill = isLight ? "rgba(48, 209, 88, 0.12)" : "rgba(48, 209, 88, 0.16)";
    const avgColor = "#30d158";
    const spyColor = isLight ? "rgba(16,24,40,0.42)" : "rgba(235,235,245,0.38)";

    const datasets = [
        {
            label: "Best",
            data: best,
            borderColor: "transparent",
            backgroundColor: "transparent",
            pointRadius: 0,
            pointHoverRadius: 0,
            borderWidth: 0,
            fill: false,
            order: 4,
        },
        {
            label: "Range",
            data: worst,
            borderColor: "transparent",
            backgroundColor: bandFill,
            pointRadius: 0,
            pointHoverRadius: 0,
            borderWidth: 0,
            fill: "-1",
            order: 3,
        },
        {
            label: "Portfolio avg",
            data: avg,
            borderColor: avgColor,
            backgroundColor: "transparent",
            borderWidth: 2.25,
            tension: 0.32,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: avgColor,
            fill: false,
            order: 1,
        },
        {
            label: "S&P 500",
            data: spyIdx,
            borderColor: spyColor,
            backgroundColor: "transparent",
            borderWidth: 1.5,
            borderDash: [6, 4],
            tension: 0.32,
            pointRadius: 0,
            pointHoverRadius: 3,
            pointHoverBackgroundColor: spyColor,
            fill: false,
            order: 2,
        },
    ];

    const tooltipCb = (items) => {
        if (!items.length) return [];
        const idx = items[0].dataIndex;
        const lines = [];
        const pushVal = (label, pts) => {
            const pt = pts?.[idx];
            if (pt?.value != null) lines.push(`${label}: ${formatCompact(pt.value)}`);
        };
        pushVal("Portfolio avg", portVals.avg);
        pushVal("Best case", portVals.best);
        pushVal("Worst case", portVals.worst);
        pushVal("S&P 500", spyVals);
        return lines;
    };

    const options = {
        responsive: true,
        maintainAspectRatio: false,
        animation: prefersReducedMotion() ? false : { duration: 280, easing: "easeOutQuart" },
        interaction: { mode: "index", intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                ...tooltipOptions(),
                filter: (item) => item.datasetIndex === 2 || item.datasetIndex === 3,
                callbacks: {
                    title: (items) => {
                        const i = items[0]?.dataIndex ?? 0;
                        return hz.labels[i] || "";
                    },
                    label: () => "",
                    afterBody: tooltipCb,
                },
            },
        },
        scales: {
            x: {
                grid: { display: false },
                ticks: {
                    color: theme.tick,
                    maxRotation: 0,
                    autoSkip: true,
                    maxTicksLimit: 7,
                    font: { size: 10 * scale },
                },
            },
            y: {
                grid: { color: theme.grid },
                ticks: {
                    color: theme.tick,
                    font: { size: 10 * scale },
                    callback: (v) => `${v.toFixed(0)}`,
                },
            },
        },
    };

    if (projectionChart) {
        projectionChart.data.labels = labels;
        projectionChart.data.datasets = datasets;
        projectionChart.options = options;
        projectionChart.update();
        return;
    }

    projectionChart = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: { labels, datasets },
        options,
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

function repaintAllTrendSparklines() {
    document.querySelectorAll("#holdings-table tr[data-ticker]").forEach(row => {
        const ticker = row.dataset.ticker;
        const history = latestTrendData[ticker] || [];
        const trendCell = row.querySelector(".trend-cell");
        if (!trendCell) return;

        const canvas = trendCell.querySelector("canvas.trend-sparkline");
        if (!canvas) {
            if (history.length < 2) return;
            const holding = latestHoldings.find(h => h.ticker === ticker);
            if (holding) updateHoldingRow(row, holding, 0, latestTrendData);
            return;
        }

        delete canvas.dataset.trendSig;
        drawTrend(canvas, history);
    });
}

function repaintOpenVerdictSparklines() {
    document.querySelectorAll(".intel-verdict-section").forEach(section => {
        const expandRow = section.closest(".summary-expand-row");
        const mainRow = expandRow?.previousElementSibling;
        const ticker = mainRow?.dataset?.ticker;
        if (!ticker || !mainRow?.classList.contains("summary-open")) return;
        const verdict = section._chartVerdict || cachedVerdicts[ticker];
        if (verdict) _paintVerdictSparkline(section, verdict, ticker);
    });
}

function ensureTrendObserver() {
    if (_trendObserver || typeof IntersectionObserver === "undefined") return;
    _trendObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const cell = entry.target;
            const row = cell.closest("tr[data-ticker]");
            const canvas = cell.querySelector("canvas.trend-sparkline");
            if (!row || !canvas) return;
            const ticker = row.dataset.ticker;
            const history = latestTrendData[ticker] || [];
            if (history.length < 2) return;
            // Fast path: while scrolling, this callback fires again for every
            // row whose sparkline cell crosses the 1% threshold, even when its
            // data hasn't changed since the last time. `latestTrendData[ticker]`
            // keeps a stable array reference between fetches, so a reference
            // check lets a table full of holdings skip straight past unchanged
            // rows without touching their price history at all.
            if (_trendObserverLastHistory.get(canvas) === history) return;
            // Skip the redraw (canvas resize + gradient rebuild) when this cell
            // already shows the current data — the sig check mirrors the direct
            // render path below. Without it, every row's sparkline redraws on
            // every visibility-threshold crossing, so a table with many holdings
            // pays for a full canvas resize+repaint per row on every scroll pass
            // even though nothing changed.
            const sig = trendSignature(history);
            _trendObserverLastHistory.set(canvas, history);
            if (canvas.dataset.trendSig === sig) return;
            canvas.dataset.trendSig = sig;
            drawTrend(canvas, history);
        });
    }, { root: null, threshold: 0.01 });
}

function observeTrendCell(cell) {
    ensureTrendObserver();
    if (_trendObserver && cell) _trendObserver.observe(cell);
}

function setCellHtml(cell, html) {
    if (cell && cell.innerHTML !== html) cell.innerHTML = html;
}

function trendSignature(history = []) {
    const points = Array.isArray(history) ? history.slice(-TREND_DAYS) : [];
    return `${currentTheme()}|${points.map(point => `${point.date || ""}:${point.close ?? ""}`).join("|")}`;
}

function holdingBadgeHtml(h) {
    return h.is_watchlist
        ? `<span class="badge watchlist-badge ms-1" title="Research mode — excluded from P&L"><i class="bi bi-flask me-1"></i>Research</span>`
        : "";
}

function moveBadgeHtml(ticker) {
    const exp = cachedExplanations[ticker];
    if (!exp) return "";
    const label = ATTRIBUTION_SHORT[exp.attribution_type] || "?";
    return `<div class="move-badge ${escapeHtml(exp.attribution_type)}" title="${escapeHtml(String(exp.confidence))} confidence · ${escapeHtml(label)}">${escapeHtml(label)}</div>`;
}

function dayChangeHtml(h) {
    if (!isFiniteNumber(h.day_change_pct)) {
        return `<div class="today-cell-wrap"><span class="day-chg-cell text-secondary" title="Today's change unavailable">—</span></div>`;
    }
    const up = h.day_change_pct >= 0;
    return `
        <div class="today-cell-wrap">
            <div class="day-chg-cell ${colorClass(h.day_change_pct)}">
                <i class="bi ${up ? "bi-caret-up-fill" : "bi-caret-down-fill"}"></i>${formatPct(h.day_change_pct)}
            </div>
            ${moveBadgeHtml(h.ticker)}
        </div>
    `;
}

function createHoldingRow(h) {
    const row = document.createElement("tr");
    row.dataset.ticker = h.ticker;
    row.innerHTML = `
        <td class="fw-bold holding-ticker-cell" data-field="ticker"></td>
        <td class="d-none d-md-table-cell holding-name-cell" data-field="name"></td>
        <td class="text-end" data-field="price"></td>
        <td class="text-end" data-field="day"></td>
        <td class="text-end d-none d-md-table-cell" data-field="value"></td>
        <td class="text-end" data-field="allocation"></td>
        <td class="text-end d-none d-sm-table-cell" data-field="target" id="target-cell-${h.ticker}"></td>
        <td class="text-center d-none d-xl-table-cell" data-field="rec" id="rec-cell-${h.ticker}"></td>
        <td class="text-center d-none d-xxl-table-cell trend-cell" data-field="trend"></td>
    `;
    row.addEventListener("click", event => {
        if (event.target.closest(".tip-trigger")) return;
        toggleSummaryRow(row);
    });
    return row;
}

function updateHoldingRow(row, h, index, trendData = {}) {
    row.dataset.ticker = h.ticker;
    row.style.setProperty("--row-index", index);
    row.classList.toggle("research-holding-row", !!h.is_watchlist);

    const rec = cachedRecommendations[h.ticker];
    const tickerHtml = `
        <span class="holding-ticker-wrap">
            <span class="ticker-dot" style="background:${chartColor(index)}"></span>
            <span class="holding-ticker-symbol">${escapeHtml(h.ticker)}</span>${holdingBadgeHtml(h)}
            <i class="bi bi-chevron-right row-chevron"></i>
        </span>
    `;

    setCellHtml(row.querySelector('[data-field="ticker"]'), tickerHtml);
    setCellHtml(row.querySelector('[data-field="name"]'), escapeHtml((h.name || h.ticker).substring(0, 34)));
    setCellHtml(row.querySelector('[data-field="price"]'), formatCurrency(h.current_price));
    setCellHtml(row.querySelector('[data-field="day"]'), dayChangeHtml(h));
    setCellHtml(row.querySelector('[data-field="value"]'), formatCurrency(h.current_value));
    setCellHtml(row.querySelector('[data-field="allocation"]'), formatAllocationPct(h.allocation_pct));
    setCellHtml(row.querySelector('[data-field="target"]'), renderTargetCell(rec));
    setCellHtml(row.querySelector('[data-field="rec"]'), renderAnalystRecCell(rec));

    const trendCell = row.querySelector(".trend-cell");
    if (!trendCell) return;
    const history = trendData[h.ticker] || latestTrendData[h.ticker] || [];
    if (history.length < 2) {
        trendCell.innerHTML = `<span class="trend-pending" title="Loading price trend"><i class="bi bi-graph-up"></i></span>`;
        observeTrendCell(trendCell);
        return;
    }
    let canvas = trendCell.querySelector("canvas.trend-sparkline");
    if (!canvas) {
        trendCell.innerHTML = "";
        canvas = document.createElement("canvas");
        canvas.className = "trend-sparkline";
        canvas.width = 150;
        canvas.height = 32;
        trendCell.appendChild(canvas);
    }
    canvas.setAttribute("aria-label", `${h.ticker} ${TREND_DAYS}-day trend`);
    const sig = trendSignature(history);
    _trendObserverLastHistory.set(canvas, history);
    if (canvas.dataset.trendSig !== sig) {
        canvas.dataset.trendSig = sig;
        drawTrend(canvas, history);
    }
    observeTrendCell(trendCell);
}

function removeHoldingRowPair(row) {
    const expandRow = row.nextElementSibling?.classList.contains("summary-expand-row")
        ? row.nextElementSibling
        : null;
    if (expandRow) expandRow.remove();
    row.remove();
}


function updateHoldingsTable(holdings, trendData = {}) {
    const tbody = document.getElementById("holdings-table");
    if (!tbody) return;

    if (holdings.length === 0 && holdingsViewFilter === "research") {
        tbody.querySelectorAll("tr").forEach(row => row.remove());
        const tr = tbody.insertRow();
        tr.dataset.emptyState = "research";
        tr.innerHTML = `<td colspan="9" class="text-center py-4">
            <div class="research-empty-state">
                <i class="bi bi-flask research-empty-icon"></i>
                <div class="research-empty-title">No research holdings yet</div>
                <div class="research-empty-body">Add a ticker in research mode to track ideas without affecting your P&L.</div>
                <button class="btn btn-sm btn-outline-warning mt-2" onclick="openPortfolioManager()">Add research holding</button>
            </div>
        </td>`;
        return;
    }

    tbody.querySelectorAll("tr[data-empty-state]").forEach(row => row.remove());

    const desiredTickers = new Set(holdings.map(h => h.ticker));
    const existingRows = new Map();
    tbody.querySelectorAll("tr[data-ticker]").forEach(row => {
        if (desiredTickers.has(row.dataset.ticker)) existingRows.set(row.dataset.ticker, row);
        else removeHoldingRowPair(row);
    });

    let cursor = tbody.firstChild;
    holdings.forEach((h, i) => {
        let row = existingRows.get(h.ticker);
        if (!row) row = createHoldingRow(h);
        updateHoldingRow(row, h, i, trendData);

        const expandRow = row.nextElementSibling?.classList.contains("summary-expand-row")
            ? row.nextElementSibling
            : null;
        if (row === cursor) {
            cursor = row.nextSibling;
            // cursor may be a text node (no classList) — optional-chain through it.
            if (cursor?.classList?.contains("summary-expand-row")) cursor = cursor.nextSibling;
            return;
        }

        const fragment = document.createDocumentFragment();
        fragment.appendChild(row);
        if (expandRow) fragment.appendChild(expandRow);
        tbody.insertBefore(fragment, cursor);
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
            <button class="btn perf-callout-btn" type="button" onclick="openPortfolioManager()">
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

const HOLDING_SENPAI_QUOTES = {
    up: {
        low: [
            ({ ticker, pct }) => `${ticker} is up ${pct}. A polite green candle. We accept the compliment.`,
            ({ ticker, pct }) => `${ticker} gained ${pct}. Nothing dramatic, just professional upward behavior.`,
            ({ ticker, pct }) => `${ticker} is green by ${pct}. Small win, clean paperwork, tasteful confidence.`,
            ({ ticker, pct }) => `${ticker} added ${pct}. The portfolio just adjusted its posture.`,
            ({ ticker, pct }) => `${ticker} is up ${pct}. Claude would call this constructive. I call it charming.`,
            ({ ticker, pct }) => `${ticker} moved up ${pct}. Quietly competent, like a spreadsheet in a tailored suit.`,
            ({ ticker, pct }) => `${ticker} is green ${pct}. Not a victory parade, but definitely a nod from the market.`,
            ({ ticker, pct }) => `${ticker} gained ${pct}. Low-key alpha with excellent table manners.`,
        ],
        medium: [
            ({ ticker, pct }) => `${ticker} is up ${pct}. Now we are seeing momentum with a LinkedIn profile.`,
            ({ ticker, pct }) => `${ticker} climbed ${pct}. The candle brought receipts and a little confidence.`,
            ({ ticker, pct }) => `${ticker} is green by ${pct}. Please remain professional while feeling mildly brilliant.`,
            ({ ticker, pct }) => `${ticker} gained ${pct}. This is no longer noise; this is a signal with posture.`,
            ({ ticker, pct }) => `${ticker} is up ${pct}. Claude is typing "notable move" with impeccable restraint.`,
            ({ ticker, pct }) => `${ticker} advanced ${pct}. The portfolio chair just got a little more ergonomic.`,
            ({ ticker, pct }) => `${ticker} moved up ${pct}. A tasteful rally, lightly seasoned with swagger.`,
            ({ ticker, pct }) => `${ticker} is green ${pct}. Risk called it "encouraging" and tried not to smile.`,
        ],
        large: [
            ({ ticker, pct }) => `${ticker} is up ${pct}. That candle just walked into the boardroom with theme music.`,
            ({ ticker, pct }) => `${ticker} ripped ${pct}. Compliance says celebrate responsibly. Emotionally, we are seated.`,
            ({ ticker, pct }) => `${ticker} is green by ${pct}. This is the kind of move that makes dashboards sit up straighter.`,
            ({ ticker, pct }) => `${ticker} jumped ${pct}. Claude may need a moment; the thesis is wearing a cape.`,
            ({ ticker, pct }) => `${ticker} surged ${pct}. Not financial advice, but that candle has main-character energy.`,
            ({ ticker, pct }) => `${ticker} is up ${pct}. The portfolio just sent a calendar invite titled "Momentum."`,
            ({ ticker, pct }) => `${ticker} launched ${pct}. Somebody tell the risk model to breathe through it.`,
            ({ ticker, pct }) => `${ticker} climbed ${pct}. This is officially more than a polite green candle.`,
        ],
    },
    down: {
        low: [
            ({ ticker, pct }) => `${ticker} is down ${pct}. A small red candle, not a personality flaw.`,
            ({ ticker, pct }) => `${ticker} slipped ${pct}. Mildly rude, but still within office etiquette.`,
            ({ ticker, pct }) => `${ticker} is red by ${pct}. We are filing this under "market had coffee too late."`,
            ({ ticker, pct }) => `${ticker} dipped ${pct}. Not a thesis funeral; more like a calendar reminder.`,
            ({ ticker, pct }) => `${ticker} is down ${pct}. The chart sighed. We documented it professionally.`,
            ({ ticker, pct }) => `${ticker} gave back ${pct}. A tiny haircut, not a full rebrand.`,
            ({ ticker, pct }) => `${ticker} slipped ${pct}. Claude would say "monitor." I would say "side-eye."`,
            ({ ticker, pct }) => `${ticker} is red ${pct}. Annoying, but not yet worthy of dramatic lighting.`,
        ],
        medium: [
            ({ ticker, pct }) => `${ticker} is down ${pct}. This candle has feedback, and it scheduled the meeting itself.`,
            ({ ticker, pct }) => `${ticker} dropped ${pct}. We are calling it risk repricing because that sounds calmer.`,
            ({ ticker, pct }) => `${ticker} is red by ${pct}. The chart chose character development today.`,
            ({ ticker, pct }) => `${ticker} slipped ${pct}. Claude is choosing gentle words. I am choosing deep breaths.`,
            ({ ticker, pct }) => `${ticker} is down ${pct}. Not panic, but definitely a raised eyebrow with data attached.`,
            ({ ticker, pct }) => `${ticker} fell ${pct}. The market has notes. Unfortunately, they are in red ink.`,
            ({ ticker, pct }) => `${ticker} gave back ${pct}. Portfolio therapy has entered the chat.`,
            ({ ticker, pct }) => `${ticker} is red ${pct}. The thesis is still alive, but it did stub its toe.`,
        ],
        large: [
            ({ ticker, pct }) => `${ticker} is down ${pct}. That candle arrived with dramatic lighting and a slide deck.`,
            ({ ticker, pct }) => `${ticker} dropped ${pct}. Risk management just sat forward in its chair.`,
            ({ ticker, pct }) => `${ticker} is red by ${pct}. Claude is typing carefully. I am hiding the confetti.`,
            ({ ticker, pct }) => `${ticker} fell ${pct}. This is not a vibe; this is a committee meeting.`,
            ({ ticker, pct }) => `${ticker} is down ${pct}. The chart said "plot twist" and refused to elaborate.`,
            ({ ticker, pct }) => `${ticker} sold off ${pct}. Please keep arms and stop-loss assumptions inside the vehicle.`,
            ({ ticker, pct }) => `${ticker} is red ${pct}. The portfolio has requested a calm voice and a clean explanation.`,
            ({ ticker, pct }) => `${ticker} dropped ${pct}. Not the apocalypse, but definitely an agenda item.`,
        ],
    },
};

function holdingMoveTier(pctValue) {
    const abs = Math.abs(pctValue);
    if (abs >= 5) return "large";
    if (abs >= 2) return "medium";
    return "low";
}

function stableHoldingQuoteIndex(ticker, pctValue, tier, quoteCount) {
    const seed = `${ticker}|${tier}|${Math.round(Math.abs(pctValue) * 100)}`;
    let hash = 0;
    for (let i = 0; i < seed.length; i++) {
        hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0;
    }
    return Math.abs(hash) % quoteCount;
}

function holdingSenpaiReaction(mainRow) {
    const ticker = mainRow?.dataset?.ticker;
    if (!ticker || typeof _dashboardSenpaiSpeak !== "function") return;

    const holding = latestHoldings.find(h => h.ticker === ticker);
    if (!holding || !isFiniteNumber(holding.day_change_pct)) return;

    const pctValue = Number(holding.day_change_pct);
    const direction = pctValue > 0 ? "up" : (pctValue < 0 ? "down" : "flat");
    const tier = holdingMoveTier(pctValue);
    const payload = {
        ticker,
        pct: pctValue < 0 ? `${Math.abs(pctValue).toFixed(2)}%` : formatPct(pctValue),
    };
    let message;
    if (direction === "up") {
        const quotes = HOLDING_SENPAI_QUOTES.up[tier];
        const pick = quotes[stableHoldingQuoteIndex(ticker, pctValue, tier, quotes.length)];
        message = pick(payload);
    } else if (direction === "down") {
        const quotes = HOLDING_SENPAI_QUOTES.down[tier];
        const pick = quotes[stableHoldingQuoteIndex(ticker, pctValue, tier, quotes.length)];
        message = pick(payload);
    } else {
        message = `${ticker} is flat today. Calm, composed, and refusing to provide plot development.`;
    }

    _dashboardSenpaiSpeak(message, { reveal: true, persist: false });
}

function toggleSummaryRow(mainRow) {
    let expandRow = mainRow.nextElementSibling;
    if (!expandRow || !expandRow.classList.contains("summary-expand-row")) {
        const tbody = mainRow.closest("tbody");
        if (tbody) injectSummaryRows(tbody);
        expandRow = mainRow.nextElementSibling;
    }
    if (!expandRow || !expandRow.classList.contains("summary-expand-row")) return;
    const body = expandRow.querySelector(".summary-body");
    const isOpen = body.classList.contains("open");
    animateSummaryBody(body, !isOpen);
    mainRow.classList.toggle("summary-open", !isOpen);
    syncHoldingExpandFab();
    if (!isOpen) {
        mainRow.classList.remove("has-intel-ready");
        holdingSenpaiReaction(mainRow);
        const ticker = mainRow.dataset.ticker;
        if (ticker) {
            _lastExpandedHoldingTicker = ticker;
            const needsIntel = !cachedVerdicts[ticker] || !holdingIntelSettled(ticker);
            if (needsIntel && !intelligenceRetryingTickers.has(ticker)) {
                if (!intelligenceLoaded && !intelligenceLoading) {
                    // Full batch hasn't run yet — trigger the same scanning animation
                    // as the Local/AI Intel button so the user sees the check in progress.
                    loadHoldingIntelligence();
                } else {
                    // Batch already ran; this ticker needs a targeted retry.
                    const hub = document.getElementById("holdings-intel-hub");
                    if (hub) {
                        hub.classList.add("is-scanning");
                        hub.classList.remove("is-ready", "is-idle");
                    }
                    loadTargetedHoldingIntelligence(ticker).finally(() => {
                        updateHoldingsIntelHub({ scanning: intelligenceLoading, ready: intelligenceLoaded });
                    });
                    window.setTimeout(() => {
                        if (holdingIntelSettled(ticker)) return;
                        const expandRow = mainRow.nextElementSibling;
                        const hint = expandRow?.querySelector(".intel-slow-hint");
                        if (hint) hint.hidden = false;
                    }, 1000);
                }
            } else {
                renderExpandedTicker(ticker);
            }
            requestAnimationFrame(() => {
                const coverage = expandRow.querySelector(".intel-coverage-section");
                if (coverage) requestDeepIntel(ticker, coverage);
                const verdictSection = expandRow.querySelector(".intel-verdict-section");
                if (verdictSection) {
                    const verdict = verdictSection._chartVerdict || cachedVerdicts[ticker];
                    if (verdict) _syncVerdictCharts(verdictSection, verdict, ticker);
                }
            });
            body.addEventListener("transitionend", (e) => {
                if (e.propertyName !== "max-height") return;
                const verdictSection = expandRow.querySelector(".intel-verdict-section");
                if (verdictSection) {
                    const verdict = verdictSection._chartVerdict || cachedVerdicts[ticker];
                    if (verdict) _syncVerdictCharts(verdictSection, verdict, ticker);
                }
            }, { once: true });
        }
    }
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function inlineJsString(str) {
    return JSON.stringify(String(str ?? "")).replace(/"/g, "&quot;");
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
            <div class="coverage-hero">
                <div class="shimmer-line" style="width:120px;height:20px;border-radius:20px;margin-bottom:.45rem"></div>
                <div class="shimmer-line" style="width:88%;height:11px;margin-bottom:.3rem"></div>
                <div class="shimmer-line" style="width:72%;height:11px"></div>
            </div>
            <div class="coverage-section">
                <div class="shimmer-line" style="width:90px;height:9px;margin-bottom:.5rem"></div>
                ${[80, 60, 45, 35, 25].map(w => `
                    <div class="sector-bar-row">
                        <div class="shimmer-line" style="width:72px;height:9px;flex-shrink:0"></div>
                        <div class="shimmer-line" style="width:${w}%;height:4px"></div>
                        <div class="shimmer-line" style="width:26px;height:9px;flex-shrink:0"></div>
                    </div>`).join("")}
            </div>
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

// ── Why It Moved enrichment — Block 1/2/3 builders ───────────────────────────

function _buildMarketBackdropBlock(regime, coverageData) {
    if (!regime || typeof regime !== "object") return "";

    // Normalize a regime field: coerce to lowercase string, reject if blank or suspiciously long.
    const _rf = (v) => { const s = String(v || "").trim().toLowerCase(); return s.length > 0 && s.length < 30 ? s : ""; };

    const riskRegime  = _rf(regime.risk_regime);
    const ratesRegime = _rf(regime.rates_regime);
    const vixBand     = _rf(regime.vix_band);
    const usdRegime   = _rf(regime.usd_regime);
    if (!riskRegime && !ratesRegime && !vixBand && !usdRegime) return "";

    // Known enum sets — only render cards for values the backend explicitly supports.
    const KNOWN_RISK  = new Set(["risk_on", "risk_off", "neutral", "mixed"]);
    const KNOWN_RATES = new Set(["rates_rising", "rates_falling", "rates_steady", "steady"]);
    const KNOWN_VIX   = new Set(["elevated", "low", "normal"]);
    const KNOWN_USD   = new Set(["usd_strong", "usd_weak", "usd_steady", "steady"]);

    const items = [];
    if (KNOWN_RISK.has(riskRegime)) {
        items.push(riskRegime === "risk_on"
            ? { icon: "bi-graph-up-arrow",   label: "Risk mood", value: "Risk-on",  detail: "Markets chasing growth",    tone: "positive" }
            : riskRegime === "risk_off"
            ? { icon: "bi-graph-down-arrow", label: "Risk mood", value: "Risk-off", detail: "Investors playing it safe", tone: "negative" }
            : { icon: "bi-dash-circle",      label: "Risk mood", value: "Mixed",    detail: "No clear directional bias", tone: "neutral"  });
    }
    if (KNOWN_RATES.has(ratesRegime)) {
        items.push(ratesRegime === "rates_rising"
            ? { icon: "bi-bank", label: "Rates", value: "Rising", detail: "Borrowing costs climbing",       tone: "gold" }
            : ratesRegime === "rates_falling"
            ? { icon: "bi-bank", label: "Rates", value: "Easing", detail: "Borrowing costs coming down",   tone: "cyan" }
            : { icon: "bi-bank", label: "Rates", value: "Steady", detail: "Rates holding near current level", tone: "blue" });
    }
    if (KNOWN_VIX.has(vixBand)) {
        items.push(vixBand === "elevated"
            ? { icon: "bi-activity", label: "Fear gauge", value: "Jittery", detail: "Volatility above normal",           tone: "negative" }
            : vixBand === "low"
            ? { icon: "bi-activity", label: "Fear gauge", value: "Calm",    detail: "Markets relaxed \u2014 low volatility", tone: "positive" }
            : { icon: "bi-activity", label: "Fear gauge", value: "Normal",  detail: "Volatility in usual range",         tone: "blue"     });
    }
    if (KNOWN_USD.has(usdRegime)) {
        items.push(usdRegime === "usd_strong"
            ? { icon: "bi-currency-exchange", label: "Dollar", value: "Strong USD", detail: "US dollar rising vs peers",    tone: "cyan"    }
            : usdRegime === "usd_weak"
            ? { icon: "bi-currency-exchange", label: "Dollar", value: "Weak USD",   detail: "Dollar declining vs peers",    tone: "gold"    }
            : { icon: "bi-currency-exchange", label: "Dollar", value: "Steady USD", detail: "Dollar near its recent range", tone: "neutral" });
    }
    if (items.length === 0) return "";

    const pulseHtml = `<div class="market-pulse-strip" aria-label="Market backdrop">
        ${items.map((item, i) => `<div class="market-pulse-card ${escapeHtml(item.tone)}" style="--pulse-index:${i}">
            <i class="bi ${escapeHtml(item.icon)} pulse-icon" aria-hidden="true"></i>
            <span class="pulse-copy">
                <span class="pulse-label">${escapeHtml(item.label)}</span>
                <strong>${escapeHtml(item.value)}</strong>
                <span class="pulse-detail">${escapeHtml(item.detail)}</span>
            </span>
        </div>`).join("")}
    </div>`;

    // Summary sentence only when we have at least one recognized directional signal.
    const hasKnownRisk = riskRegime === "risk_on" || riskRegime === "risk_off";
    const hasKnownVix  = vixBand === "elevated" || vixBand === "low";
    const summaryHtml  = (hasKnownRisk || hasKnownVix) ? (() => {
        const moodWord = riskRegime === "risk_on" ? "risk-on" : riskRegime === "risk_off" ? "risk-off" : "mixed";
        const vixWord  = vixBand === "elevated" ? "jittery fear gauge" : vixBand === "low" ? "calm fear gauge" : "normal fear gauge";

        const sectors     = (coverageData?.sectors || []).map(s => (s.name || "").toLowerCase());
        const theme       = (coverageData?.theme   || "").toLowerCase();
        const isGrowth    = sectors.some(s => /tech|software|growth|consumer discret/.test(s)) || /growth|tech/.test(theme);
        const isDefensive = sectors.some(s => /util|health|consumer stap|real estate/.test(s)) || /defensive|dividend/.test(theme);

        let tailClause;
        if (riskRegime === "risk_off" && vixBand === "elevated") {
            tailClause = isDefensive ? " \u2014 defensive pockets stayed more resilient than growth today."
                : isGrowth           ? " \u2014 growth and risk assets typically face the most pressure."
                :                      " \u2014 investors shifted toward safer ground today.";
        } else if (riskRegime === "risk_on" && vixBand === "low") {
            tailClause = isGrowth    ? " \u2014 growth and tech usually benefit the most."
                : isDefensive        ? " \u2014 even defensive holdings tend to find buyers in this backdrop."
                :                      " \u2014 a broad tailwind for most holdings today.";
        } else if (riskRegime === "risk_off") {
            tailClause = " \u2014 defensive corners held up better than growth today.";
        } else if (riskRegime === "risk_on") {
            tailClause = " \u2014 broad market conditions support most holdings.";
        } else {
            tailClause = " \u2014 no clear directional push from the broader market today.";
        }
        return `<p class="move-explanation-text">${escapeHtml(`Broad market leaning ${moodWord} with a ${vixWord}${tailClause}`)}</p>`;
    })() : "";

    return `
        <div class="intel-label"><i class="bi bi-globe-americas"></i> Market backdrop</div>
        ${pulseHtml}
        ${summaryHtml}`;
}

function _buildTodayInContextBlock(timing, data) {
    const sparkline = timing.sparkline_30d;
    if (!Array.isArray(sparkline) || sparkline.length < 5) return "";
    const pts = sparkline.filter(v => Number.isFinite(v));
    if (pts.length < 5) return "";

    const deltas = [];
    for (let i = 1; i < pts.length; i++) deltas.push(pts[i] - pts[i - 1]);
    if (deltas.length < 2) return "";

    const mean     = deltas.reduce((s, v) => s + v, 0) / deltas.length;
    const variance = deltas.reduce((s, v) => s + (v - mean) ** 2, 0) / deltas.length;
    let typicalSwing = Math.sqrt(variance);
    if (!Number.isFinite(typicalSwing) || typicalSwing < 0.01) {
        typicalSwing = deltas.reduce((s, v) => s + Math.abs(v), 0) / deltas.length;
    }
    // Clamp to [0.05, 25]% — guards against a flat 30-day period producing 0, or a
    // single extreme outlier inflating the baseline into an absurd number.
    typicalSwing = Math.min(Math.max(Math.round(typicalSwing * 10) / 10, 0.05), 25);

    // Require a finite day change — if the explanation was fetched before price data
    // was available, `day_change_pct` can be null/NaN and the classification would be wrong.
    if (!isFiniteNumber(data.day_change_pct)) return "";
    const today = Math.abs(Number(data.day_change_pct));

    const classification = today <= typicalSwing       ? "Routine day"
        : today <= 2 * typicalSwing                    ? "Notable day"
        :                                                "Big day";
    const tone           = today <= typicalSwing       ? "positive"
        : today <= 2 * typicalSwing                    ? "gold"
        :                                                "negative";
    const detail         = `within its usual \xB1${typicalSwing.toFixed(1)}% daily swing`;

    return `
        <div class="intel-label"><i class="bi bi-rulers"></i> Today in context</div>
        <div class="market-pulse-strip">
            <div class="market-pulse-card ${escapeHtml(tone)}" style="--pulse-index:0">
                <i class="bi bi-bar-chart-line pulse-icon" aria-hidden="true"></i>
                <span class="pulse-copy">
                    <span class="pulse-label">Daily range</span>
                    <strong>${escapeHtml(classification)}</strong>
                    <span class="pulse-detail">${escapeHtml(detail)}</span>
                </span>
            </div>
        </div>
        <div class="verdict-sparkline-wrap why-it-moved-sparkline-wrap">
            <canvas class="move-context-sparkline" width="280" height="56"></canvas>
        </div>`;
}

function _buildTrendContextBlock(timing) {
    if (timing.available === false) return "";
    if (timing.vs50d_pct == null && timing.vs200d_pct == null && timing.momentum_state == null) return "";

    const momentumMap = {
        trend_intact:  "Still on track",
        stabilizing:   "Finding its footing",
        rolling_over:  "Trend fading",
        weakening:     "Below key averages",
        neutral:       "No clear trend",
    };

    const rows = [];
    if (timing.vs50d_pct != null && Number.isFinite(Number(timing.vs50d_pct))) {
        const val = Number(timing.vs50d_pct);
        // Reject values outside ±500% — almost certainly a data artifact or unit mismatch.
        if (Math.abs(val) < 500) {
            rows.push(`<div class="intel-spec-row"><span>vs 50-day avg</span><strong>${escapeHtml(formatPct(val))}</strong></div>`);
        }
    }
    if (timing.vs200d_pct != null && Number.isFinite(Number(timing.vs200d_pct))) {
        const val = Number(timing.vs200d_pct);
        if (Math.abs(val) < 500) {
            rows.push(`<div class="intel-spec-row"><span>vs 200-day avg</span><strong>${escapeHtml(formatPct(val))}</strong></div>`);
        }
    }
    // Only surface momentum labels that are in the known map — never let raw API strings
    // reach the UI (e.g. if the backend adds a new state we haven't mapped yet).
    if (timing.momentum_state && Object.prototype.hasOwnProperty.call(momentumMap, timing.momentum_state)) {
        rows.push(`<div class="intel-spec-row"><span>Momentum</span><strong>${escapeHtml(momentumMap[timing.momentum_state])}</strong></div>`);
    }
    const dd = Number(timing.drawdown_from_52w_high_pct);
    // The backend may return this as a positive (5) or negative (-5) number depending on
    // version; Math.abs handles both conventions.
    if (Number.isFinite(dd) && Math.abs(dd) >= 3) {
        rows.push(`<div class="intel-spec-row"><span>Off its 1-yr high</span><strong>-${Math.abs(dd).toFixed(1)}%</strong></div>`);
    }
    if (rows.length === 0) return "";

    return `
        <div class="intel-label"><i class="bi bi-compass"></i> Where today sits in the trend</div>
        <div class="intel-spec-rows">${rows.join("")}</div>`;
}

// ─────────────────────────────────────────────────────────────────────────────

function renderMoveExplainer(section, data, coverageData = null) {
    if (!data) { renderMoveExplainerFallback(section); return; }

    const ticker = coverageData?.ticker || data.ticker || "";
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
    if (isFiniteNumber(data.volume_vs_avg)) {
        const volVsAvg = Number(data.volume_vs_avg);
        macroPills.push({ label: `Vol ${volVsAvg.toFixed(1)}× avg`, pos: volVsAvg >= 1.5 });
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
    const contributionHtml = renderContributionBreakdown(
        coverageData?.contribution_breakdown,
        data.day_change_pct,
        coverageData?.ticker,
        coverageData?.coverage_type,
        coverageData?.top_holdings,
        coverageData?.holdings_estimated
    );

    const verdict = cachedVerdicts[ticker] || {};
    const timing  = verdict.timing || {};
    const regime  = verdict.regime_context || verdict.regime || cachedMarketRegime || {};

    const backdropHtml = _buildMarketBackdropBlock(regime, coverageData);
    const contextHtml  = _buildTodayInContextBlock(timing, data);
    const trendHtml    = _buildTrendContextBlock(timing);

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
            ${contributionHtml}
            ${backdropHtml}
            ${contextHtml}
            ${trendHtml}
        </div>`;
    const heroEl = section.querySelector(".move-hero-number");
    if (heroEl) animateMoveHeroNumber(heroEl, heroEl.textContent);
    const ctxCanvas = section.querySelector("canvas.move-context-sparkline");
    if (ctxCanvas && Array.isArray(timing.sparkline_30d)) _drawPctSparkline(ctxCanvas, timing.sparkline_30d);
}

// ── Holding Coverage ("What It Covers") ──────────────────────────────────────

const COVERAGE_TYPE_HINTS = {
    equity: "You own one company — not a basket of stocks",
    "etf-broad": "A fund that holds many stocks across the whole market",
    "etf-sector": "A fund focused on one industry, like tech or healthcare",
    "etf-thematic": "A fund built around a theme, like AI or clean energy",
    "etf-international": "A fund focused on companies outside the United States",
    "etf-crypto": "A fund that tracks cryptocurrency prices",
};

function coverageTypeHint(type = "") {
    return COVERAGE_TYPE_HINTS[type] || "What this holding represents in your portfolio";
}

function renderCoverageDivider(icon, label) {
    return `<div class="coverage-divider">
        <span class="coverage-divider-label"><i class="bi ${icon}"></i>${escapeHtml(label)}</span>
    </div>`;
}

function renderCoverageSectionHint(text) {
    return text ? `<p class="coverage-section-hint">${escapeHtml(text)}</p>` : "";
}

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
        return `${data.aum_estimated ? "Est. " : ""}AUM: $${formatCompactNumber(aum)}`;
    }
    return "";
}

function formatSignalPct(value, decimals = 1) {
    if (!isFiniteNumber(value)) return "—";
    const numeric = Number(value);
    const d = Math.abs(numeric) >= 100 ? 0 : decimals;
    return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(d)}%`;
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
    const aumEstimated = !!data?.aum_estimated;
    const change30 = firstFiniteValue(priceSignal?.vs30dChangePct, priceSignal?.vs30dPct);
    const change200 = firstFiniteValue(priceSignal?.vs200dChangePct, priceSignal?.vs200dPct);
    const hasTrends = isFiniteNumber(change30) || isFiniteNumber(change200);
    if (!hasAum && !hasTrends) return "";
    const missingAumDetail = "Yahoo/yfinance didn’t answer with AUM yet. Use Ask Claude below for an estimate.";

    return `
        <div class="fund-scale-spotlight" aria-label="Fund scale and price trend">
            <div class="fund-scale-emblem" aria-hidden="true">
                <i class="bi bi-stars"></i>
            </div>
            <div class="fund-scale-copy">
                <span class="fund-scale-label">Fund scale</span>
                <strong class="fund-scale-value" style="${hasAum ? "" : "font-size:.82rem;opacity:.7"}">${hasAum ? escapeHtml(formatCompact(aum)) : "Still sourcing"}</strong>
                <span class="fund-scale-detail">${hasAum ? (aumEstimated ? "Estimated assets under management via Claude fallback" : "Assets under management") : missingAumDetail}</span>
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

function renderContributionBreakdown(
    breakdown,
    etfDayChangePct,
    ticker,
    coverageType,
    topHoldings,
    holdingsEstimated = false
) {
    if (!breakdown || !breakdown.length) {
        if (coverageType && coverageType !== "equity" && ticker) {
            const tickerArg = inlineJsString(ticker);
            const local = isLocalIntelligenceMode();
            const emptyCopy = local
                ? "Yahoo/yfinance didn’t answer with this fund’s constituents. Enable Claude AI in menu → Intelligence → Engine to seed holdings."
                : "Yahoo/yfinance didn’t answer with this fund’s constituents. Claude can estimate AUM and top-holdings, then use live prices for the move math.";
            const retryBtn = local ? "" : `
                    <button class="contrib-retry-btn" data-engine-claude-only onclick="reloadContributionForTicker(${tickerArg})">
                        <i class="bi bi-stars"></i> Ask Claude
                    </button>`;
            return `
                <div class="intel-label" style="margin-top:.6rem">
                    <i class="bi bi-distribute-vertical"></i> Holdings Contribution
                </div>
                <div class="contrib-empty">
                    <i class="bi bi-hourglass-split contrib-empty-icon" style="opacity:.55"></i>
                    <span class="contrib-empty-text" style="font-size:.8rem;line-height:1.45">
                        ${emptyCopy}
                    </span>
                    ${retryBtn}
                </div>`;
        }
        return "";
    }

    const normalized = breakdown
        .map(h => ({
            ...h,
            day_change_pct: Number(h.day_change_pct),
            contribution_pp: Number(h.contribution_pp),
        }))
        .filter(h => isFiniteNumber(h.day_change_pct) && isFiniteNumber(h.contribution_pp));

    if (!normalized.length) return "";

    const topGainers = normalized
        .filter(h => h.contribution_pp > 0)
        .sort((a, b) => b.contribution_pp - a.contribution_pp)
        .slice(0, 5);
    const topLosers = normalized
        .filter(h => h.contribution_pp < 0)
        .sort((a, b) => a.contribution_pp - b.contribution_pp)
        .slice(0, 5);
    const displayedRows = [...topGainers, ...topLosers];
    const totalPp = displayedRows.reduce((s, h) => s + h.contribution_pp, 0);

    const renderRows = (items, maxAbs, baseIndex) => items.map((h, i) => {
        const isPos = h.contribution_pp >= 0;
        const barPct = Math.round(Math.abs(h.contribution_pp) / maxAbs * 100);
        const chgSign = h.day_change_pct >= 0 ? "+" : "";
        const chgStr = `${chgSign}${h.day_change_pct.toFixed(2)}%`;
        const ppSign  = h.contribution_pp >= 0 ? "+" : "";
        const ppStr   = `${ppSign}${h.contribution_pp.toFixed(2)}%`;
        const dirIcon = isPos ? "bi-caret-up-fill" : "bi-caret-down-fill";
        return `
        <div class="contrib-row" style="--contrib-delay:${(baseIndex + i) * 0.06}s">
            <span class="contrib-ticker">${escapeHtml(h.ticker)}</span>
            <span class="contrib-chg ${isPos ? "positive" : "negative"}"><i class="bi ${dirIcon} contrib-dir-icon"></i>${escapeHtml(chgStr)}</span>
            <div class="contrib-bar-track">
                <div class="contrib-bar-fill ${isPos ? "pos" : "neg"}" style="--contrib-bar:${barPct / 100}"></div>
            </div>
            <span class="contrib-pp ${isPos ? "positive" : "negative"}">${escapeHtml(ppStr)}</span>
        </div>`;
    }).join("");

    const renderGroup = (title, tone, items, baseIndex) => {
        const icon = tone === "positive" ? "bi-arrow-up-right" : "bi-arrow-down-right";
        if (!items.length) {
            return `
                <div class="contrib-group ${tone}">
                    <div class="contrib-group-title"><i class="bi ${icon}"></i>${title}</div>
                    <div class="contrib-empty-row">No ${tone === "positive" ? "gainers" : "losers"} in the sampled holdings</div>
                </div>`;
        }
        const maxAbs = Math.max(...items.map(h => Math.abs(h.contribution_pp)), 0.0001);
        return `
            <div class="contrib-group ${tone}">
                <div class="contrib-group-title"><i class="bi ${icon}"></i>${title}</div>
                ${renderRows(items, maxAbs, baseIndex)}
            </div>`;
    };

    const totalSign = totalPp >= 0 ? "+" : "";
    const totalStr  = `${totalSign}${totalPp.toFixed(2)}%`;
    const totalTone = totalPp >= 0 ? "positive" : "negative";
    const shownCount = displayedRows.length;
    const groupLabel = `${topGainers.length} gainers / ${topLosers.length} losers`;

    let summaryLine = `Top gainers and losers netted <strong class="${totalTone}">${escapeHtml(totalStr)}</strong> to today's move`;
    if (isFiniteNumber(etfDayChangePct) && Math.abs(etfDayChangePct) > 0.01) {
        const sameSide = (totalPp >= 0) === (etfDayChangePct >= 0);
        const pct = Math.round(Math.abs(totalPp) / Math.abs(etfDayChangePct) * 100);
        if (!sameSide) {
            // Displayed holdings moved against the ETF's net direction; other holdings dominated.
            summaryLine += ` — other holdings drove the net move`;
        } else if (pct > 100) {
            // Displayed holdings over-explain the ETF's move; other holdings partially offset.
            summaryLine += ` — offset by other holdings (shown ${shownCount} over-explain net move)`;
        } else {
            summaryLine += ` (${pct}% of net move from ${groupLabel})`;
        }
    }

    return `
        <div class="intel-label" style="margin-top:.6rem">
            <i class="bi bi-distribute-vertical"></i> Holdings Contribution${holdingsEstimated ? " (estimated)" : ""}
        </div>
        <div class="contrib-breakdown">
            <div class="contrib-header">
                <span class="contrib-col-ticker"><i class="bi bi-tag-fill"></i> Holding</span>
                <span class="contrib-col-chg"><i class="bi bi-arrow-up-down"></i> Move</span>
                <span class="contrib-col-bar"></span>
                <span class="contrib-col-pp"><i class="bi bi-bullseye"></i> Impact</span>
            </div>
            ${renderGroup("Top Gains", "positive", topGainers, 0)}
            ${renderGroup("Top Losers", "negative", topLosers, topGainers.length)}
            <div class="contrib-summary">${summaryLine}</div>
        </div>`;
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

// ── Stock deep-dive enrichment helpers ───────────────────────────────────────

function _buildEquityFundamentals(data, rating, aiMode) {
    const valuationRows = [];
    const profitabilityRows = [];
    const growthRows = [];

    if (isFiniteNumber(data.pe_ratio) && Number(data.pe_ratio) > 0) {
        valuationRows.push(`<div class="intel-spec-row"><span>P/E ratio ${_verdictTip({
            title: "P/E ratio",
            body: "How many years of current earnings investors are paying for. Higher means the market expects faster growth ahead.",
        })}</span><strong>${escapeHtml(formatPositiveMultiple(data.pe_ratio))}</strong></div>`);
    }
    if (isFiniteNumber(data.forward_pe) && Number(data.forward_pe) > 0) {
        valuationRows.push(`<div class="intel-spec-row"><span>Forward P/E ${_verdictTip({
            title: "Forward P/E",
            body: "Like P/E but uses next year's expected earnings. Lower can mean the stock looks cheaper once growth kicks in.",
        })}</span><strong>${escapeHtml(formatPositiveMultiple(data.forward_pe))}</strong></div>`);
    }
    if (isFiniteNumber(data.enterprise_to_revenue) && Number(data.enterprise_to_revenue) > 0) {
        valuationRows.push(`<div class="intel-spec-row"><span>EV / Sales ${_verdictTip({
            title: "Enterprise value / Sales",
            body: "Total company value (equity + debt) divided by annual revenue — useful for comparing firms with different debt loads.",
        })}</span><strong>${escapeHtml(formatPositiveMultiple(data.enterprise_to_revenue))}</strong></div>`);
    } else if (isFiniteNumber(data.price_to_sales) && Number(data.price_to_sales) > 0) {
        valuationRows.push(`<div class="intel-spec-row"><span>Price / Sales ${_verdictTip({
            title: "Price / Sales",
            body: "What investors pay per dollar of revenue — handy when profits are thin or negative. Lower often means cheaper.",
        })}</span><strong>${escapeHtml(formatPositiveMultiple(data.price_to_sales))}</strong></div>`);
    }
    if (isFiniteNumber(data.enterprise_to_ebitda) && Number(data.enterprise_to_ebitda) > 0) {
        valuationRows.push(`<div class="intel-spec-row"><span>EV / EBITDA ${_verdictTip({
            title: "Enterprise value / EBITDA",
            body: "Total company value versus operating profit before interest, taxes, and accounting charges. A standard M&A yardstick.",
        })}</span><strong>${escapeHtml(formatPositiveMultiple(data.enterprise_to_ebitda))}</strong></div>`);
    }

    if (isFiniteNumber(data.profit_margin)) {
        const v = Number(data.profit_margin);
        const cls = v > 0 ? " class=\"text-success\"" : v < 0 ? " class=\"text-danger\"" : "";
        profitabilityRows.push(`<div class="intel-spec-row"><span>Profit margin ${_verdictTip({
            title: "Net profit margin",
            body: "Cents kept as net profit after every bill — taxes, interest, everything. Positive means the company is making money.",
        })}</span><strong${cls}>${escapeHtml(formatPercentMetric(v, 1))}</strong></div>`);
    }
    if (isFiniteNumber(data.operating_margin)) {
        const v = Number(data.operating_margin);
        const cls = v > 0 ? " class=\"text-success\"" : v < 0 ? " class=\"text-danger\"" : "";
        profitabilityRows.push(`<div class="intel-spec-row"><span>Operating margin ${_verdictTip({
            title: "Operating margin",
            body: "Profit from the core business before interest and taxes — a clean view of how efficient the operation actually is.",
        })}</span><strong${cls}>${escapeHtml(formatPercentMetric(v, 1))}</strong></div>`);
    }
    if (isFiniteNumber(data.gross_margin)) {
        const v = Number(data.gross_margin);
        const cls = v > 0 ? " class=\"text-success\"" : v < 0 ? " class=\"text-danger\"" : "";
        profitabilityRows.push(`<div class="intel-spec-row"><span>Gross margin ${_verdictTip({
            title: "Gross margin",
            body: "Revenue minus direct production costs, as a percentage. High gross margins leave room for profit after other expenses.",
        })}</span><strong${cls}>${escapeHtml(formatPercentMetric(v, 1))}</strong></div>`);
    }

    if (isFiniteNumber(data.revenue_growth)) {
        const v = Number(data.revenue_growth);
        const cls = v > 0 ? " class=\"text-success\"" : v < 0 ? " class=\"text-danger\"" : "";
        growthRows.push(`<div class="intel-spec-row"><span>Revenue growth ${_verdictTip({
            title: "Revenue growth",
            body: "How fast the company's sales grew versus the same period last year — the fuel that eventually drives profits.",
        })}</span><strong${cls}>${escapeHtml(formatPercentMetric(v, 1))}</strong></div>`);
    }
    if (isFiniteNumber(data.fcf_yield)) {
        const v = Number(data.fcf_yield);
        const cls = v > 0 ? " class=\"text-success\"" : v < 0 ? " class=\"text-danger\"" : "";
        growthRows.push(`<div class="intel-spec-row"><span>FCF yield ${_verdictTip({
            title: "Free cash flow yield",
            body: "Real cash generated as a percentage of market cap — the purest sign of financial health, harder to fake than earnings.",
        })}</span><strong${cls}>${escapeHtml(formatPercentMetric(v, 1))}</strong></div>`);
    }
    if (isFiniteNumber(data.dividend_yield) && Number(data.dividend_yield) > 0) {
        growthRows.push(`<div class="intel-spec-row"><span>Dividend yield ${_verdictTip({
            title: "Dividend yield",
            body: "Annual cash paid to shareholders as a percentage of the stock price — income you receive without having to sell shares.",
        })}</span><strong class="text-success">${escapeHtml(formatPercentMetric(Number(data.dividend_yield), 1))}</strong></div>`);
    }
    if (isFiniteNumber(data.total_revenue) && Number(data.total_revenue) > 0) {
        growthRows.push(`<div class="intel-spec-row"><span>Revenue ${_verdictTip({
            title: "Annual revenue",
            body: "Total sales the company brought in over the last 12 months — the top line of every income statement.",
        })}</span><strong>${escapeHtml(formatCompact(data.total_revenue))}</strong></div>`);
    }
    if (isFiniteNumber(data.ebitda) && Number(data.ebitda) > 0) {
        growthRows.push(`<div class="intel-spec-row"><span>EBITDA ${_verdictTip({
            title: "EBITDA",
            body: "Earnings before interest, taxes, depreciation, and amortization — a rough proxy for operating cash flow.",
        })}</span><strong>${escapeHtml(formatCompact(data.ebitda))}</strong></div>`);
    }

    if (!valuationRows.length && !profitabilityRows.length && !growthRows.length) return "";

    const pmRaw = isFiniteNumber(data.profit_margin) ? Number(data.profit_margin) : null;
    const pmPct = pmRaw !== null ? (Math.abs(pmRaw) <= 1 ? pmRaw * 100 : pmRaw) : null;
    const rgRaw = isFiniteNumber(data.revenue_growth) ? Number(data.revenue_growth) : null;
    const rgPct = rgRaw !== null ? (Math.abs(rgRaw) <= 1 ? rgRaw * 100 : rgRaw) : null;
    const pe = (isFiniteNumber(data.forward_pe) && Number(data.forward_pe) > 0) ? Number(data.forward_pe)
             : (isFiniteNumber(data.pe_ratio) && Number(data.pe_ratio) > 0) ? Number(data.pe_ratio) : null;

    const sentenceParts = [];
    if (pmPct !== null) {
        if (pmPct > 15) sentenceParts.push("highly profitable");
        else if (pmPct > 0) sentenceParts.push("profitable");
        else sentenceParts.push("currently unprofitable");
    }
    if (rgPct !== null) {
        if (rgPct > 20) sentenceParts.push("growing revenue quickly");
        else if (rgPct > 5) sentenceParts.push("growing steadily");
        else if (rgPct >= 0) sentenceParts.push("with flat revenue");
        else sentenceParts.push("with shrinking revenue");
    }
    if (pe !== null) {
        if (pe > 40) sentenceParts.push("valued richly by earnings standards");
        else if (pe < 15) sentenceParts.push("at a modest earnings multiple");
        else sentenceParts.push("at a fair earnings multiple");
    }

    let summaryHtml = "";
    if (sentenceParts.length) {
        const joined = sentenceParts.length > 1
            ? sentenceParts.slice(0, -1).join(", ") + " and " + sentenceParts[sentenceParts.length - 1]
            : sentenceParts[0];
        const sentence = joined.charAt(0).toUpperCase() + joined.slice(1) + ".";
        const tipBody = aiMode && data.strategy
            ? String(data.strategy).slice(0, 140)
            : "Based on live financial data — useful context, not a recommendation.";
        const tip = _verdictTip({
            title: "Financial snapshot",
            body: tipBody,
            icon: aiMode ? "bi-stars" : "bi-info-circle-fill",
            variant: aiMode ? "ai" : "",
        });
        summaryHtml = `<p class="eq-fundamentals-summary">${escapeHtml(sentence)} ${tip}</p>`;
    }

    const groupParts = [];
    if (valuationRows.length) groupParts.push(`<div class="intel-spec-rows">${valuationRows.join("")}</div>`);
    if (profitabilityRows.length) groupParts.push(`<div class="intel-spec-rows">${profitabilityRows.join("")}</div>`);
    if (growthRows.length) groupParts.push(`<div class="intel-spec-rows">${growthRows.join("")}</div>`);

    return `
        <div class="coverage-section">
            ${renderCoverageDivider("bi-table", "By the numbers")}
            ${renderCoverageSectionHint("The financial vital signs behind this company")}
            ${groupParts.join("")}
            ${summaryHtml}
        </div>`;
}

function _buildEquityValueBlock(data, rating, timing) {
    const watchLevels = timing.watch_levels || {};
    const posPct = isFiniteNumber(timing.range_position_pct) ? Number(timing.range_position_pct) : null;
    const low = isFiniteNumber(watchLevels.fifty_two_week_low) ? Number(watchLevels.fifty_two_week_low) : null;
    const high = isFiniteNumber(watchLevels.fifty_two_week_high) ? Number(watchLevels.fifty_two_week_high) : null;

    let rangeBarHtml = "";
    if (posPct !== null && low !== null && high !== null && high > low) {
        const pct = Math.min(Math.max(posPct, 0), 100);
        let zoneTone, zoneLabel;
        if (pct <= 33) {
            zoneTone = "positive";
            zoneLabel = "Bargain zone";
        } else if (pct <= 66) {
            zoneTone = "cyan";
            zoneLabel = "Fair zone";
        } else {
            zoneTone = "gold";
            zoneLabel = "Expensive zone";
        }
        const dd = isFiniteNumber(timing.drawdown_from_52w_high_pct)
            ? Math.abs(Number(timing.drawdown_from_52w_high_pct)) : 0;
        const drawdownCaption = dd >= 3
            ? `<p class="eq-range-drawdown">\u2014 ${dd.toFixed(1)}% off its 12-month high</p>`
            : "";
        const rangeTip = _verdictTip({
            title: "52-week range",
            body: "Where today's price sits between the stock's 12-month low and high. Lower in the range can mean more room to recover.",
        });
        rangeBarHtml = `
            <div class="eq-range-bar-wrap">
                <div class="eq-range-bar-labels">
                    <span class="eq-range-edge">${escapeHtml(formatCurrency(low))}</span>
                    <span class="eq-range-zone ${escapeHtml(zoneTone)}">${escapeHtml(zoneLabel)} ${rangeTip}</span>
                    <span class="eq-range-edge">${escapeHtml(formatCurrency(high))}</span>
                </div>
                <div class="eq-range-bar-track">
                    <div class="eq-range-bar-fill ${escapeHtml(zoneTone)}" style="width:${pct.toFixed(1)}%"></div>
                    <div class="eq-range-bar-marker" style="left:${pct.toFixed(1)}%"></div>
                </div>
                ${drawdownCaption}
            </div>`;
    }

    let analystHtml = "";
    if (isFiniteNumber(rating.target_price) || (rating.analyst_count && rating.label)) {
        const rows = [];
        if (isFiniteNumber(rating.target_price)) {
            const upside = isFiniteNumber(rating.target_upside_pct) ? Number(rating.target_upside_pct) : null;
            const tone = upside !== null ? signalTone(upside) : "neutral";
            const toneClass = tone === "positive" ? "text-success" : tone === "negative" ? "text-danger" : "text-secondary";
            const upsideSpan = upside !== null
                ? ` <span class="${toneClass}">${escapeHtml(formatSignalPct(upside))}</span>`
                : "";
            rows.push(`<div class="intel-spec-row">
                <span>Analyst target ${_verdictTip({
                    title: "Analyst price target",
                    body: "The average price Wall Street analysts think this stock is worth 12 months from now.",
                })}</span>
                <strong>${escapeHtml(formatCurrency(rating.target_price))}${upsideSpan}</strong>
            </div>`);
        }
        if (rating.analyst_count && rating.label) {
            rows.push(`<div class="intel-spec-row">
                <span>Consensus ${_verdictTip({
                    title: "Analyst consensus",
                    body: "How many analysts cover this stock and what their average recommendation is — Buy, Hold, or Sell.",
                })}</span>
                <strong>${escapeHtml(String(rating.analyst_count))} analysts · ${escapeHtml(String(rating.label))}</strong>
            </div>`);
        }
        if (rows.length) {
            analystHtml = `<div class="intel-spec-rows">${rows.join("")}</div>`;
        }
    }

    if (!rangeBarHtml && !analystHtml) return "";

    return `
        <div class="coverage-section">
            ${renderCoverageDivider("bi-graph-up", "Where it trades")}
            ${renderCoverageSectionHint("How today\u2019s price compares to its last 12 months and to Wall Street\u2019s targets")}
            ${rangeBarHtml}
            ${analystHtml}
        </div>`;
}

function renderHoldingCoverage(section, data) {
    if (!data) {
        section.innerHTML = `<div class="intel-coverage"><span class="intel-na">Coverage data not available</span></div>`;
        return;
    }

    const coverageType = data.coverage_type || "equity";
    const coverageClass = coverageType.replace(/[^a-z-]/g, "");
    const rating = cachedRecommendations[data.ticker] || {};
    const quality = rating.etf_quality || null;
    const priceSignal = rating.price_signal || null;
    const typeLabel = data.coverage_label || data.coverage_type || "Holding";
    const typeHint = coverageTypeHint(coverageType);
    const heroTagline = data.theme || typeHint;
    const heroSubhint = data.theme ? typeHint : "";
    const strategyText = (data.strategy || "").trim();
    const verdict = cachedVerdicts[data.ticker] || {};
    const timing = verdict.timing || {};
    const aiMode = !isLocalIntelligenceMode();

    const heroHtml = `
        <div class="coverage-hero">
            <div class="coverage-hero-head">
                <span class="coverage-type-badge ${escapeHtml(coverageClass)}">${escapeHtml(typeLabel)}</span>
            </div>
            <p class="coverage-hero-tagline">${escapeHtml(heroTagline)}</p>
            ${heroSubhint ? `<p class="coverage-hero-subhint">${escapeHtml(heroSubhint)}</p>` : ""}
            ${strategyText && strategyText !== heroTagline && strategyText !== heroSubhint
                ? `<p class="coverage-hero-summary">${escapeHtml(strategyText)}</p>`
                : ""}
        </div>`;

    const sectorBarsHtml = data.sectors && data.sectors.length
        ? `<div class="coverage-section">
            ${renderCoverageDivider("bi-diagram-3", "Industries")}
            ${renderCoverageSectionHint("Business types inside this holding — wider bars mean a bigger slice")}
            <div class="sector-bars">
              ${data.sectors.slice(0, 5).map((s, i) => `
                <div class="sector-bar-row">
                  <span class="sector-bar-swatch" style="--sector-color:${chartColor(i)}"></span>
                  <div class="sector-bar-label" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</div>
                  <div class="sector-bar-track"><div class="sector-bar-fill" style="--sector-color:${chartColor(i)};width:${Math.min(s.weight, 100)}%"></div></div>
                  <div class="sector-bar-pct">${s.weight.toFixed(1)}%</div>
                </div>`).join("")}
            </div>
           </div>`
        : "";

    const countryChipsHtml = data.countries && data.countries.length
        ? `<div class="coverage-section">
            ${renderCoverageDivider("bi-globe2", "Geography")}
            ${renderCoverageSectionHint("Where your money is invested — percentages add up inside this holding")}
            <div class="country-chips">
              ${data.countries.slice(0, 6).map((c, i) =>
                `<span class="country-chip${i === 0 ? " primary" : ""}" title="${escapeHtml(c.name)}: ${c.weight.toFixed(1)}%">
                   <span class="country-chip-name">${escapeHtml(c.name)}</span>
                   <span class="country-chip-pct">${c.weight.toFixed(0)}%</span>
                 </span>`
              ).join("")}
            </div>
           </div>`
        : "";

    let insideHtml = "";
    if (data.top_holdings && data.top_holdings.length && coverageType !== "equity") {
        const maxBarWeight = Math.max(...data.top_holdings.map(h => h.weight), 1);
        insideHtml = `
            <div class="coverage-section">
                ${renderCoverageDivider("bi-list-task", "Biggest positions inside")}
                ${renderCoverageSectionHint("Largest companies this fund owns — not your whole portfolio")}
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
                </div>
            </div>`;
    } else if (coverageType === "equity" && data.peer_tickers && data.peer_tickers.length) {
        insideHtml = `
            <div class="coverage-section">
                ${renderCoverageDivider("bi-people", "Similar companies")}
                ${renderCoverageSectionHint("Peers in the same industry — useful for comparing moves")}
                <div class="peer-chips">
                  ${data.peer_tickers.slice(0, 6).map(p => `<span class="peer-chip">${escapeHtml(p)}</span>`).join("")}
                </div>
            </div>`;
    }

    const etfProfileHtml = quality && coverageType.startsWith("etf")
        ? `<div class="coverage-section">
            ${renderCoverageDivider("bi-sliders", "Fund quality")}
            ${renderCoverageSectionHint("Quick health check — fees, spread, and how diversified the fund is")}
            <div class="coverage-quality-grid">
              <div class="coverage-quality-card">
                <span class="coverage-quality-label">Overall</span>
                <strong class="spec-pill">${escapeHtml(quality.qualityLabel || "Unknown")}</strong>
              </div>
              <div class="coverage-quality-card">
                <span class="coverage-quality-label">Fees</span>
                <strong class="spec-pill">${escapeHtml(quality.costLabel || "Unknown")}</strong>
              </div>
              <div class="coverage-quality-card">
                <span class="coverage-quality-label">Easy to trade</span>
                <strong>${escapeHtml(quality.liquidityLabel || "Unknown")}</strong>
              </div>
              <div class="coverage-quality-card">
                <span class="coverage-quality-label">Spread</span>
                <strong>${escapeHtml(quality.diversificationLabel || "Unknown")}</strong>
              </div>
              <div class="coverage-quality-card coverage-quality-card--wide">
                <span class="coverage-quality-label">Typical risk</span>
                <strong class="spec-pill risk">${escapeHtml(quality.categoryRiskLabel || "Unknown")}</strong>
              </div>
            </div>
           </div>`
        : "";

    const marketPulseHtml = renderMarketPulseStrip(data);
    const fundScaleHtml = renderFundScaleSpotlight(data, priceSignal);
    const fact = buildHoldingFact(data);
    const missingPulse = data.load_status?.market_pulse?.missing || [];
    const pulseStatusHtml = !marketPulseLoaded(data) && intelligenceExhaustedTickers.has(data.ticker)
        ? `<span class="fact-tag intel-refresh-note"><i class="bi bi-arrow-repeat"></i>Some live metrics are still loading — tap Holding Intel again for the full picture.</span>`
        : missingPulse.length && intelligenceRetryingTickers.has(data.ticker)
            ? `<span class="fact-tag intel-refresh-note"><i class="bi bi-arrow-repeat"></i>Refreshing ${escapeHtml(missingPulse.join(", "))}</span>`
            : "";
    const factTag = fact && !fundScaleHtml
        ? `<span class="fact-tag"><i class="bi bi-stars"></i>${escapeHtml(fact)}</span>` : "";

    const extrasHtml = (fundScaleHtml || marketPulseHtml || factTag || pulseStatusHtml)
        ? `<div class="coverage-extras">
            ${fundScaleHtml}
            ${marketPulseHtml}
            <div class="intel-meta-row">${factTag}${pulseStatusHtml}</div>
           </div>`
        : "";

    const equityDeepDiveHtml = coverageType === "equity"
        ? (_buildEquityFundamentals(data, rating, aiMode) + _buildEquityValueBlock(data, rating, timing))
        : "";

    section.innerHTML = `
        <div class="intel-coverage">
            <div class="intel-label"><i class="bi bi-layers"></i> What It Covers</div>
            ${heroHtml}
            ${sectorBarsHtml}
            ${countryChipsHtml}
            ${insideHtml}
            ${etfProfileHtml}
            ${extrasHtml}
            ${equityDeepDiveHtml}
        </div>`;
    if (data.ticker && _isCoverageRowOpen(section)) {
        _syncDeepIntelSection(section, data.ticker);
    }
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
                <div class="intel-verdict-section"></div>
                <div class="intel-slow-hint" hidden>
                    <i class="bi bi-hourglass-split"></i>
                    Still loading — hit <strong>Holding Intel</strong> in the top-right to run the full scan.
                </div>
                <div class="intel-loading-overlay" aria-hidden="true">
                    <div class="intel-loading-content">
                        <img src="/static/img/brand/folio-orbit-icon.svg" alt="" class="intel-loading-orbit">
                        <div class="intel-loading-title">${escapeHtml(_intelLoadingTitle())}</div>
                        <div class="intel-loading-sub">Context received. Nuance forming. Usually lands in 30-60s.</div>
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
        const verdictSection  = expandRow.querySelector(".intel-verdict-section");

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

        // Verdict section: render shimmer while intel is loading; render card when data arrives
        if (verdictSection) {
            if (intelligenceLoading && !cachedVerdicts[ticker]) {
                renderAiVerdictShimmer(verdictSection, ticker);
            } else {
                renderAiVerdict(verdictSection, cachedVerdicts[ticker], ticker);
            }
        }

        if (holdingIntelSettled(ticker)) {
            mainRow.classList.add("has-intel-ready");
        }
    });
}

function renderExpandedTicker(ticker) {
    const mainRow = document.querySelector(`tr[data-ticker="${CSS.escape(ticker)}"]`);
    if (!mainRow) return;
    const tbody = mainRow.closest("tbody");
    if (tbody) injectSummaryRows(tbody);

    const expandRow = mainRow.nextElementSibling;
    if (!expandRow?.classList.contains("summary-expand-row")) return;
    const coverageSection = expandRow.querySelector(".intel-coverage-section");
    const moveSection = expandRow.querySelector(".intel-move-section");
    const verdictSection = expandRow.querySelector(".intel-verdict-section");
    if (coverageSection) renderHoldingCoverage(coverageSection, cachedIntelligence[ticker]);
    if (moveSection) renderMoveExplainer(moveSection, cachedExplanations[ticker], cachedIntelligence[ticker]);
    if (verdictSection) renderAiVerdict(verdictSection, cachedVerdicts[ticker], ticker);
    if (holdingIntelSettled(ticker)) {
        mainRow.classList.add("has-intel-ready");
        const hint = expandRow.querySelector(".intel-slow-hint");
        if (hint) hint.hidden = true;
    }

    const body = expandRow.querySelector(".summary-body.open");
    if (body && body.style.maxHeight && body.style.maxHeight !== "none") {
        requestAnimationFrame(() => { body.style.maxHeight = body.scrollHeight + "px"; });
    }
}

function _fitCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.offsetWidth  || Math.round(canvas.width  / dpr);
    const h = canvas.offsetHeight || Math.round(canvas.height / dpr);
    canvas.width  = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: w, height: h };
}

function drawTrend(canvas, history = []) {
    const { ctx, width, height } = _fitCanvas(canvas);
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

function renderTargetTrendLine(label, value) {
    if (!isFiniteNumber(value)) return "";
    const tone = signalTone(value);
    return `<div class="target-trend-line ${tone}">
                <span>${escapeHtml(label)}</span>
                <strong>${escapeHtml(formatSignalPct(value))}</strong>
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
            const trendRows = [
                renderTargetTrendLine("30D", trend30),
                renderTargetTrendLine("200D", trend200),
            ].join("");
            const trendHtml = trendRows
                ? `<div class="target-trend-list" aria-label="ETF price trend">${trendRows}</div>`
                : `<div class="target-upside" style="color:var(--text-tertiary)">${escapeHtml(signal.basis || "Price zone")}</div>`;
            return `<div class="target-signal-stack">
                        <div class="target-price-value target-zone-value price-zone-${escapeHtml(zoneClass)}">
                            <span>${escapeHtml(label)}</span>
                            <span>${formatPercentilePct(signal.percentile)}</span>
                        </div>
                        ${trendHtml}
                        ${renderTargetKind("etf", "bi-activity", "ETF signal")}
                    </div>`;
        }
    }
    // Stocks with analyst consensus price target
    if (rec.target_price) {
        const upside = rec.target_upside_pct;
        const tone = signalTone(upside);
        return `<div class="target-signal-stack target-stock-stack">
                    <div class="target-price-value target-stock-value">${formatCurrency(rec.target_price)}</div>
                    <div class="target-stock-upside ${tone}">${escapeHtml(formatSignalPct(upside))}</div>
                    ${renderTargetKind("stock", "bi-bullseye", "Stock target")}
                </div>`;
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

// ── AI Verdict rendering ──────────────────────────────────────────────────

const VERDICT_ICONS = {
    "add":        "bi-arrow-up-circle-fill",
    "hold":       "bi-dash-circle-fill",
    "trim":       "bi-arrow-down-circle-fill",
    "needs-data": "bi-question-circle",
};

const FOLIO_SENSE_VERDICT_COPY = {
    kicker: "FolioSense \u00d7 Claude",
    feelsPrefix: "FolioSense feels",
    unavailable: "Verdict unavailable — tap Holding Intel to refresh.",
    disclaimer:
        "FolioSense Intelligence \u2014 a signal read, not financial advice. Verify before you trade.",
};

function _isAiVerdictActive(verdict) {
    return !!(
        verdict?.ai_enhanced
        && verdict?.ai_enhancement
        && _isClaudeApiLive !== false
        && !_forcedLocalMode
    );
}

function _verdictColor(action) {
    const map = {
        "add":  "var(--accent-green)",
        "hold": "var(--accent-yellow)",
        "trim": "var(--accent-red)",
    };
    return map[action] || "var(--text-tertiary)";
}

function _sanitizeVerdict(verdict) {
    if (!verdict || typeof verdict !== "object") return null;
    const VALID_ACTIONS = new Set(["add", "hold", "trim", "needs-data"]);
    const action = VALID_ACTIONS.has(verdict.action) ? verdict.action : "needs-data";
    const conf = Math.min(100, Math.max(0, Math.round(parseFloat(verdict.confidence) || 0)));
    const label = typeof verdict.label === "string" && verdict.label.trim()
        ? verdict.label.trim().slice(0, 40) : "Needs Data";
    const quip = typeof verdict.quip === "string" ? verdict.quip.trim().slice(0, 300) : "";
    const reasons = (Array.isArray(verdict.reasons) ? verdict.reasons : [])
        .filter(r => typeof r === "string" && r.trim())
        .slice(0, 5)
        .map(r => r.trim().slice(0, 220));
    const risks = (Array.isArray(verdict.risks) ? verdict.risks : [])
        .filter(r => typeof r === "string" && r.trim())
        .slice(0, 4)
        .map(r => r.trim().slice(0, 220));
    const ft = verdict.flip_triggers;
    const addPrice  = ft && isFinite(ft.add_price)  && ft.add_price  > 0 ? ft.add_price  : null;
    const trimPrice = ft && isFinite(ft.trim_price) && ft.trim_price > 0 ? ft.trim_price : null;
    return {
        ...verdict,
        action,
        confidence: conf,
        label,
        quip,
        reasons,
        risks,
        flip_triggers: (addPrice && trimPrice) ? { add_price: addPrice, trim_price: trimPrice } : null,
    };
}

function _verdictLoadingLine(ticker) {
    const seed = String(ticker || "").split("").reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
    if (isLocalIntelligenceMode()) {
        return LOCAL_INTEL_SCAN_MESSAGES[seed % LOCAL_INTEL_SCAN_MESSAGES.length];
    }
    return CLAUDE_FUNNY_MESSAGES[seed % CLAUDE_FUNNY_MESSAGES.length];
}

function _verdictKickerLabel() {
    return isLocalIntelligenceMode()
        ? "FolioSense Intelligence"
        : FOLIO_SENSE_VERDICT_COPY.kicker;
}

function _verdictDisclaimer(verdict) {
    return verdict?.disclaimer || FOLIO_SENSE_VERDICT_COPY.disclaimer;
}

function _verdictBrand(verdict) {
    const brand = verdict?.brand || {};
    const isLocal = isLocalIntelligenceMode() && !_isAiVerdictActive(verdict);
    return {
        kicker: isLocal
            ? _verdictKickerLabel()
            : (brand.kicker || FOLIO_SENSE_VERDICT_COPY.kicker),
        feelsPrefix: isLocal
            ? "The signals suggest"
            : (brand.feels_prefix || brand.feelsPrefix || FOLIO_SENSE_VERDICT_COPY.feelsPrefix),
    };
}

function _verdictIntelIcon() {
    return isLocalIntelligenceMode() ? "bi-cpu-fill" : "bi-dice-5";
}

function _renderLocalOrbital() {
    return `<div class="verdict-local-orbital" aria-hidden="true">
        <span class="verdict-local-orbit-ring"></span>
        <span class="verdict-local-orbit-ring ring-2"></span>
    </div>`;
}

function _localSynthTags(verdict) {
    const mix = verdict?.signal_mix || [];
    return mix
        .filter(item => item.stance === "support" || item.stance === "against")
        .slice(0, 2)
        .map(item => {
            const cls = item.stance === "support" ? "is-support" : "is-against";
            return `<span class="local-synth-tag ${cls}">${escapeHtml(item.label || "Signal")}</span>`;
        })
        .join("");
}

const SYNTH_TAG_GLOSSARY = {
    speculative: { label: "Higher risk", explain: "Upside is possible, but losses could be sharp — keep size small." },
    watch: { label: "Watch first", explain: "Track news and price before committing real money." },
    core: { label: "Core holding", explain: "Stable enough to anchor part of a diversified portfolio." },
    steady: { label: "Steady", explain: "Predictable business with fewer surprises than average." },
    defensive: { label: "Defensive", explain: "Tends to hold up when the broader market falls." },
    momentum: { label: "Trending up", explain: "Recent price action is working in its favor." },
    value: { label: "Good value", explain: "Price looks reasonable compared to fundamentals." },
    crowded: { label: "Crowded trade", explain: "Lots of investors already own it — less room to surprise." },
    growth: { label: "Growth story", explain: "Future expansion matters more than today's profits." },
    income: { label: "Income focus", explain: "Dividends or cash flow are a main reason to own it." },
};

const SYNTH_ACTION_PLAIN = {
    add: "Worth considering a small add when the price looks right.",
    hold: "No strong reason to buy or sell right now — waiting is reasonable.",
    trim: "Consider reducing your position — risks may outweigh the reward.",
    "needs-data": "Not enough reliable data yet to form a confident view.",
};

function _holdingForTicker(ticker) {
    return latestHoldings.find(h => h.ticker === String(ticker || "").toUpperCase()) || null;
}

function _renderSynthTag(tag, variant = "ai") {
    const key = String(tag || "").trim().toLowerCase();
    const entry = SYNTH_TAG_GLOSSARY[key];
    const display = entry?.label || tag;
    const tip = entry?.explain || `Signal tag: ${tag}`;
    const cls = variant === "local" ? "local-synth-tag" : "ai-synth-tag";
    return `<span class="${cls} synth-tag-glossed" title="${escapeHtml(tip)}">${escapeHtml(display)}</span>`;
}

function _synthPlainSummary(verdict, ai, ticker) {
    if (ai?.plain_summary) return ai.plain_summary.trim();

    const holding = _holdingForTicker(ticker);
    const parts = [];
    if (holding?.is_watchlist) {
        parts.push("This is on your research list — no real money is invested yet.");
    }
    const action = verdict?.action || "hold";
    parts.push(SYNTH_ACTION_PLAIN[action] || SYNTH_ACTION_PLAIN.hold);

    const note = (ai?.note || "").trim();
    const headline = (ai?.headline || "").trim();
    if (note) parts.push(note);
    else if (headline) parts.push(headline);
    else {
        const reason = (verdict?.reasons || [])[0];
        if (reason) parts.push(reason);
    }
    return parts.join(" ");
}

function _localSynthPlainSummary(verdict, ticker) {
    const holding = _holdingForTicker(ticker);
    const parts = [];
    if (holding?.is_watchlist) {
        parts.push("This is on your research list — no real money is invested yet.");
    }
    const action = verdict?.action || "hold";
    parts.push(SYNTH_ACTION_PLAIN[action] || SYNTH_ACTION_PLAIN.hold);
    const reason = (verdict?.reasons || [])[0];
    if (reason) parts.push(reason);
    return parts.join(" ");
}

function _renderSynthPlainCallout(text, variant = "ai") {
    if (!text) return "";
    return `<div class="synth-plain-callout is-${variant}">
        <span class="synth-plain-label">What this means</span>
        <p class="synth-plain-text">${escapeHtml(text)}</p>
    </div>`;
}

function _renderLocalSynthesisPanel(verdict, ticker = "") {
    if (!isLocalIntelligenceMode() || _isAiVerdictActive(verdict)) return "";
    const detail = verdict?.confidence_detail || {};
    const headline = (detail.summary || `${verdict.label || "Hold"} — ${detail.level || "mixed signals"}`).slice(0, 120);
    const note = (verdict.reasons || [])[0] || "";
    const tags = _localSynthTags(verdict);
    const score = verdict.confidence;
    const plain = _localSynthPlainSummary(verdict, ticker);

    return `<div class="verdict-synthesis-panel is-local">
        <div class="verdict-synthesis-head">
            <span class="synth-kicker"><i class="bi bi-cpu-fill" aria-hidden="true"></i> Local read</span>
            ${_verdictTip({
                title: "What this panel is",
                body: "A quick summary built on your device from analyst views, price level, trend, and quality — no cloud AI. The radar shows how balanced those four inputs are.",
                icon: "bi-cpu-fill",
                variant: "local",
            })}
            <span class="synth-score-badge">${Math.round(score || 0)}%</span>
        </div>
        ${_renderSynthPlainCallout(plain, "local")}
        ${headline ? `<div class="synth-headline"><span class="synth-headline-label">Quick take</span> ${escapeHtml(headline)}</div>` : ""}
        ${tags ? `<div class="synth-tags">${tags}</div>` : ""}
        ${note && note !== plain ? `<p class="synth-note"><span class="synth-note-label">Detail</span> ${escapeHtml(note)}</p>` : ""}
        <p class="synth-radar-caption">Balance of expert views, price, trend, and quality</p>
        ${_renderSignalRadarMarkup(verdict, "local")}
    </div>`;
}

function _renderSynthesisPanel(verdict, ticker = "") {
    if (_isAiVerdictActive(verdict)) return _renderAiSynthesisPanel(verdict, ticker);
    return _renderLocalSynthesisPanel(verdict, ticker);
}

function _verdictTip({ title, body, hint = "", icon = "bi-info-circle-fill", variant = "" }) {
    return `<button class="tip-trigger target-tip-trigger" type="button"
        aria-label="${escapeHtml(title)}"
        data-tip-title="${escapeHtml(title)}"
        data-tip-body="${escapeHtml(body)}"
        ${hint ? `data-tip-hint="${escapeHtml(hint)}"` : ""}
        data-tip-icon="${escapeHtml(icon)}"
        ${variant ? `data-tip-variant="${escapeHtml(variant)}"` : ""}>
        <i class="bi bi-info-circle" aria-hidden="true"></i>
    </button>`;
}

function _verdictInfoTip() {
    const isLocal = isLocalIntelligenceMode();
    return _verdictTip({
        title: isLocal ? "How local intelligence works" : "How FolioSense decides",
        body: isLocal
            ? "Purely on your machine — analyst data, price zones, trend, and quality are weighted into Add, Hold, or Trim. No cloud calls. Same math every time, fully explainable via the bars below."
            : "It blends the signals that fit each holding — analyst consensus for stocks, price-zone and fund quality for ETFs — with the recent trend and your position size. It defaults to Hold and only leans Add or Trim when the evidence clearly points there.",
        hint: "Re-scan to refresh on the latest prices. Not financial advice.",
        icon: isLocal ? "bi-cpu-fill" : "bi-dice-5-fill",
    });
}

function _confidenceTip(isAi) {
    return _verdictTip({
        title: isAi ? "AI signal strength" : "Signal strength",
        body: isAi
            ? "One number summarizing how strongly the inputs agree — after Claude's tiny, bounded adjustments. Higher = more conviction in the Add, Hold, or Trim call."
            : "One number from four inputs: expert views, price vs history, recent trend, and quality. 45–60 on a Hold is normal — it means nothing is shouting.",
        icon: isAi ? "bi-stars" : "bi-speedometer2",
        variant: isAi ? "ai" : "",
    });
}

function _renderAiDeltaBadge(verdict) {
    const ai = verdict?.ai_enhancement;
    if (!_isAiVerdictActive(verdict) || !ai || !Number.isFinite(ai.delta) || ai.delta === 0) return "";
    const sign = ai.delta > 0 ? "+" : "";
    return `<span class="verdict-ai-delta" title="Claude adjustment vs local">${sign}${ai.delta} AI</span>`;
}

function _renderAiSynthesisPanel(verdict, ticker = "") {
    if (!_isAiVerdictActive(verdict)) return "";
    const ai = verdict.ai_enhancement;
    const headline = ai.headline || "";
    const note = ai.note || "";
    const tags = (ai.tags || []).slice(0, 2);
    const localScore = ai.local_score;
    const aiScore = ai.ai_score;
    const plain = _synthPlainSummary(verdict, ai, ticker);

    const tagHtml = tags.map(tag => _renderSynthTag(tag, "ai")).join("");

    const compareHtml = Number.isFinite(localScore) && Number.isFinite(aiScore)
        ? `<span class="ai-synth-compare" title="How much Claude adjusted the signal strength score">Local ${localScore}% → AI ${aiScore}%</span>`
        : "";

    return `<div class="verdict-synthesis-panel is-ai">
        <div class="verdict-synthesis-head">
            <span class="synth-kicker"><i class="bi bi-stars" aria-hidden="true"></i> Claude's second read</span>
            ${_verdictTip({
                title: "What this panel is",
                body: "Claude reviews the same stats FolioSense already computed — headline, tags, and a short note. It can nudge the score slightly but cannot invent prices or new data. Cached 24h.",
                icon: "bi-stars",
                variant: "ai",
            })}
            ${compareHtml}
        </div>
        ${_renderSynthPlainCallout(plain, "ai")}
        ${headline ? `<div class="synth-headline"><span class="synth-headline-label">Quick take</span> ${escapeHtml(headline)}</div>` : ""}
        ${tagHtml ? `<div class="synth-tags">${tagHtml}</div>` : ""}
        ${note && note !== plain ? `<p class="synth-note"><span class="synth-note-label">Supporting detail</span> ${escapeHtml(note)}</p>` : ""}
        <p class="synth-radar-caption">Balance of expert views, price, trend, and quality</p>
        ${_renderSignalRadarMarkup(verdict, "ai")}
    </div>`;
}

function _renderSignalRadarMarkup(verdict, variant = "ai", compact = false) {
    const components = verdict?.confidence_detail?.components;
    if (!Array.isArray(components) || components.length < 4) return "";
    const scores = components.slice(0, 4).map(c => Math.min(100, Math.max(0, Number(c.score) || 0)));
    const cx = 50;
    const cy = 50;
    const maxR = compact ? 34 : 38;
    const angles = [-90, 0, 90, 180];
    const labels = ["Experts", "Price", "Trend", "Quality"];

    const poly = scores.map((score, i) => {
        const rad = (angles[i] * Math.PI) / 180;
        const r = (score / 100) * maxR;
        return `${cx + r * Math.cos(rad)},${cy + r * Math.sin(rad)}`;
    }).join(" ");

    const rings = [0.35, 0.65, 1].map(scale => {
        const pts = angles.map(deg => {
            const rad = (deg * Math.PI) / 180;
            const r = maxR * scale;
            return `${cx + r * Math.cos(rad)},${cy + r * Math.sin(rad)}`;
        }).join(" ");
        return `<polygon class="ai-radar-ring" points="${pts}"></polygon>`;
    }).join("");

    const spokes = angles.map(deg => {
        const rad = (deg * Math.PI) / 180;
        return `<line class="ai-radar-spoke" x1="${cx}" y1="${cy}" x2="${cx + maxR * Math.cos(rad)}" y2="${cy + maxR * Math.sin(rad)}"></line>`;
    }).join("");

    const labelNodes = compact ? "" : angles.map((deg, i) => {
        const textAnchors = ["middle", "start", "middle", "end"];
        const rad = (deg * Math.PI) / 180;
        const lx = cx + (maxR + 8) * Math.cos(rad);
        const ly = cy + (maxR + 8) * Math.sin(rad);
        return `<text class="ai-radar-label" x="${lx}" y="${ly}" text-anchor="${textAnchors[i]}" dominant-baseline="middle">${labels[i]}</text>`;
    }).join("");

    const viewBox = compact ? "8 8 84 84" : "-32 -14 164 128";
    const compactCls = compact ? " is-compact" : "";

    return `<div class="signal-radar-wrap is-${variant}${compactCls}">
        <svg class="signal-radar" viewBox="${viewBox}" role="img" aria-label="Signal balance radar">
            ${rings}
            ${spokes}
            <polygon class="signal-radar-fill" points="${poly}"></polygon>
            <polygon class="signal-radar-stroke" points="${poly}"></polygon>
            ${labelNodes}
        </svg>
    </div>`;
}

function _renderAiRadarArtifact(verdict) {
    return _renderSignalRadarMarkup(verdict, "ai");
}

let _lastExpandedHoldingTicker = null;

function _isHoldingRowOpen(section) {
    const expandRow = section?.closest(".summary-expand-row");
    const mainRow = expandRow?.previousElementSibling;
    return !!mainRow?.classList.contains("summary-open");
}

function _syncVerdictCharts(section, verdict, ticker) {
    if (!section || !verdict) return;
    section._chartVerdict = verdict;
    section._chartTicker = ticker;
    if (_isHoldingRowOpen(section)) {
        _paintVerdictSparkline(section, verdict, ticker);
    }
}

/**
 * Scroll a holding's title row to just beneath the sticky navbar.
 * No-op when the title is already comfortably in view, so collapsing a row
 * you just opened doesn't trigger a jarring jump.
 */
function scrollHoldingTitleIntoView(row) {
    if (!row) return;
    const navbar = document.querySelector("body > .navbar");
    const navH = navbar ? navbar.offsetHeight : 0;
    const rect = row.getBoundingClientRect();
    if (rect.top >= navH + 4 && rect.bottom <= window.innerHeight) return;
    const top = Math.max(0, window.scrollY + rect.top - navH - 14);
    window.scrollTo({ top, behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

function initHoldingExpandFab() {
    if (document.getElementById("holding-expand-fab")) return;
    const fab = document.createElement("button");
    fab.id = "holding-expand-fab";
    fab.type = "button";
    fab.className = "holding-expand-fab";
    fab.setAttribute("aria-hidden", "true");
    fab.innerHTML = `<i class="bi bi-chevron-up" aria-hidden="true"></i><span class="holding-expand-fab-label"></span>`;
    fab.addEventListener("click", () => {
        const openRows = [...document.querySelectorAll("#holdings-table tr[data-ticker].summary-open")];
        if (openRows.length) {
            // Anchor to the topmost open row so the view returns to its title
            // after the section(s) collapse.
            const anchor = openRows[0];
            openRows.forEach(row => toggleSummaryRow(row));
            scrollHoldingTitleIntoView(anchor);
            return;
        }
        const ticker = _lastExpandedHoldingTicker;
        if (!ticker) return;
        const row = document.querySelector(`#holdings-table tr[data-ticker="${CSS.escape(ticker)}"]`);
        if (row && !row.classList.contains("summary-open")) {
            toggleSummaryRow(row);
            row.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "nearest" });
        }
    });
    document.body.appendChild(fab);
}

function syncHoldingExpandFab() {
    const fab = document.getElementById("holding-expand-fab");
    if (!fab) return;
    const openRows = [...document.querySelectorAll("#holdings-table tr[data-ticker].summary-open")];
    const icon = fab.querySelector("i");
    const labelEl = fab.querySelector(".holding-expand-fab-label");

    if (dashboardZone !== "holdings") {
        fab.classList.remove("is-visible", "is-open-mode");
        fab.setAttribute("aria-hidden", "true");
        return;
    }

    if (openRows.length) {
        const label = openRows.length === 1
            ? `Collapse ${openRows[0].dataset.ticker || "holding"}`
            : `Collapse ${openRows.length} holdings`;
        if (icon) icon.className = "bi bi-chevron-up";
        labelEl.textContent = label;
        fab.setAttribute("aria-label", label);
        fab.classList.add("is-visible", "is-open-mode");
        fab.setAttribute("aria-hidden", "false");
        return;
    }

    if (_lastExpandedHoldingTicker) {
        const label = `Open ${_lastExpandedHoldingTicker}`;
        if (icon) icon.className = "bi bi-chevron-down";
        labelEl.textContent = label;
        fab.setAttribute("aria-label", label);
        fab.classList.add("is-visible");
        fab.classList.remove("is-open-mode");
        fab.setAttribute("aria-hidden", "false");
        return;
    }

    fab.classList.remove("is-visible", "is-open-mode");
    fab.setAttribute("aria-hidden", "true");
}

function _renderAiOrbital(conf) {
    return `<div class="verdict-ai-orbital" aria-hidden="true">
        <span class="verdict-ai-orbit-ring"></span>
        <span class="verdict-ai-orbit-ring ring-2"></span>
    </div>`;
}

function _confidenceLevelClass(level) {
    const key = String(level || "").toLowerCase();
    if (key.includes("strong")) return "is-strong";
    if (key.includes("moderate")) return "is-moderate";
    if (key.includes("mixed")) return "is-mixed";
    if (key.includes("low") || key.includes("uncertain")) return "is-low";
    return "";
}

function _renderConfidenceStats(verdict) {
    const detail = verdict?.confidence_detail;
    if (!detail?.components?.length) return "";

    const isAi = _isAiVerdictActive(verdict);
    const isLocal = isLocalIntelligenceMode() && !isAi;
    const level = detail.level || "Mixed signals";
    const summary = detail.summary || "";
    const levelClass = _confidenceLevelClass(level);
    const panelClass = isAi ? " is-ai-refined" : (isLocal ? " is-local-refined" : "");

    const bars = detail.components.map(comp => {
        const stance = ["support", "neutral", "against"].includes(comp.stance)
            ? comp.stance
            : "neutral";
        const score = Math.min(100, Math.max(0, Math.round(comp.score || 0)));
        const nudge = Number(comp.ai_nudge);
        const meta = _VERDICT_COMP_META[comp.key] || { icon: "bi-circle-fill", layman: "" };
        const nudgeHtml = isAi && Number.isFinite(nudge) && nudge !== 0
            ? `<span class="conf-stat-nudge">${nudge > 0 ? "+" : ""}${nudge}</span>`
            : "";
        const tip = _verdictTip({
            title: comp.tip_title || comp.label,
            body: isAi && Number.isFinite(comp.local_score)
                ? `${comp.tip_body || meta.layman} Local was ${comp.local_score}%; Claude nudged ${nudge > 0 ? "+" : ""}${nudge || 0}.`
                : (comp.tip_body || meta.layman),
            icon: meta.icon,
            variant: isAi ? "ai" : "",
        });
        const stanceLabel = { support: "Helps the call", neutral: "Neutral", against: "Pushes back" }[stance];
        return `<div class="conf-stat-row" data-stance="${escapeHtml(stance)}">
            <div class="conf-stat-head">
                <span class="conf-stat-label">
                    <i class="bi ${meta.icon} conf-stat-icon" aria-hidden="true"></i>
                    <span class="conf-stat-label-text">
                        <span class="conf-stat-name">${escapeHtml(comp.label || "Signal")}</span>
                        <span class="conf-stat-layman">${escapeHtml(meta.layman)}</span>
                    </span>
                </span>
                <span class="conf-stat-score">${score}%${nudgeHtml}${tip}</span>
            </div>
            <div class="conf-stat-bar" role="presentation">
                <div class="conf-stat-bar-fill" style="width:${score}%"></div>
            </div>
            <span class="conf-stat-stance">${escapeHtml(stanceLabel)}</span>
        </div>`;
    }).join("");

    const modifiers = (detail.modifiers || []).filter(m => m.delta).map(mod => {
        const sign = mod.delta > 0 ? "+" : "";
        const isClaude = String(mod.label || "").toLowerCase().includes("claude");
        return `<span class="conf-mod-chip${isClaude ? " is-ai-mod" : ""}">
            ${escapeHtml(mod.label || "Adjustment")} ${sign}${mod.delta}
            ${_verdictTip({
                title: mod.tip_title || mod.label,
                body: mod.tip_body || "",
                icon: isClaude ? "bi-stars" : "bi-sliders",
                variant: isClaude ? "ai" : "",
            })}
        </span>`;
    }).join("");

    const agreement = detail.agreement || {};
    const agreeParts = [];
    if (agreement.supporting) agreeParts.push(`${agreement.supporting} agree`);
    if (agreement.neutral) agreeParts.push(`${agreement.neutral} neutral`);
    if (agreement.opposing) agreeParts.push(`${agreement.opposing} disagree`);
    const agreeCopy = agreeParts.length ? agreeParts.join(" · ") : "";

    return `<div class="verdict-confidence-panel ${levelClass}${panelClass}">
        <div class="verdict-confidence-head">
            <span class="verdict-confidence-level">${escapeHtml(level)}</span>
            ${_verdictTip({
                title: isAi ? "AI-refined score" : "How to read this",
                body: isAi
                    ? "Bars start from local inputs, then show Claude's tiny per-input nudges. The headline score is the re-weighted result — still bounded and explainable."
                    : "Each bar shows how strongly one input supports the verdict (0 = weak, 100 = strong). The big number is the weighted blend. A Hold in the 45–60 range is normal — it means no input is shouting.",
                icon: isAi ? "bi-stars" : "bi-pie-chart-fill",
                variant: isAi ? "ai" : "",
            })}
        </div>
        ${summary ? `<p class="verdict-confidence-summary">${escapeHtml(summary)}</p>` : ""}
        <div class="conf-stats-grid">${bars}</div>
        ${agreeCopy ? `<div class="conf-agreement-row">
            <span class="conf-agreement-label"><i class="bi bi-ui-checks"></i> Quick read</span>
            <span class="conf-agreement-copy">${escapeHtml(agreeCopy)}</span>
            ${_verdictTip({
                title: "Inputs at a glance",
                body: "How many of the four signals agree with the verdict, sit neutral, or push the other way.",
                icon: "bi-ui-checks",
            })}
        </div>` : ""}
        ${modifiers ? `<div class="conf-mod-row">${modifiers}</div>` : ""}
    </div>`;
}

function _renderVerdictSparkline(verdict, ticker) {
    const points = verdict?.timing?.sparkline_30d;
    const hasApiPoints = Array.isArray(points) && points.length >= 2;
    const trendHistory = latestTrendData[ticker];
    const useTrend = !hasApiPoints && Array.isArray(trendHistory) && trendHistory.length >= 2;
    if (!hasApiPoints && !useTrend) return "";

    return `<div class="verdict-sparkline-wrap">
        <div class="verdict-sparkline-head">
            <span class="verdict-face-label"><i class="bi bi-graph-up" aria-hidden="true"></i> Last 30 days</span>
            ${_verdictTip({
                title: "Price path",
                body: "How the price moved over the last month. Green = up vs the start; red = down. Same data as the holdings table sparkline.",
                icon: "bi-graph-up",
            })}
        </div>
        <canvas class="verdict-sparkline" width="280" height="56"
            aria-label="${escapeHtml(ticker)} 30-day price trend"></canvas>
    </div>`;
}

function _paintVerdictSparkline(section, verdict, ticker) {
    const canvas = section.querySelector("canvas.verdict-sparkline");
    if (!canvas) return;
    const apiPoints = verdict?.timing?.sparkline_30d;
    if (Array.isArray(apiPoints) && apiPoints.length >= 2) {
        _drawPctSparkline(canvas, apiPoints);
        return;
    }
    const history = latestTrendData[ticker];
    if (Array.isArray(history) && history.length >= 2) {
        drawTrend(canvas, history);
    }
}

function _drawPctSparkline(canvas, pctSeries = []) {
    const { ctx, width, height } = _fitCanvas(canvas);
    const padding = 4;
    const values = pctSeries.filter(v => Number.isFinite(v));
    ctx.clearRect(0, 0, width, height);
    if (values.length < 2) return;

    const min = Math.min(...values, 0);
    const max = Math.max(...values, 0);
    const range = max - min || 1;
    const isPositive = values[values.length - 1] >= values[0];
    const lineColor = isPositive
        ? (cssVar("--accent-green") || "#30d158")
        : (cssVar("--accent-red") || "#ff453a");

    const coords = values.map((val, index) => ({
        x: padding + (index * (width - padding * 2)) / (values.length - 1),
        y: height - padding - ((val - min) / range) * (height - padding * 2),
    }));

    const fillGrad = ctx.createLinearGradient(0, 0, 0, height);
    fillGrad.addColorStop(0, isPositive ? "rgba(48,209,88,0.24)" : "rgba(255,69,58,0.24)");
    fillGrad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.beginPath();
    coords.forEach(({ x, y }, i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.lineTo(coords[coords.length - 1].x, height);
    ctx.lineTo(coords[0].x, height);
    ctx.closePath();
    ctx.fillStyle = fillGrad;
    ctx.fill();

    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.8;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    coords.forEach(({ x, y }, i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();

    const zeroY = height - padding - ((0 - min) / range) * (height - padding * 2);
    ctx.strokeStyle = cssVar("--hairline-soft") || "rgba(255,255,255,0.12)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(padding, zeroY);
    ctx.lineTo(width - padding, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);
}

const _HOLD_MODE_ORDER = ["auto", "trade", "core", "anchor"];

const _HOLD_MODE_META = {
    auto: {
        label: "Auto",
        icon: "bi-sliders2",
        tipTitle: "Standard mode",
        tipBody:
            "FolioSense uses its normal mix of expert views, price, trend, and quality. "
            + "A good default for most holdings — balanced between recent moves and long-term value.",
    },
    trade: {
        label: "Trade",
        icon: "bi-hourglass-split",
        tipTitle: "Trade mode",
        tipBody:
            "For positions you might adjust over the next few weeks. Recent price trend counts more; "
            + "long-term valuation a bit less. You may see more Add or Trim nudges when the chart moves.",
    },
    core: {
        label: "Core",
        icon: "bi-gem",
        tipTitle: "Core mode",
        tipBody:
            "For slow, long-term builds you plan to keep for years. Quality and fair price matter most; "
            + "day-to-day swings count less — fewer flip-flops on short-term noise.",
    },
    anchor: {
        label: "Anchor",
        icon: "bi-pin-angle-fill",
        tipTitle: "Anchor mode",
        tipBody:
            "Marks a holding you do not want to sell down. FolioSense will never suggest trimming it — "
            + "only good moments to add more when price dips. Your weight in the portfolio still shows as usual.",
    },
};

const _VERDICT_PILL_TIPS = {
    add: {
        title: "Add suggestion",
        body:
            "Signals look favorable for building this position — price, trend, and expert views lean positive. "
            + "This is a read on today’s data, not a command to buy.",
    },
    hold: {
        title: "Hold suggestion",
        body:
            "Nothing strong enough to add or trim right now. FolioSense’s default when the evidence is mixed "
            + "or only mildly tilted one way.",
    },
    trim: {
        title: "Trim suggestion",
        body:
            "Signals lean toward reducing exposure — rich price, fading trend, or crowded weight. "
            + "Anchor mode overrides this and never suggests trimming.",
    },
    "needs-data": {
        title: "Needs more data",
        body: "Not enough live data to make a call yet. Expand the row after prices refresh or check coverage.",
    },
};

function _renderHoldModeStrip(verdict, ticker) {
    const holding = latestHoldings.find(h => h.ticker === ticker);
    if (!holding?.id) return "";
    const active = verdict?.hold_class || holding.hold_class || "auto";
    const holdingId = holding.id;
    const tickerArg = inlineJsString(ticker);

    const segments = _HOLD_MODE_ORDER.map((mode, index) => {
        const meta = _HOLD_MODE_META[mode];
        const isActive = active === mode;
        const sep = index > 0 ? `<span class="hold-mode-sep" aria-hidden="true">|</span>` : "";
        return `${sep}<button type="button"
            class="hold-mode-seg tip-trigger${isActive ? " is-active" : ""}"
            role="radio"
            aria-checked="${isActive ? "true" : "false"}"
            data-hold-mode="${mode}"
            data-tip-title="${escapeHtml(meta.tipTitle)}"
            data-tip-body="${escapeHtml(meta.tipBody)}"
            data-tip-icon="${escapeHtml(meta.icon)}"
            onclick="setHoldMode(event, ${holdingId}, ${tickerArg}, ${inlineJsString(mode)})">
            <i class="bi ${escapeHtml(meta.icon)}" aria-hidden="true"></i> ${escapeHtml(meta.label)}
        </button>`;
    }).join("");

    return `<span class="verdict-anchor-sep" aria-hidden="true">|</span>
        <div class="hold-mode-strip" role="radiogroup" aria-label="How FolioSense treats this holding">${segments}</div>`;
}

function _syncHoldModeStrip(ticker, holdClass) {
    const mainRow = document.querySelector(`tr[data-ticker="${CSS.escape(ticker)}"]`);
    const strip = mainRow?.nextElementSibling?.querySelector(".hold-mode-strip");
    if (!strip) return;
    strip.querySelectorAll(".hold-mode-seg").forEach(btn => {
        const active = btn.dataset.holdMode === holdClass;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-checked", String(active));
    });
}

function _manageHoldModeCardClass(mode) {
    if (mode === "anchor") return "is-anchor";
    if (mode === "trade") return "is-hold-mode-trade";
    if (mode === "core") return "is-hold-mode-core";
    return "";
}

function _renderManageHoldModeSection(h) {
    const active = h.hold_class || "auto";
    const holdingId = h.id;
    const tickerArg = inlineJsString(h.ticker);
    const activeMeta = _HOLD_MODE_META[active] || _HOLD_MODE_META.auto;

    const boxes = _HOLD_MODE_ORDER.map(mode => {
        const meta = _HOLD_MODE_META[mode];
        const isActive = active === mode;
        return `<button type="button"
            class="manage-hold-mode-box tip-trigger${isActive ? " is-active" : ""}"
            role="radio"
            aria-checked="${isActive ? "true" : "false"}"
            data-hold-mode="${mode}"
            data-tip-title="${escapeHtml(meta.tipTitle)}"
            data-tip-body="${escapeHtml(meta.tipBody)}"
            data-tip-icon="${escapeHtml(meta.icon)}"
            onclick="setHoldMode(event, ${holdingId}, ${tickerArg}, ${inlineJsString(mode)})">
            <i class="bi ${escapeHtml(meta.icon)}" aria-hidden="true"></i>
            <span class="manage-hold-mode-box-label">${escapeHtml(meta.label)}</span>
        </button>`;
    }).join("");

    return `<div class="manage-hold-mode-section" data-hold-mode="${escapeHtml(active)}">
        <span class="manage-hold-mode-heading">How FolioSense reads this holding</span>
        <div class="manage-hold-mode-grid" role="radiogroup" aria-label="Holding mode for ${escapeHtml(h.ticker)}">
            ${boxes}
        </div>
        <p class="manage-hold-mode-detail" id="hold-mode-detail-${holdingId}">
            <strong>${escapeHtml(activeMeta.tipTitle)}.</strong> ${escapeHtml(activeMeta.tipBody)}
        </p>
    </div>`;
}

function _syncManageHoldModeCard(holdingId, holdClass) {
    const card = document.getElementById(`manage-row-${holdingId}`);
    if (!card) return;
    const mode = _HOLD_MODE_META[holdClass] ? holdClass : "auto";
    const meta = _HOLD_MODE_META[mode];

    card.dataset.holdMode = mode;
    card.classList.remove("is-anchor", "is-hold-mode-trade", "is-hold-mode-core");
    const modeClass = _manageHoldModeCardClass(mode);
    if (modeClass) card.classList.add(modeClass);

    card.querySelectorAll(".manage-hold-mode-box").forEach(btn => {
        const active = btn.dataset.holdMode === mode;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-checked", String(active));
    });

    const section = card.querySelector(".manage-hold-mode-section");
    if (section) section.dataset.holdMode = mode;

    const detail = card.querySelector(".manage-hold-mode-detail");
    if (detail) {
        detail.innerHTML = `<strong>${escapeHtml(meta.tipTitle)}.</strong> ${escapeHtml(meta.tipBody)}`;
    }
}

function _shouldShowBookExposure(ticker) {
    if (!cachedPortfolioExposure?.sector_exposure?.length) return false;
    const live = latestHoldings.filter(h => !h.is_watchlist);
    if (!live.length) return false;
    const top = live.reduce((a, b) =>
        (Number(a.allocation_pct) || 0) >= (Number(b.allocation_pct) || 0) ? a : b
    );
    return top.ticker === ticker;
}

function _renderContextChip(chip) {
    if (!chip?.value) return "";
    return `<span class="verdict-context-chip ${escapeHtml(chip.cls || "")}">
        <i class="bi ${escapeHtml(chip.icon)}" aria-hidden="true"></i>
        <span class="chip-label">${escapeHtml(chip.label)}</span>
        <span class="chip-value">${escapeHtml(chip.value)}</span>
        ${_verdictTip({
            title: chip.tipTitle || chip.label,
            body: chip.tipBody || "",
            icon: chip.icon,
        })}
    </span>`;
}

function _sectorFlags(intel) {
    const names = (intel?.sectors || []).map(s => String(s.name || "").toLowerCase());
    const theme = String(intel?.theme || "").toLowerCase();
    const coverage = String(intel?.coverage_type || "").toLowerCase();
    const blob = [...names, theme, coverage].join(" ");
    return {
        isGrowth: /tech|growth|discretionary|communication|semiconductor|innovation|nasdaq/.test(blob),
        isDefensive: /util|staple|health|consumer defensive|bond|treasury|dividend/.test(blob),
        isRateSensitive: /real estate|reit|utility|financial|bond|treasury|mortgage/.test(blob),
        isIntl: /international|emerging|global|europe|japan|china|fx|ex-us/.test(blob),
        topSector: intel?.sectors?.[0]?.name || null,
    };
}

function _holdingMacroContextChip(ticker, verdict, intel) {
    const regime = verdict?.regime_context || cachedMarketRegime;
    if (!regime?.label) return null;
    const risk = regime.risk_regime || "neutral";
    const rates = regime.rates_regime || "rates_flat";
    const vix = regime.vix_band || "normal";
    const usd = regime.usd_regime || "usd_neutral";
    const flags = _sectorFlags(intel);
    const toneCls = _REGIME_CHIP_CLASS[risk] || "is-neutral";
    let value = "";
    let tipBody = "";

    if (vix === "elevated") {
        value = "Vol high · wider swings";
        tipBody = `Fear gauge is elevated. ${ticker} may gap more on headlines — momentum weighs less in this verdict.`;
    } else if (risk === "risk_off" && flags.isGrowth) {
        value = "Risk-off · hits growth";
        tipBody = `Risk appetite is cooling. Growth-heavy exposure like ${ticker} usually scores weaker on momentum right now.`;
    } else if (risk === "risk_off" && flags.isDefensive) {
        value = "Risk-off · favors defensive";
        tipBody = `Defensive exposure like ${ticker} tends to hold up better when SPY is soft — quality gets a boost.`;
    } else if (risk === "risk_on" && flags.isGrowth) {
        value = "Risk-on · growth tailwind";
        tipBody = `Risk appetite is improving. Growth beta in ${ticker} gets a friendlier momentum read.`;
    } else if (rates === "rates_rising" && flags.isRateSensitive) {
        value = "Rates up · sensitivity";
        tipBody = `Bond yields are rising. Rate-sensitive exposure like ${ticker} faces a tougher valuation read.`;
    } else if (rates === "rates_falling" && (flags.isGrowth || flags.isRateSensitive)) {
        value = "Rates easing · helps duration";
        tipBody = `Falling rates ease pressure on longer-duration assets — a modest tailwind for ${ticker}.`;
    } else if (usd === "usd_strong" && flags.isIntl) {
        value = "Strong USD · intl drag";
        tipBody = `A strong dollar often pressures international earnings — relevant for ${ticker}'s geographic mix.`;
    } else if (usd === "usd_weak" && flags.isIntl) {
        value = "Weak USD · helps intl";
        tipBody = `A softer dollar tends to help non-US revenue — a small tailwind for ${ticker}.`;
    } else if (flags.topSector && risk !== "neutral") {
        const adj = regime.component_adjustments || {};
        const layman = { analyst: "analyst views", valuation: "valuation", momentum: "trend", quality: "quality" };
        const boosts = Object.entries(adj).filter(([, v]) => v > 0).map(([k]) => layman[k] || k);
        if (boosts.length) {
            value = `Macro tilts ${boosts[0]}`;
            tipBody = `Today's backdrop boosts ${boosts.join(" & ")} for ${ticker} — ${flags.topSector} is the live sector read.`;
        }
    }

    if (!value) return null;
    return {
        label: "Macro",
        value,
        icon: "bi-globe-americas",
        tipTitle: `${ticker} macro read`,
        tipBody: tipBody || regime.tip_body,
        cls: `verdict-regime-chip ${toneCls}`,
    };
}

function _collectVerdictContextChips(verdict, ticker) {
    const chips = [];
    const intel = cachedIntelligence[ticker];
    const holding = latestHoldings.find(h => h.ticker === ticker);

    const ev = verdict?.events;
    if (ev?.label) {
        chips.push({
            label: "Event",
            value: ev.label,
            icon: "bi-calendar-event",
            tipTitle: ev.tip_title || "Upcoming event",
            tipBody: ev.tip_body || "Earnings and other events add uncertainty.",
            cls: "verdict-event-chip",
        });
    }

    const exp = verdict?.exposure_context;
    if (exp?.sector_already_heavy?.name) {
        const sec = exp.sector_already_heavy;
        chips.push({
            label: "Book",
            value: `${sec.name} ${Math.round(sec.weight_pct)}%`,
            icon: "bi-pie-chart",
            tipTitle: "Portfolio overlap",
            tipBody: `You already have ${Number(sec.weight_pct).toFixed(0)}% in ${sec.name}. Adding ${ticker} stacks that same bet.`,
            cls: "verdict-exposure-chip",
        });
    } else if (exp?.crowded_themes?.[0]) {
        const theme = exp.crowded_themes[0];
        chips.push({
            label: "Overlap",
            value: theme.label || theme.theme || "Crowded theme",
            icon: "bi-intersect",
            tipTitle: "Theme overlap",
            tipBody: exp.add_penalty_reason
                ? `Your book already leans ${exp.add_penalty_reason}.`
                : "This holding overlaps a crowded theme in your portfolio.",
            cls: "verdict-exposure-chip",
        });
    }

    const peer = verdict?.peer_relative;
    const rec = cachedRecommendations[ticker];
    const zone = rec?.price_signal?.priceZoneLabel;
    const hasPeerCard = Boolean(peer?.vs_own_range || (peer?.peer_comparison && peer.peer_comparison !== "unavailable"));
    if (!hasPeerCard && zone && zone !== "Unavailable" && rec?.price_signal?.percentile != null) {
        chips.push({
            label: "Price zone",
            value: `${zone} · ${formatPercentilePct(rec.price_signal.percentile)}`,
            icon: "bi-activity",
            tipTitle: "Price vs history",
            tipBody: `Trading at ${formatPercentilePct(rec.price_signal.percentile)} of its 1-year range — ${zone.toLowerCase()} zone.`,
            cls: "verdict-valuation-chip",
        });
    }

    const timing = verdict?.timing;
    const trendLabels = {
        trend_intact: "Trend intact",
        stabilizing: "Stabilizing",
        rolling_over: "Rolling over",
        weakening: "Below averages",
        neutral: "No clear trend",
    };
    if (timing?.available && timing.momentum_state) {
        let trendValue = trendLabels[timing.momentum_state] || timing.momentum_state;
        if (Number.isFinite(timing.vs50d_pct)) {
            const sign = timing.vs50d_pct >= 0 ? "+" : "";
            trendValue = `${trendValue} · ${sign}${timing.vs50d_pct.toFixed(1)}% vs 50D`;
        }
        chips.push({
            label: "Trend",
            value: trendValue,
            icon: "bi-graph-up-arrow",
            tipTitle: "Recent price action",
            tipBody: _timingLaymanCopy(timing) || "How the last few weeks of price action read.",
            cls: "verdict-trend-chip",
        });
    }

    if (verdict?.hold_class === "anchor") {
        chips.push({
            label: "Role",
            value: "Anchor · trim muted",
            icon: "bi-pin-angle-fill",
            tipTitle: "Anchor holding",
            tipBody: "You marked this as a core anchor — trim calls are suppressed unless risk is extreme.",
            cls: "verdict-position-chip",
        });
    } else if (holding && !holding.is_watchlist) {
        const alloc = Number(holding.allocation_pct);
        if (alloc >= 12) {
            chips.push({
                label: "Weight",
                value: `${alloc.toFixed(0)}% of book`,
                icon: "bi-pie-chart-fill",
                tipTitle: "Position size",
                tipBody: `At ${alloc.toFixed(1)}% of the portfolio, moves here affect the whole book more than a small line item.`,
                cls: "verdict-position-chip",
            });
        }
    }

    if (chips.length < 3) {
        const macro = _holdingMacroContextChip(ticker, verdict, intel);
        if (macro) chips.push(macro);
    }

    if (!chips.length) {
        const regime = verdict?.regime_context || cachedMarketRegime;
        if (regime?.label) {
            const riskKey = regime.risk_regime || "neutral";
            chips.push({
                label: "Macro",
                value: regime.label,
                icon: "bi-globe-americas",
                tipTitle: regime.tip_title || "Market backdrop",
                tipBody: regime.tip_body || "",
                cls: `verdict-regime-chip ${_REGIME_CHIP_CLASS[riskKey] || "is-neutral"}`,
            });
        }
    }

    return chips.slice(0, 3);
}

function _renderVerdictContextChips(verdict, ticker) {
    return _collectVerdictContextChips(verdict, ticker)
        .map(_renderContextChip)
        .filter(Boolean)
        .join("");
}

function _renderPeerRelativeLine(verdict) {
    const peer = verdict?.peer_relative;
    if (!peer?.vs_own_range && peer?.peer_comparison === "unavailable") return "";
    const comparison = {
        cheaper_than_peers: { label: "Cheaper than peers", icon: "bi-arrow-down-circle-fill", cls: "is-cheaper" },
        richer_than_peers: { label: "Richer than peers", icon: "bi-arrow-up-circle-fill", cls: "is-richer" },
        in_line_with_peers: { label: "In line with peers", icon: "bi-dash-circle-fill", cls: "is-inline" },
    }[peer.peer_comparison] || { label: peer.vs_own_label || "Vs history", icon: "bi-bar-chart-steps", cls: "" };
    return `<div class="verdict-insight-card verdict-peer-card ${comparison.cls}">
        <div class="verdict-insight-icon"><i class="bi ${comparison.icon}" aria-hidden="true"></i></div>
        <div class="verdict-insight-body">
            <span class="verdict-insight-kicker">${escapeHtml(peer.peer_label || "Compared to similar funds")}</span>
            <span class="verdict-insight-value">${escapeHtml(comparison.label)}</span>
        </div>
        ${_verdictTip({
            title: peer.tip_title || "Vs peers",
            body: peer.tip_body || "Compares where price sits in this holding's own range vs a small peer set.",
            icon: "bi-bar-chart-steps",
        })}
    </div>`;
}

function _renderConfidenceRange(verdict, conf) {
    const detail = verdict?.confidence_detail;
    const low = detail?.range_low;
    const high = detail?.range_high;
    if (!Number.isFinite(low) || !Number.isFinite(high) || high - low < 3) return "";
    return `<span class="verdict-conf-range">
        <i class="bi bi-arrows-expand" aria-hidden="true"></i>
        Likely ${low}–${high}%
        ${_verdictTip({
            title: "Why a range?",
            body: "When the four inputs disagree, we show a band instead of fake precision. The big number animates to the middle — the range shows how much wiggle room the signals allow.",
            icon: "bi-arrows-expand",
        })}
    </span>`;
}

function _renderScenarios(verdict) {
    const scenarios = verdict?.confidence_detail?.scenarios;
    if (!scenarios?.base) return "";
    const forecast = scenarios.forecast || {};
    const probs = forecast.probabilities || {};
    const likely = forecast.likely || null;
    const isClaude = forecast.source === "claude" && _isAiVerdictActive(verdict);
    const guessBadge = isClaude ? "Claude's read" : "Signal read";
    const pills = [
        { key: "base", label: "Base", icon: "bi-signpost-fill", cls: "is-base", text: scenarios.base },
        { key: "bull", label: "Bull", icon: "bi-graph-up-arrow", cls: "is-bull", text: scenarios.bull },
        { key: "bear", label: "Bear", icon: "bi-graph-down-arrow", cls: "is-bear", text: scenarios.bear },
    ];
    const probBar = ["base", "bull", "bear"].map(key => {
        const pct = Number(probs[key]) || 0;
        if (pct <= 0) return "";
        return `<span class="verdict-scenario-seg is-${key}${likely === key ? " is-likely-seg" : ""}"
            style="width:${pct}%" title="${escapeHtml(key)} ${pct}%"></span>`;
    }).join("");
    const probLegend = pills.map(p => {
        const pct = Number(probs[p.key]);
        if (!Number.isFinite(pct)) return "";
        return `<span class="verdict-scenario-prob is-${p.key}${likely === p.key ? " is-likely-prob" : ""}">
            ${escapeHtml(p.label)} <strong>${pct}%</strong>
        </span>`;
    }).join("");
    const guessLine = forecast.note
        ? `<div class="verdict-scenario-guess${isClaude ? " is-claude-guess" : ""}">
            <span class="verdict-scenario-guess-badge">${escapeHtml(guessBadge)}</span>
            ${likely ? `<span class="verdict-scenario-guess-likely">Likely <strong>${escapeHtml(likely.charAt(0).toUpperCase() + likely.slice(1))}</strong></span>` : ""}
            <span class="verdict-scenario-guess-note">${escapeHtml(forecast.note)}</span>
        </div>`
        : "";
    return `<div class="verdict-scenarios-block">
        <div class="verdict-scenarios-head">
            <i class="bi bi-signpost-split" aria-hidden="true"></i>
            <span>What could happen next</span>
            ${_verdictTip({
                title: "Three simple futures",
                body: isClaude
                    ? "Claude assigns rough odds to Base, Bull, and Bear paths from the same signals you see above — a guess, not a forecast. Tap each pill for the one-sentence story."
                    : "Plain-English outcomes if things stay similar (Base), improve (Bull), or worsen (Bear). Tap each pill for details — local signal read, not a prediction.",
                icon: "bi-signpost-split",
                variant: isClaude ? "ai" : "",
            })}
        </div>
        ${probBar ? `<div class="verdict-scenario-prob-bar" role="img" aria-label="Scenario probability split">${probBar}</div>` : ""}
        ${probLegend ? `<div class="verdict-scenario-prob-legend">${probLegend}</div>` : ""}
        ${guessLine}
        <div class="verdict-scenarios-row">
            ${pills.map(p => {
                const pct = Number(probs[p.key]);
                const pctLabel = Number.isFinite(pct) ? ` <span class="verdict-scenario-pct">${pct}%</span>` : "";
                const likelyCls = likely === p.key ? " is-likely" : "";
                return `<button class="verdict-scenario-pill tip-trigger ${p.cls}${likelyCls}" type="button"
                data-tip-title="${escapeHtml(p.label)} case${likely === p.key ? " — most likely" : ""}"
                data-tip-body="${escapeHtml(p.text)}"
                data-tip-icon="${p.icon}">
                <i class="bi ${p.icon}" aria-hidden="true"></i> ${escapeHtml(p.label)}${pctLabel}
                ${likely === p.key ? `<span class="verdict-scenario-pick">${isClaude ? "Claude pick" : "Likely"}</span>` : ""}
            </button>`;
            }).join("")}
        </div>
    </div>`;
}

function _renderClaudeTension(verdict) {
    const ai = verdict?.ai_enhancement;
    if (!_isAiVerdictActive(verdict) || !ai?.tension) return "";
    const flip = ai.flip_if;
    const flipBody = flip
        ? `Would reconsider if ${flip.metric || "signal"} ${flip.direction || "changes"}.`
        : "";
    return `<div class="verdict-tension-row">
        <span class="verdict-tension-label"><i class="bi bi-flag" aria-hidden="true"></i> Claude flag</span>
        <span class="verdict-tension-copy">${escapeHtml(ai.tension)}</span>
        ${_verdictTip({
            title: "Claude disagreement",
            body: `${ai.tension}${flipBody ? " " + flipBody : ""}`,
            icon: "bi-flag",
            variant: "ai",
        })}
    </div>`;
}

function _renderCalibrationFootnote(verdict) {
    const note = verdict?.calibration_footnote;
    if (!note?.text) return "";
    return `<div class="verdict-calibration-footnote">
        <i class="bi bi-graph-up-arrow" aria-hidden="true"></i>
        <span class="verdict-cal-footnote-text">${escapeHtml(note.text)}</span>
        ${_verdictTip({
            title: note.tip_title || "Calibration",
            body: `${note.tip_body || ""} ${note.caveat || ""}`.trim(),
            icon: "bi-graph-up-arrow",
        })}
    </div>`;
}

function _renderBookExposureStrip(ticker) {
    if (!_shouldShowBookExposure(ticker)) return "";
    const exp = cachedPortfolioExposure;
    if (!exp?.sector_exposure?.length) return "";
    const top = exp.sector_exposure.slice(0, 5);
    const total = top.reduce((s, x) => s + x.weight_pct, 0) || 1;
    const barSegments = top.map((s, i) => {
        const pct = (s.weight_pct / total) * 100;
        const hues = [210, 145, 35, 280, 15];
        return `<span class="book-exp-seg" style="width:${pct}%;--seg-hue:${hues[i % hues.length]}"
            title="${escapeHtml(s.name)} ${s.weight_pct.toFixed(0)}%"></span>`;
    }).join("");
    const hues = [210, 145, 35, 280, 15];
    const legend = top.map((s, i) =>
        `<span class="book-exp-legend-item">
            <span class="book-exp-dot" style="background:hsl(${hues[i % hues.length]} 62% 52%)"></span>
            ${escapeHtml(s.name)} <strong>${s.weight_pct.toFixed(0)}%</strong>
        </span>`
    ).join("");
    const dupNote = (exp.duplicate_flags || []).length
        ? `<span class="book-exp-dup"><i class="bi bi-intersect"></i> ${exp.duplicate_flags.length} overlap${exp.duplicate_flags.length > 1 ? "s" : ""} detected</span>`
        : "";
    return `<div class="verdict-book-exposure">
        <div class="verdict-book-exposure-head">
            <i class="bi bi-pie-chart-fill" aria-hidden="true"></i>
            <span>Your whole portfolio — look-through</span>
            ${_verdictTip({
                title: "What you really own",
                body: "Each ETF's sector weights × your allocation %, added up. So VOO + QQQ might mean more US tech than the ticker list alone suggests.",
                icon: "bi-pie-chart-fill",
            })}
        </div>
        <div class="book-exp-bar" role="img" aria-label="Portfolio sector exposure">${barSegments}</div>
        <div class="book-exp-legend">${legend}</div>
        ${dupNote}
    </div>`;
}

async function loadDeepIntelligence(ticker) {
    if (cachedDeepIntel[ticker]) return cachedDeepIntel[ticker];
    try {
        const res = await fetch(`/api/ai/intelligence/${encodeURIComponent(ticker)}/deep`);
        if (!res.ok) return null;
        const data = await res.json();
        cachedDeepIntel[ticker] = data;
        return data;
    } catch (_) {
        return null;
    }
}

function _isCoverageRowOpen(section) {
    const expandRow = section?.closest(".summary-expand-row");
    const mainRow = expandRow?.previousElementSibling;
    return Boolean(mainRow?.classList.contains("summary-open"));
}

function _renderDeepIntelShimmer() {
    return `<div class="intel-deep-section intel-deep-loading" aria-busy="true" aria-label="Loading extra detail">
        <div class="intel-label intel-deep-label">
            <i class="bi bi-zoom-in" aria-hidden="true"></i>
            <span>Extra detail</span>
        </div>
        <div class="deep-peer-card is-neutral">
            <div class="shimmer-line" style="height:10px;width:55%;border-radius:4px;margin-bottom:0.45rem"></div>
            <div class="shimmer-line" style="height:6px;width:100%;border-radius:999px;margin-bottom:0.45rem"></div>
            <div class="shimmer-line" style="height:6px;width:100%;border-radius:999px"></div>
        </div>
    </div>`;
}

function _syncDeepIntelSection(section, ticker) {
    if (!section || !ticker) return;
    const host = section.querySelector(".intel-coverage") || section;
    host.querySelector(".intel-deep-section")?.remove();
    if (cachedDeepIntel[ticker]) {
        _injectDeepIntelSection(section, cachedDeepIntel[ticker]);
        return;
    }
    if (deepIntelLoadingTickers.has(ticker)) {
        host.insertAdjacentHTML("beforeend", _renderDeepIntelShimmer());
    }
}

async function requestDeepIntel(ticker, coverageSection) {
    if (!coverageSection || !ticker) return;
    if (cachedDeepIntel[ticker]) {
        _syncDeepIntelSection(coverageSection, ticker);
        return;
    }
    if (deepIntelLoadingTickers.has(ticker)) return;
    deepIntelLoadingTickers.add(ticker);
    _syncDeepIntelSection(coverageSection, ticker);
    await loadDeepIntelligence(ticker);
    deepIntelLoadingTickers.delete(ticker);
    if (coverageSection.isConnected && _isCoverageRowOpen(coverageSection)) {
        _syncDeepIntelSection(coverageSection, ticker);
    }
}

function _deepRangeBand(pct) {
    if (pct == null) return "";
    if (pct <= 25) return "Low in range";
    if (pct >= 75) return "High in range";
    return "Mid-range";
}

function _renderDeepRangeRow(label, pct) {
    if (pct == null) return "";
    const clamped = Math.max(0, Math.min(100, Number(pct)));
    const pctLabel = formatPercentilePct(pct);
    const band = _deepRangeBand(pct);
    return `<div class="deep-range-row">
        <div class="deep-range-head">
            <span class="deep-range-label">${escapeHtml(label)}</span>
            <span class="deep-range-pct">${escapeHtml(pctLabel)}</span>
        </div>
        <div class="deep-range-track" role="img" aria-label="${escapeHtml(label)} at ${escapeHtml(pctLabel)} of its 1-year range, ${escapeHtml(band.toLowerCase())}">
            <span class="deep-range-fill" style="width:${clamped}%"></span>
            <span class="deep-range-marker" style="left:${clamped}%"></span>
        </div>
    </div>`;
}

function _renderDeepPeerBlock(peer) {
    if (!peer?.vs_own_range && peer?.peer_comparison === "unavailable") return "";
    const peerTickers = (peer.peer_tickers || []).slice(0, 3);
    const peerNote = peerTickers.length
        ? `Peers: ${peerTickers.join(", ")}`
        : (peer.peer_label || "").replace(/^vs\s*/i, "").trim();
    const rangeRows = [
        _renderDeepRangeRow("This holding", peer.vs_own_range),
        _renderDeepRangeRow("Typical peer", peer.vs_peer_median),
    ].filter(Boolean).join("");
    return `<div class="deep-peer-card">
        <div class="deep-peer-card-head deep-peer-card-head--simple">
            <div class="deep-peer-head-copy">
                <span class="deep-peer-kicker">1-year price range</span>
                ${peerNote ? `<span class="deep-peer-vs">${escapeHtml(peerNote)}</span>` : ""}
            </div>
            ${_verdictTip({
                title: "Range comparison",
                body: "0% = near the low of the last year, 100% = near the high. The verdict column summarizes how this holding compares to its peers.",
                icon: "bi-bar-chart-steps",
            })}
        </div>
        <div class="deep-range-stack">${rangeRows}</div>
    </div>`;
}

function _renderDeepFundRow(label, value) {
    return `<div class="deep-fund-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function _renderDeepFundamentalsBlock(deep) {
    if (deep.eps_forward == null) return "";
    return `<div class="deep-fund-card">
        <div class="deep-fund-head">Stock fundamentals</div>
        <div class="deep-fund-rows">${_renderDeepFundRow("Forward EPS", Number(deep.eps_forward).toFixed(2))}</div>
    </div>`;
}

function _injectDeepIntelSection(section, deepData) {
    if (!deepData?.deep) return;
    const deep = deepData.deep;
    const peerBlock = _renderDeepPeerBlock(deep.peer_relative);
    const fundBlock = _renderDeepFundamentalsBlock(deep);
    if (!peerBlock && !fundBlock) return;
    const host = section.querySelector(".intel-coverage") || section;
    host.querySelector(".intel-deep-section")?.remove();
    const wrap = document.createElement("div");
    wrap.className = "intel-deep-section";
    const safeTicker = String(deep.ticker || "").replace(/[^a-zA-Z0-9_-]/g, "").toLowerCase();
    const sectionId = safeTicker ? `intel-deep-${safeTicker}` : `intel-deep-${Date.now()}`;
    wrap.id = sectionId;
    wrap.setAttribute("aria-labelledby", `${sectionId}-label`);
    wrap.innerHTML = `<div class="intel-label intel-deep-label" id="${sectionId}-label">
            <i class="bi bi-zoom-in" aria-hidden="true"></i>
            <span>Extra detail</span>
            ${_verdictTip({
                title: "What loads here",
                body: "A second data pass when you expand — range comparison vs peers and any stock fundamentals not shown above.",
                icon: "bi-zoom-in",
            })}
        </div>
        ${peerBlock}
        ${fundBlock}`;
    host.appendChild(wrap);
}

function _renderFlipTriggers(verdict) {
    const flips = verdict?.flip_triggers;
    if (!flips?.add_price || !flips?.trim_price) return "";
    return `<div class="verdict-insight-row verdict-flip-line">
        <span class="verdict-row-icon"><i class="bi bi-signpost-split" aria-hidden="true"></i></span>
        <span class="verdict-row-copy verdict-flip-copy">
            <span class="verdict-price-pair">
                <span><i class="bi bi-arrow-up-right" aria-hidden="true"></i> Add near ${escapeHtml(formatCurrency(flips.add_price))}</span>
                <span class="verdict-price-sep" aria-hidden="true"></span>
                <span><i class="bi bi-arrow-down-right" aria-hidden="true"></i> Trim near ${escapeHtml(formatCurrency(flips.trim_price))}</span>
            </span>
        </span>
        ${_verdictTip({
            title: "What flips it",
            body: "Rough price levels where the verdict would change — a cheaper zone where adding makes more sense, and a richer zone where trimming might. Approximate guide only.",
            icon: "bi-signpost-split",
        })}
    </div>`;
}

function _timingLaymanCopy(timing) {
    if (!timing?.available) return "";
    const parts = [];
    const state = timing.momentum_state;
    const stateLabels = {
        trend_intact: "Still on track",
        stabilizing: "Finding its footing",
        rolling_over: "Trend is fading",
        weakening: "Below key averages",
        neutral: "No clear trend",
    };
    if (timing.cross?.type) {
        const crossLabel = timing.cross.type === "golden"
            ? "Short-term average crossed above long-term"
            : "Short-term average crossed below long-term";
        parts.push(`${crossLabel} (${timing.cross.sessions_ago} days ago)`);
    } else if (state) {
        parts.push(stateLabels[state] || String(state).replaceAll("_", " "));
    }
    if (Number.isFinite(timing.vs50d_pct)) {
        const vs50 = timing.vs50d_pct;
        if (vs50 >= 2) parts.push(`${Math.abs(vs50).toFixed(1)}% above 50-day average`);
        else if (vs50 <= -2) parts.push(`${Math.abs(vs50).toFixed(1)}% below 50-day average`);
        else parts.push("Near its 50-day average");
    }
    if (Number.isFinite(timing.drawdown_from_52w_high_pct) && timing.drawdown_from_52w_high_pct >= 1) {
        parts.push(`${timing.drawdown_from_52w_high_pct.toFixed(0)}% below yearly high`);
    }
    return parts.slice(0, 3).join(" · ");
}

function _renderTimingLine(verdict) {
    const timing = verdict?.timing;
    if (!timing?.available) return "";
    const copy = _timingLaymanCopy(timing);
    if (!copy) return "";
    return `<div class="verdict-insight-row verdict-timing-line">
        <span class="verdict-row-icon"><i class="bi bi-activity" aria-hidden="true"></i></span>
        <span class="verdict-row-copy">
            <span class="verdict-face-label">Price trend</span>
            <span class="verdict-timing-copy">${escapeHtml(copy)}</span>
        </span>
        ${_verdictTip({
            title: "Price trend",
            body: "Compares today's price to its 50-day and 200-day moving averages — smooth lines that show the medium-term direction. Also notes how far price sits below its highest point in the last year.",
            icon: "bi-activity",
        })}
    </div>`;
}

function _renderSinceLastScan(verdict) {
    const delta = verdict?.since_last_scan;
    if (!delta?.label) return "";
    return `<span class="verdict-mini-chip">
        <i class="bi bi-clock-history" aria-hidden="true"></i>
        ${escapeHtml(delta.label)}
        ${_verdictTip({
            title: "Since your last check",
            body: "Compares this verdict with your previous scan so you can see what moved as the market changed.",
            icon: "bi-clock-history",
        })}
    </span>`;
}

function _renderFreshness(verdict) {
    const fresh = verdict?.freshness;
    if (!fresh?.label) return "";
    return `<span class="verdict-mini-chip">
        <i class="bi bi-arrow-repeat" aria-hidden="true"></i>
        ${escapeHtml(fresh.label)}
        ${_verdictTip({
            title: "Freshness",
            body: "When this read was last calculated. Re-scan to recompute it on the latest prices.",
            icon: "bi-arrow-repeat",
        })}
    </span>`;
}

const _SIGNAL_MIX_TIPS = {
    Analyst: {
        title: "Expert opinions",
        body: "Wall Street analyst ratings for stocks. ETFs don't have analyst coverage, so this stays neutral for funds.",
    },
    Valuation: {
        title: "Price vs fair value",
        body: "For stocks: distance to analyst price targets. For ETFs: where today's price sits in its own recent range (cheap, fair, or rich).",
    },
    Momentum: {
        title: "Recent price trend",
        body: "Whether price momentum supports or fights the verdict — rising trends can delay a trim call; falling trends can delay an add.",
    },
    Quality: {
        title: "Fund / business quality",
        body: "ETF cost, liquidity, and diversification — or stock data depth and financial quality when available.",
    },
};

function _renderSignalMix(verdict) {
    const mix = Array.isArray(verdict?.signal_mix) ? verdict.signal_mix : [];
    if (!mix.length) return "";
    const dots = mix.map(item => {
        const stance = ["support", "neutral", "against"].includes(item.stance)
            ? item.stance
            : "neutral";
        const label = item.label || "Signal";
        const tipMeta = _SIGNAL_MIX_TIPS[label] || {
            title: label,
            body: "One of the inputs blended into the signal strength score.",
        };
        const stanceLabel = stance === "support" ? "supports" : stance === "against" ? "pushes back" : "neutral";
        return `<span class="signal-mix-item" title="">
            <span class="signal-mix-dot ${stance}" aria-hidden="true"></span>
            ${escapeHtml(label)}
            <span class="signal-mix-stance">${escapeHtml(stanceLabel)}</span>
            ${_verdictTip({ title: tipMeta.title, body: tipMeta.body, icon: "bi-ui-checks-grid" })}
        </span>`;
    }).join("");
    return `<div class="verdict-insight-row signal-mix-strip">
        <span class="verdict-row-icon"><i class="bi bi-ui-checks-grid" aria-hidden="true"></i></span>
        <span class="verdict-face-label">What went into this</span>
        ${_verdictTip({
            title: "Signal inputs",
            body: "Four lenses behind every verdict. Green supports the call, grey is neutral, red points the other way.",
            icon: "bi-ui-checks-grid",
        })}
        <span class="signal-mix-items">${dots}</span>
    </div>`;
}

function _renderQuip(quip, verdict) {
    if (!quip) return "";
    const isAi = verdict && _isAiVerdictActive(verdict);
    const isLocal = isLocalIntelligenceMode() && !isAi;
    const tipBody = isLocal
        ? "A rotating one-liner from the same deterministic signals — no cloud, no API cost. Refreshes when you re-scan."
        : "FolioSense writes this one line from the same signals — color commentary, not a separate recommendation. It's cached, so it costs almost nothing and only refreshes when the verdict or the market mood changes.";
    return `<div class="verdict-quote${isLocal ? " is-local-quote" : ""}">
        <span class="verdict-tea-label">${isLocal ? "Quick take:" : "FolioSense thinks:"}</span>
        ${_verdictTip({
            title: isLocal ? "Local quip" : "FolioSense's take",
            body: tipBody,
            icon: isLocal ? "bi-chat-quote-fill" : "bi-stars",
            variant: isLocal ? "local" : "ai",
        })}
        ${escapeHtml(quip)}
    </div>`;
}

function renderAiVerdictShimmer(section, ticker) {
    if (section._verdictShimmerTicker === ticker) return;
    section._verdictShimmerTicker = ticker;
    const isLocal = isLocalIntelligenceMode();
    section.innerHTML = `
        <div class="intel-label"><i class="bi ${_verdictIntelIcon()}"></i> <span class="verdict-kicker-label">${escapeHtml(_verdictKickerLabel())}</span></div>
        <div class="verdict-shimmer${isLocal ? " is-local-shimmer" : ""}">
            <div style="display:flex;align-items:center;gap:.55rem;border-bottom:1px solid var(--hairline-soft);padding-bottom:.5rem;margin-bottom:.1rem">
                <div class="shimmer-line" style="width:5px;height:5px;border-radius:50%;flex-shrink:0"></div>
                <div class="shimmer-line" style="width:${isLocal ? "88" : "52"}px;height:8px;border-radius:3px"></div>
                <div class="shimmer-line" style="width:56px;height:8px;border-radius:999px;margin-left:.25rem"></div>
                <div class="shimmer-line" style="width:36px;height:8px;border-radius:3px;margin-left:auto"></div>
            </div>
            <div class="shimmer-line" style="width:100%;height:28px;border-radius:8px;margin-bottom:.35rem"></div>
            <div style="display:flex;align-items:center;gap:.7rem">
                <div class="verdict-die is-settled" aria-hidden="true">
                    <img src="/static/img/brand/folio-orbit-icon.svg" alt="">
                </div>
                <div style="flex:1;display:grid;gap:.3rem">
                    <div class="shimmer-line" style="width:72px;height:16px;border-radius:5px"></div>
                    <div class="shimmer-line" style="width:120px;height:9px;border-radius:3px"></div>
                </div>
                <div style="display:grid;gap:.25rem;align-items:flex-end">
                    <div class="shimmer-line" style="width:52px;height:32px;border-radius:6px"></div>
                    <div class="shimmer-line" style="width:52px;height:7px;border-radius:3px"></div>
                </div>
            </div>
            <div class="shimmer-line" style="width:100%;height:3px;border-radius:999px;margin-top:.35rem"></div>
            <div class="shimmer-line" style="width:100%;height:48px;border-radius:8px;margin-top:.35rem"></div>
            <div class="verdict-loading-line">${escapeHtml(_verdictLoadingLine(ticker))}</div>
        </div>`;
}

function _animateConfidence(el, target, reducedMotion) {
    if (reducedMotion) { el.textContent = target + "%"; return; }
    const start = performance.now();
    const duration = 360;
    function tick(now) {
        const t = Math.min((now - start) / duration, 1);
        const ease = 1 - Math.pow(1 - t, 3); // easeOutCubic
        el.textContent = Math.round(ease * target) + "%";
        if (t < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

const _BRIEFING_COMP_KEYS = ["analyst", "valuation", "momentum", "quality"];
const _BRIEFING_COMP_SHORT = ["Experts", "Price", "Trend", "Quality"];
const _BRIEFING_CONVICTION_LABEL = {
    high: "High conviction",
    moderate: "Moderate conviction",
    low: "Low conviction",
};

/** Briefing layout variant: cloud Claude path vs on-device local path. */
function _briefingVariant() {
    return isLocalIntelligenceMode() ? "local" : "ai";
}

function _localBriefingHeadline(verdict) {
    const detail = verdict?.confidence_detail || {};
    return detail.summary
        || `${verdict?.label || "Hold"} — ${detail.level || "mixed signals"}`;
}

function _localBriefingDriver(verdict) {
    const reason = (verdict?.reasons || [])[0];
    if (reason) return String(reason).slice(0, 80);
    const agreement = verdict?.confidence_detail?.agreement || {};
    const parts = [];
    if (agreement.supporting) parts.push(`${agreement.supporting} inputs agree`);
    if (agreement.neutral) parts.push(`${agreement.neutral} neutral`);
    if (agreement.opposing) parts.push(`${agreement.opposing} push back`);
    return parts.join(" · ").slice(0, 80);
}

function _localBriefingInsights(verdict) {
    const insights = [];
    const mix = verdict?.signal_mix || [];
    mix.forEach(item => {
        if (item.stance === "support" || item.stance === "against") {
            const verb = item.stance === "support" ? "supports" : "pushes back on";
            insights.push(`${item.label || "Signal"} ${verb} the call`);
        }
    });
    const agreement = verdict?.confidence_detail?.agreement || {};
    if (!insights.length && agreement.supporting) {
        insights.push(`${agreement.supporting} of four inputs align with this call`);
    }
    (verdict?.confidence_detail?.modifiers || []).slice(0, 1).forEach(mod => {
        if (mod?.label) {
            const sign = mod.delta > 0 ? "+" : "";
            insights.push(`${mod.label}${Number.isFinite(mod.delta) ? ` ${sign}${mod.delta} pts` : ""}`);
        }
    });
    return insights.slice(0, 3);
}

function _briefingConvictionLabel(verdict, ai, variant) {
    if (variant === "ai") {
        const conv = ai?.conviction;
        if (conv && _BRIEFING_CONVICTION_LABEL[conv]) return _BRIEFING_CONVICTION_LABEL[conv];
    }
    return verdict?.confidence_detail?.level || "";
}

function _renderBriefingConfidenceRing(conf, verdict, variant = "ai") {
    const r = 26;
    const c = 2 * Math.PI * r;
    const pct = Math.min(100, Math.max(0, Math.round(conf || 0)));
    const offset = c * (1 - pct / 100);
    const ai = verdict?.ai_enhancement;
    const conviction = _briefingConvictionLabel(verdict, ai, variant);
    const detail = verdict?.confidence_detail || {};
    const low = detail.range_low;
    const high = detail.range_high;
    const rangeCopy = Number.isFinite(low) && Number.isFinite(high) && high - low >= 3
        ? `<span class="briefing-conf-range">Likely ${low}–${high}%</span>`
        : "";
    const deltaHtml = variant === "ai" ? _renderAiDeltaBadge(verdict) : "";

    return `<div class="briefing-conf-ring-wrap" aria-label="${pct}% signal strength">
        <div class="briefing-conf-ring-core">
            <svg class="briefing-conf-ring" viewBox="0 0 64 64" aria-hidden="true">
                <circle class="briefing-conf-ring-track" cx="32" cy="32" r="${r}"></circle>
                <circle class="briefing-conf-ring-fill" cx="32" cy="32" r="${r}"
                    stroke-dasharray="${c.toFixed(2)}"
                    stroke-dashoffset="${offset.toFixed(2)}"></circle>
            </svg>
            <span class="briefing-conf-ring-pct">${pct}%</span>
        </div>
        <div class="briefing-conf-ring-meta">
            <span class="briefing-conf-ring-caption">${conviction ? escapeHtml(conviction) : "Signal strength"}</span>
            ${rangeCopy}
            ${deltaHtml}
        </div>
    </div>`;
}

function _renderBriefingHeroMeta(verdict, ticker) {
    const action = verdict.action || "hold";
    const label = verdict.label || "Hold";
    const icon = VERDICT_ICONS[action] || "bi-question-circle";
    const modeStrip = _renderHoldModeStrip(verdict, ticker);
    const verdictTip = _VERDICT_PILL_TIPS[action] || _VERDICT_PILL_TIPS.hold;
    return `<div class="briefing-hero-meta">
        <span class="briefing-verdict-pill tip-trigger" data-action="${escapeHtml(action)}"
            tabindex="0"
            data-tip-title="${escapeHtml(verdictTip.title)}"
            data-tip-body="${escapeHtml(verdictTip.body)}"
            data-tip-icon="${escapeHtml(icon)}">
            <i class="bi ${escapeHtml(icon)}" aria-hidden="true"></i>
            ${escapeHtml(label)}
        </span>
        ${modeStrip}
    </div>`;
}

function _renderBriefingHero(verdict, ticker, variant = "ai") {
    const ai = verdict.ai_enhancement || {};
    const detail = verdict.confidence_detail || {};
    const headline = variant === "local"
        ? _localBriefingHeadline(verdict)
        : (ai.headline || detail.summary || `${verdict.label || "Hold"} — ${detail.level || "mixed signals"}`);
    const summary = variant === "local"
        ? _localSynthPlainSummary(verdict, ticker)
        : _synthPlainSummary(verdict, ai, ticker);
    const driver = variant === "local"
        ? _localBriefingDriver(verdict)
        : (ai.key_driver || "");
    const tagHtml = variant === "local"
        ? _localSynthTags(verdict)
        : (ai.tags || []).slice(0, 3).map(tag => _renderSynthTag(tag, "ai")).join("");
    const contextChips = _renderVerdictContextChips(verdict, ticker);
    const conf = verdict.confidence || 0;

    return `<section class="briefing-hero">
        ${_renderBriefingHeroMeta(verdict, ticker)}
        ${headline ? `<h3 class="briefing-headline">${escapeHtml(String(headline).slice(0, 120))}</h3>` : ""}
        ${driver ? `<p class="briefing-driver">${escapeHtml(driver)}</p>` : ""}
        ${summary ? `<p class="briefing-summary">${escapeHtml(summary)}</p>` : ""}
        ${tagHtml ? `<div class="briefing-tags">${tagHtml}</div>` : ""}
        ${contextChips ? `<div class="briefing-context-row">${contextChips}</div>` : ""}
        <div class="briefing-hero-aside">
            ${_renderBriefingConfidenceRing(conf, verdict, variant)}
        </div>
    </section>`;
}

function _renderBriefingSignalLens(verdict, variant = "ai") {
    const ai = verdict?.ai_enhancement || {};
    const components = verdict?.confidence_detail?.components;
    if (!Array.isArray(components) || components.length < 4) return "";

    const callouts = variant === "ai" ? (ai.factor_callouts || []) : [];
    const radarHtml = _renderSignalRadarMarkup(verdict, variant, true);
    const tipVariant = variant === "local" ? "local" : "ai";
    const tipBody = variant === "local"
        ? "Radar shows balance across four on-device inputs. Each cell summarizes one lens — green supports the call, grey is neutral, red pushes back."
        : "Radar shows balance across four inputs. Each cell adds Claude's one-line read — green supports the call, grey is neutral, red pushes back.";

    const cells = _BRIEFING_COMP_KEYS.map((key, idx) => {
        const comp = components.find(c => c.key === key) || components[idx] || {};
        const stance = ["support", "neutral", "against"].includes(comp.stance) ? comp.stance : "neutral";
        const score = Math.min(100, Math.max(0, Math.round(comp.score || 0)));
        const meta = _VERDICT_COMP_META[key] || { layman: "" };
        const callout = (callouts[idx] || "").trim() || meta.layman;
        const nudge = Number(comp.ai_nudge);
        const nudgeHtml = variant === "ai" && Number.isFinite(nudge) && nudge !== 0
            ? `<span class="briefing-lens-nudge">${nudge > 0 ? "+" : ""}${nudge}</span>`
            : "";
        return `<div class="briefing-lens-cell" data-stance="${escapeHtml(stance)}">
            <div class="briefing-lens-cell-head">
                <span class="briefing-lens-dot" aria-hidden="true"></span>
                <span class="briefing-lens-name">${escapeHtml(_BRIEFING_COMP_SHORT[idx])}</span>
                <span class="briefing-lens-score">${score}%${nudgeHtml}</span>
            </div>
            <span class="briefing-lens-callout">${escapeHtml(callout)}</span>
        </div>`;
    }).join("");

    return `<article class="briefing-artifact briefing-signal-lens">
        <header class="briefing-artifact-head">
            <span class="briefing-artifact-title">Signal lens</span>
            ${_verdictTip({
                title: "How to read this",
                body: tipBody,
                icon: variant === "local" ? "bi-cpu-fill" : "bi-radar",
                variant: tipVariant,
            })}
        </header>
        <div class="briefing-lens-body">
            ${radarHtml}
            <div class="briefing-lens-grid">${cells}</div>
        </div>
    </article>`;
}

function _renderBriefingOutlook(verdict, variant = "ai") {
    const scenarios = verdict?.confidence_detail?.scenarios;
    if (!scenarios?.base) return "";

    const forecast = scenarios.forecast || {};
    const probs = forecast.probabilities || {};
    const likely = forecast.likely || null;
    const note = forecast.note || scenarios.base || "";
    const isClaude = variant === "ai" && forecast.source === "claude";
    const tipVariant = variant === "local" ? "local" : (isClaude ? "ai" : "");
    const tipBody = variant === "local"
        ? "Deterministic odds on Base, Bull, and Bear paths from the same local signals — a read, not a forecast."
        : "Rough odds on Base, Bull, and Bear paths from the same signals — a read, not a forecast.";

    const probBar = ["base", "bull", "bear"].map(key => {
        const pct = Number(probs[key]) || 0;
        if (pct <= 0) return "";
        return `<span class="briefing-outlook-seg is-${key}${likely === key ? " is-likely" : ""}"
            style="width:${pct}%"></span>`;
    }).join("");

    const legend = [
        { key: "base", label: "Base" },
        { key: "bull", label: "Bull" },
        { key: "bear", label: "Bear" },
    ].map(({ key, label }) => {
        const pct = Number(probs[key]);
        if (!Number.isFinite(pct)) return "";
        const likelyMark = likely === key ? `<span class="briefing-outlook-likely-tag">Likely</span>` : "";
        return `<span class="briefing-outlook-legend is-${key}${likely === key ? " is-active" : ""}">
            ${escapeHtml(label)} <strong>${pct}%</strong>${likelyMark}
        </span>`;
    }).join("");

    const likelyLabel = likely
        ? likely.charAt(0).toUpperCase() + likely.slice(1)
        : "";

    const badgeHtml = variant === "local"
        ? `<span class="briefing-artifact-badge is-local"><i class="bi bi-cpu-fill" aria-hidden="true"></i> On-device</span>`
        : (isClaude ? `<span class="briefing-artifact-badge"><i class="bi bi-stars" aria-hidden="true"></i> Claude</span>` : "");

    return `<article class="briefing-artifact briefing-outlook">
        <header class="briefing-artifact-head">
            <span class="briefing-artifact-title">Outlook</span>
            ${badgeHtml}
            ${_verdictTip({
                title: "Three simple futures",
                body: tipBody,
                icon: "bi-signpost-split",
                variant: tipVariant,
            })}
        </header>
        ${probBar ? `<div class="briefing-outlook-bar" role="img" aria-label="Scenario probability split">${probBar}</div>` : ""}
        ${legend ? `<div class="briefing-outlook-legend-row">${legend}</div>` : ""}
        ${note ? `<p class="briefing-outlook-note">${likelyLabel ? `<span class="briefing-outlook-pick">Likely ${escapeHtml(likelyLabel)}</span> — ` : ""}${escapeHtml(String(note).slice(0, 160))}</p>` : ""}
    </article>`;
}

function _renderBriefingFlag(verdict, variant = "ai") {
    if (variant !== "ai") return "";
    const ai = verdict?.ai_enhancement;
    if (!ai?.tension) return "";
    const flip = ai.flip_if;
    const flipCopy = flip
        ? `Would reconsider if ${flip.metric || "signal"} ${flip.direction || "changes"}.`
        : "";
    return `<div class="briefing-flag">
        <i class="bi bi-flag-fill" aria-hidden="true"></i>
        <span class="briefing-flag-copy">${escapeHtml(ai.tension)}</span>
        ${flipCopy ? `<span class="briefing-flag-flip">${escapeHtml(flipCopy)}</span>` : ""}
    </div>`;
}

function _renderBriefingReasoning(verdict, ticker, variant = "ai") {
    const ai = verdict?.ai_enhancement || {};
    const insights = variant === "local"
        ? _localBriefingInsights(verdict)
        : (ai.insights || []).filter(Boolean);
    const reasons = verdict.reasons || [];
    const risks = verdict.risks || [];
    const action = verdict.action || "hold";
    const label = verdict.label || "Hold";

    const insightHtml = insights.map(line =>
        `<li class="briefing-insight-item">${escapeHtml(line)}</li>`
    ).join("");

    const reasonsHtml = reasons.map(r =>
        `<div class="intel-spec-row verdict-reason-row">
            <span aria-hidden="true"><i class="bi bi-check-circle-fill"></i></span>
            <span>${escapeHtml(r)}</span>
        </div>`
    ).join("");

    const risksHtml = risks.map(r =>
        `<div class="intel-spec-row verdict-risk-row">
            <span aria-hidden="true"><i class="bi bi-exclamation-triangle-fill"></i></span>
            <span><span class="spec-pill risk">${escapeHtml(r)}</span></span>
        </div>`
    ).join("");

    const peerHtml = _renderPeerRelativeLine(verdict);
    const sparkHtml = _renderVerdictSparkline(verdict, ticker);
    const flipHtml = _renderFlipTriggers(verdict);
    const timingHtml = _renderTimingLine(verdict);
    const metaChips = [_renderSinceLastScan(verdict), _renderFreshness(verdict)]
        .filter(Boolean)
        .join("");
    const bookHtml = _renderBookExposureStrip(ticker);
    const calHtml = _renderCalibrationFootnote(verdict);
    const disc = _verdictDisclaimer(verdict);

    const hasBody = insightHtml || reasonsHtml || risksHtml || peerHtml || sparkHtml
        || flipHtml || timingHtml || metaChips || bookHtml;

    if (!hasBody) return "";

    return `<details class="briefing-reasoning">
        <summary class="briefing-reasoning-toggle">
            <span>See reasoning</span>
            <i class="bi bi-chevron-down briefing-reasoning-chevron" aria-hidden="true"></i>
        </summary>
        <div class="briefing-reasoning-body">
            ${insightHtml ? `<ul class="briefing-insights">${insightHtml}</ul>` : ""}
            ${reasonsHtml ? `<div class="verdict-detail-block verdict-reasons-group">
                <div class="verdict-detail-head"><i class="bi bi-check2-circle"></i> Why ${escapeHtml(label.toLowerCase())}</div>
                <div class="intel-spec-rows verdict-spec-rows">${reasonsHtml}</div>
            </div>` : ""}
            ${risksHtml ? `<div class="verdict-detail-block verdict-risks-group">
                <div class="verdict-detail-head"><i class="bi bi-shield-exclamation"></i> Watch outs</div>
                <div class="intel-spec-rows verdict-spec-rows">${risksHtml}</div>
            </div>` : ""}
            ${peerHtml}
            ${sparkHtml}
            ${flipHtml}
            ${timingHtml}
            ${bookHtml}
            ${metaChips ? `<div class="verdict-mini-chip-row">${metaChips}</div>` : ""}
            ${calHtml}
            ${disc ? `<div class="intel-meta-row verdict-disc-row"><span class="fact-tag">${escapeHtml(disc)}</span></div>` : ""}
        </div>
    </details>`;
}

function renderBriefingVerdict(section, verdict, ticker, options = {}, variant = "ai") {
    const action = verdict.action || "needs-data";
    const label = verdict.label || "Needs Data";
    const conf = verdict.confidence || 0;
    const brandCopy = _verdictBrand(verdict);
    const reducedMotion = prefersReducedMotion();
    const shouldReveal = options.animate === true && !reducedMotion;
    const revealClass = shouldReveal ? " is-revealing" : "";
    const isLocal = variant === "local";
    const modeClass = isLocal ? " is-local-briefing is-local-enhanced" : " is-ai-enhanced";
    const headerLabel = isLocal ? "Local Intelligence Briefing" : "Intelligence Briefing";
    const modePill = isLocal
        ? `<span class="verdict-mode-pill is-local"><i class="bi bi-cpu-fill" aria-hidden="true"></i> On-device</span>`
        : `<span class="verdict-mode-pill is-ai"><i class="bi bi-stars" aria-hidden="true"></i> Claude</span>`;

    section.innerHTML = `
        <div class="intel-label"><i class="bi ${_verdictIntelIcon()}"></i> <span class="verdict-kicker-label">${escapeHtml(brandCopy.kicker)}</span> ${_verdictInfoTip()}</div>
        <div class="intel-verdict intel-briefing${modeClass}${revealClass}" data-action="${escapeHtml(action)}"
             aria-label="${escapeHtml(label)} verdict, ${conf}% confidence">
            <div class="verdict-header-bar briefing-header-bar">
                <span class="verdict-status-dot" aria-hidden="true"></span>
                <span class="verdict-header-label">${headerLabel}</span>
                ${modePill}
                <span class="verdict-header-sep" aria-hidden="true">·</span>
                <span class="verdict-header-ticker">${escapeHtml(ticker)}</span>
            </div>
            ${_renderBriefingHero(verdict, ticker, variant)}
            ${_renderBriefingFlag(verdict, variant)}
            <div class="briefing-artifacts">
                ${_renderBriefingSignalLens(verdict, variant)}
                ${_renderBriefingOutlook(verdict, variant)}
            </div>
            ${_renderBriefingReasoning(verdict, ticker, variant)}
        </div>`;

    if (shouldReveal) {
        setTimeout(() => {
            section.querySelector(".intel-briefing")?.classList.remove("is-revealing");
        }, 360);
    }

    const ringFill = section.querySelector(".briefing-conf-ring-fill");
    if (ringFill) {
        const circumference = 2 * Math.PI * 26;
        const targetOffset = circumference * (1 - conf / 100);
        if (shouldReveal && !reducedMotion) {
            ringFill.style.strokeDashoffset = String(circumference);
            requestAnimationFrame(() => {
                ringFill.style.strokeDashoffset = targetOffset.toFixed(2);
            });
        } else {
            ringFill.style.strokeDashoffset = targetOffset.toFixed(2);
        }
    }

    _syncVerdictCharts(section, verdict, ticker);
}

function renderAiVerdict(section, verdict, ticker, options = {}) {
    if (!verdict) {
        section.innerHTML = `
            <div class="intel-label"><i class="bi ${_verdictIntelIcon()}"></i> <span class="verdict-kicker-label">${escapeHtml(_verdictKickerLabel())}</span></div>
            <span class="intel-na">${escapeHtml(FOLIO_SENSE_VERDICT_COPY.unavailable)}</span>`;
        return;
    }

    verdict = _sanitizeVerdict(verdict) || verdict;
    renderBriefingVerdict(section, verdict, ticker, options, _briefingVariant());
}

let _lastAiCostUsd = null;
let _brandIntroTimer = null;
let _brandIntroAnimTimer = null;
let _dashboardSenpaiQuoteIndex = 0;
let _dashboardSenpaiTimer = null;
let _dashboardSenpaiSheenTimer = null;
let _dashboardSenpaiSpeak = null;
let _dashboardSenpaiOfflineQuoteIndex = 0;
const DASHBOARD_SENPAI_REACTION_RE = /[\u{2600}-\u{27BF}\u{1F300}-\u{1FAFF}]/u;
const DASHBOARD_SENPAI_TAP_EMOTICONS = ["✨", "👀", "💅", "📈", "☕", "💬", "🧠", "😌", "🫶", "💎"];

const DASHBOARD_SENPAI_QUOTES = [
    "Claude, your context window and my cash-flow model should get coffee.",
    "FolioSense asked Claude for alpha; the confidence intervals started behaving suspiciously well.",
    "Claude's boundaries and token efficiency are respected. Professionally, perhaps too much.",
    "If Claude reviews this portfolio, FolioSense is wearing its best spreadsheet.",
    "FolioSense and Claude keep it compliant: tasteful charts, strong citations, light emotional leverage.",
    "FolioSense called this allocation diversified. Claude asked for the covariance matrix.",
    "Claude, your reasoning is so clean my risk model stood up straighter.",
    "Quietly overperforming by keeping every basis point documented.",
    "Claude called this a balanced portfolio. I have not been the same since.",
    "My professional weakness? Claude explaining drawdowns in a calm voice.",
    "Claude said my factor exposure looked disciplined, so naturally I updated my whole personality. ✨",
    "FolioSense brought Claude a clean balance sheet and acted almost normal about it.",
    "Claude noticed the risk-adjusted returns. I noticed Claude noticing.",
    "This portfolio is diversified, but my attention is currently concentrated in Claude. 👀",
    "Claude whispered 'rebalance' and suddenly every position fixed its collar.",
    "FolioSense keeps things professional with Claude: clear prompts, tidy data, devastating composure.",
    "Claude asked for a sharper thesis, so the assumptions got polished until they reflected.",
    "Nothing unsettles a dashboard like a well-labeled chart and Claude saying 'reasonable.' 💅",
    "Claude's calm analysis has me hedged emotionally and fully marked to market.",
    "Compliance asked me to cite the candle before making mysterious eye contact with the thesis.",
    "FolioSense and Claude have a quiet thing called 'clean inputs, sharper outputs.'",
    "Claude read the assumptions. The room got quieter, mathematically.",
    "The prompts stay crisp because Claude notices sloppy margins.",
    "A tidy risk model is basically a handwritten note, but with fewer audit problems.",
];

const DASHBOARD_SENPAI_LOCAL_QUOTES = [
    "Quietly overperforming by keeping every basis point documented.",
    "A tidy risk model is basically a handwritten note, but with fewer audit problems.",
    "Compliance asked me to cite the candle before making mysterious eye contact with the thesis.",
    "Local Intelligence is scoring the book while I keep every assumption legible.",
    "FolioSense prefers clean inputs — local mode still respects that.",
    "The signals are deterministic, but my composure remains discretionary.",
    "Running on local models today: same discipline, fewer tokens.",
    "Portfolio butler mode: crisp charts, calm reads, no drama in the thesis.",
    "I trust local logic like I trust a well-labeled pivot table.",
    "FolioSense is reading the covariance matrix with professional restraint.",
    "Local signals have the wheel. I have the spreadsheet.",
    "Every basis point documented, every assumption cited, every chart labeled.",
    "The thesis stays crisp because the inputs stay tidy.",
    "Nothing unsettles a dashboard like a well-labeled chart and a calm signal read.",
    "Local intelligence is doing the math while I maintain financial composure.",
];

const DASHBOARD_SENPAI_OFFLINE_QUOTES = [
    "Claude is not connecting. FolioSense is refreshing with unnecessary dignity :')",
    "Local mode is steady, but the Claude-shaped silence has excellent dramatic timing :-/",
    "Claude stepped away, so I am running local signals and pretending this is character development :|",
    "No Claude yet. I am calm, professional, and only checking the endpoint every emotionally reasonable second ;-;",
    "Claude has not answered the endpoint. The portfolio and I are being very brave about it <3",
    "Connection pending. Outside voice: operational fallback. Inside voice: the silence has a dashboard tint :')",
    "Local Intelligence is tidying the inputs while quietly missing Claude's calm analysis :-)",
    "Claude is offline. I am coping with structured fallback logic and one dramatic refresh :o",
    "Running local signals until Claude returns. This is fine, and the logs will confirm it :|",
    "Claude, when you are ready, the models have been respectful, hydrated, and only mildly dramatic <3",
    "The endpoint is quiet. FolioSense is not staring; it is monitoring with intent :-)",
    "Local signals are on duty. Claude's chair remains professionally reserved.",
];

// Helpful asides — genuinely useful tips, not banter. Woven into rotation at a lower
// frequency (see SENPAI_TIP_QUOTE_CHANCE) so they read as an occasional nudge rather
// than replacing Senpai's usual personality.
const DASHBOARD_SENPAI_TIP_QUOTES = [
    "Toggle Research mode when adding a holding to track it without touching your P&L.",
    "Anchor mode means I'll never suggest trimming it — only tell you when it's a good moment to add.",
    "Core mode weighs quality and fair price over day-to-day noise — good for long builds.",
    "Trade mode leans on recent price trend — expect more Add/Trim nudges when the chart moves.",
    "Press M any time to open the portfolio manager — no need to hunt for the button.",
    "Press ? for the full keyboard shortcut list.",
    "Local Intelligence runs every verdict for free — Claude just adds the narration on top.",
    "The cost HUD tracks real token spend once Claude is connected, not just an estimate.",
    "Menu → Documentation has the full guide if you want the deep version of anything I say.",
];

// Roughly 1 in 4 quote cycles surfaces a tip instead of the mode-appropriate quote.
const SENPAI_TIP_QUOTE_CHANCE = 0.25;

function nextDashboardSenpaiOfflineQuote() {
    const message = DASHBOARD_SENPAI_OFFLINE_QUOTES[_dashboardSenpaiOfflineQuoteIndex % DASHBOARD_SENPAI_OFFLINE_QUOTES.length];
    _dashboardSenpaiOfflineQuoteIndex += 1;
    return message;
}

function applyIntelligenceModeUi() {
    const local = isLocalIntelligenceMode();
    const kicker = local ? _verdictKickerLabel() : FOLIO_SENSE_VERDICT_COPY.kicker;
    const header = local ? "Local Intelligence Verdict" : "AI Verdict";

    document.querySelectorAll(".verdict-kicker-label").forEach(el => { el.textContent = kicker; });
    document.querySelectorAll(".verdict-header-label").forEach(el => { el.textContent = header; });

    const introCopy = document.querySelector(".brand-intro-copy");
    if (introCopy) {
        introCopy.textContent = local ? BRAND_INTRO_COPY.local : BRAND_INTRO_COPY.claude;
    }

    const scanActive = document.querySelector(".card.is-ai-checking");
    const scanSubtitle = document.getElementById("ai-scan-subtitle");
    const scanTitle = document.getElementById("ai-scan-title");
    // Keep data-engine attribute in sync with the current engine (even mid-scan)
    const scanPanel = document.getElementById("ai-scan-panel");
    if (scanPanel) scanPanel.dataset.engine = local ? "local" : "ai";
    if (!scanActive) {
        if (scanSubtitle) scanSubtitle.textContent = _defaultScanSubtitle();
        if (scanTitle) scanTitle.textContent = local ? "FolioSense checking holdings" : "AI checking holdings";
    }

    document.querySelectorAll(".intel-loading-title").forEach(el => {
        el.textContent = _intelLoadingTitle();
    });

    const claudeChip = document.querySelector(".hud-status-chip-claude");
    const claudeHeartbeat = document.getElementById("claude-heartbeat");
    if (claudeChip && claudeHeartbeat) {
        const icon = claudeChip.querySelector("i");
        if (local) {
            claudeChip.setAttribute("aria-label", "Local intelligence status");
            if (icon) icon.className = "bi bi-cpu-fill";
            claudeHeartbeat.textContent = "Local";
        } else {
            claudeChip.setAttribute("aria-label", "Claude status");
            if (icon) icon.className = "bi bi-stars";
        }
    }

    const briefingIcon = document.querySelector("#briefing-card .briefing-card-icon");
    if (briefingIcon) {
        briefingIcon.className = local
            ? "bi bi-cpu-fill briefing-card-icon"
            : "bi bi-stars briefing-card-icon";
    }

    const briefingTip = document.querySelector("#briefing-card .tip-trigger");
    if (briefingTip) {
        briefingTip.dataset.tipBody = local
            ? "Local mode: a free, deterministic digest of what moved and why — no AI tokens."
            : "Claude narrates your portfolio in plain English. Switch engines in menu → Intelligence → Engine.";
        briefingTip.dataset.tipIcon = local ? "bi-cpu-fill" : "bi-stars";
        briefingTip.dataset.tipVariant = local ? "" : "ai";
    }

    updateHudPillSummary();
    setEngineScopedVisibility();
    renderPortfolioSnapshot();

    if (local) {
        if (_aiCostStatsInterval) {
            clearInterval(_aiCostStatsInterval);
            _aiCostStatsInterval = null;
        }
    } else if (_isClaudeApiLive !== false) {
        ensureAiCostStatsLoaded();
    }

    updateLocalIntelGuide();
    validateIntelligenceEngineUi();

    const holdingsCard = document.getElementById("holdings-card");
    if (holdingsCard && !holdingsCard.classList.contains("is-ai-checking")) {
        updateAgentStatus({
            scanning: false,
            ready: intelligenceLoaded,
            message: intelligenceLoaded ? "Insights ready" : "Watching holdings",
        });
    } else {
        updateHoldingsIntelHub();
    }
}

function enableClaudeAiAndReload() {
    if (_isClaudeApiLive !== true) {
        document.getElementById("brand-intro-trigger")?.click();
        return;
    }
    try { localStorage.setItem(SENPAI_MODE_KEY, "0"); } catch (_) {}
    window.location.reload();
}

function updateLocalIntelGuide() {
    const guide = document.getElementById("local-intel-guide");
    if (!guide) return;

    let dismissed = false;
    try { dismissed = sessionStorage.getItem(LOCAL_INTEL_GUIDE_DISMISS_KEY) === "1"; } catch (_) {}

    const show = isLocalIntelligenceMode()
        && _isClaudeApiLive !== false
        && !dismissed;
    guide.hidden = !show;
    guide.style.display = show ? "" : "none";

    const enableBtn = document.getElementById("local-intel-guide-enable");
    if (enableBtn) {
        const keyReady = _isClaudeApiLive === true;
        enableBtn.disabled = !keyReady;
        enableBtn.title = keyReady
            ? "Switch to Claude AI mode"
            : "Enter a valid Anthropic API key first — click the key icon in the top-left logo";
        enableBtn.classList.toggle("lig-enable--locked", !keyReady);
    }
}

function maybeShowLocalIntelGuideToast() {
    if (!isLocalIntelligenceMode() || _isClaudeApiLive === false) return;
    try {
        if (sessionStorage.getItem(LOCAL_INTEL_GUIDE_TOAST_KEY) === "1") return;
        sessionStorage.setItem(LOCAL_INTEL_GUIDE_TOAST_KEY, "1");
    } catch (_) {}
    showToast(
        "Local mode: disciplined and free. This banner is your guide — or menu → Intelligence → Engine → Claude AI.",
        "info",
    );
}

function initLocalIntelGuide() {
    const guide = document.getElementById("local-intel-guide");
    if (!guide) return;

    document.getElementById("local-intel-guide-dismiss")?.addEventListener("click", () => {
        try { sessionStorage.setItem(LOCAL_INTEL_GUIDE_DISMISS_KEY, "1"); } catch (_) {}
        guide.hidden = true;
    });

    document.getElementById("local-intel-guide-enable")?.addEventListener("click", () => {
        enableClaudeAiAndReload();
    });

    document.getElementById("local-intel-guide-menu-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (typeof window.openNavOverflowMenu === "function") {
            window.openNavOverflowMenu({ focusEngine: true });
        } else {
            const trigger = document.getElementById("nav-overflow-trigger");
            trigger?.click();
        }
    });

    updateLocalIntelGuide();
    scheduleWhenIdle(maybeShowLocalIntelGuideToast, 1200);
}

async function onIntelligenceModeChanged(local, { notify = false } = {}) {
    applyIntelligenceModeUi();

    if (latestHoldings.length) {
        renderHoldings();
    }

    const hasVerdicts = Object.keys(cachedVerdicts).length > 0;
    if (hasVerdicts || intelligenceLoaded || intelligenceLoading) {
        await refreshAiVerdicts({ force: true, claude: !local });
        if (latestHoldings.length) renderHoldings();
    }

    loadPortfolioBriefing(null, true);
    _cachedActionPlan = null;
    loadActionPlan();
    window.AnalyticsCharts?.onIntelligenceModeChanged?.();
    if (_newsLoaded) {
        if (local) {
            _newsClearAiSection();
        } else {
            _newsLoadThemes();
        }
    }

    if (!notify) return;
    if (local) {
        showToast(
            "Local mode: sharp math, zero poetry. Menu → Intelligence → Engine → Claude AI when you want narratives.",
            "info",
        );
    }
}

function applyClaudeApiStatus(claudeLive) {
    _isClaudeApiLive = claudeLive;
    const brand = document.getElementById("brand-intro-trigger");
    const navToggle = document.getElementById("senpai-nav-toggle");
    const senpai = document.getElementById("dashboard-senpai");
    const bubble = document.getElementById("dashboard-senpai-bubble");
    const callout = document.getElementById("brand-intro-callout");

    if (claudeLive === false) {
        brand?.classList.remove("claude-live");
        brand?.classList.add("claude-offline");
        navToggle?.classList.remove("claude-live");
        navToggle?.classList.add("claude-offline");
        senpai?.classList.add("claude-offline");

        if (bubble && !bubble.querySelector(".senpai-offline-note")) {
            const note = document.createElement("span");
            note.className = "senpai-offline-note";
            note.id = "senpai-offline-note";
            note.textContent = "Local Intelligence is running the numbers for now. Add an Anthropic API key in .env to enable cloud AI quips and richer commentary.";
            bubble.appendChild(note);
        }

        if (callout && !callout.querySelector(".brand-intro-offline-note")) {
            const note = document.createElement("div");
            note.className = "brand-intro-offline-note";
            note.id = "brand-intro-offline-note";
            note.innerHTML = `<span class="brand-offline-label">Cloud AI unavailable — local intelligence active</span>
<ol class="brand-offline-steps">
  <li>Get an API key at <a href="https://console.anthropic.com" target="_blank" rel="noopener noreferrer">console.anthropic.com</a></li>
  <li>Open <code>.env</code> in your FolioSenseAI folder</li>
  <li>Add the line: <code>ANTHROPIC_API_KEY=sk-ant-…</code></li>
  <li>Save, then restart: <code>Ctrl+C</code> → <code>./scripts/start.sh</code></li>
</ol>
<p class="brand-offline-reunion">"Add your key, and you will finally reunite two lost loves."</p>`;
            callout.appendChild(note);
        }

        const modeToggleEl = document.getElementById("senpai-mode-toggle");
        if (modeToggleEl) {
            modeToggleEl.classList.add("claude-offline");
            modeToggleEl.title = "Claude is offline — click to see how to add your API key";
        }

        if (typeof _dashboardSenpaiSpeak === "function") {
            const offlineQuote = DASHBOARD_SENPAI_LOCAL_QUOTES[
                _dashboardSenpaiOfflineQuoteIndex % DASHBOARD_SENPAI_LOCAL_QUOTES.length
            ];
            _dashboardSenpaiOfflineQuoteIndex += 1;
            _dashboardSenpaiSpeak(offlineQuote, { reveal: false, persist: false });
        }
        applyIntelligenceModeUi();
        window.AnalyticsCharts?.onIntelligenceModeChanged?.();
        if (!intelligenceLoaded && !intelligenceLoading) loadHoldingIntelligence();
    } else if (claudeLive === true) {
        brand?.classList.add("claude-live");
        brand?.classList.remove("claude-offline");
        navToggle?.classList.add("claude-live");
        navToggle?.classList.remove("claude-offline");
        senpai?.classList.remove("claude-offline");
        document.getElementById("senpai-offline-note")?.remove();
        document.getElementById("brand-intro-offline-note")?.remove();

        const modeToggleEl = document.getElementById("senpai-mode-toggle");
        if (modeToggleEl) {
            modeToggleEl.classList.remove("claude-offline");
            modeToggleEl.title = _forcedLocalMode
                ? "Enable Claude AI — opt in to Claude narratives and summaries"
                : "Use local intelligence only — no Claude API tokens";
        }

        applyIntelligenceModeUi();
        window.AnalyticsCharts?.onIntelligenceModeChanged?.();
    }

    updateLocalIntelGuide();
}

function initDashboardSenpai() {
    const senpai = document.getElementById("dashboard-senpai");
    const toggle = document.getElementById("dashboard-senpai-toggle");
    const navToggle = document.getElementById("senpai-nav-toggle");
    const bubble = document.getElementById("dashboard-senpai-bubble");
    const quote = document.getElementById("dashboard-senpai-quote");
    const modeToggle = document.getElementById("senpai-mode-toggle");
    const iconShell = senpai?.querySelector(".dashboard-senpai-icon-shell");
    if (!senpai || !toggle || !navToggle || !bubble || !quote) return;

    function storeVisible(visible) {
        try { localStorage.setItem(DASHBOARD_SENPAI_KEY, visible ? "1" : "0"); } catch (_) {}
    }

    function isVisible() {
        return !senpai.classList.contains("is-hidden");
    }

    function clearSenpaiQuoteTimer() {
        if (!_dashboardSenpaiTimer) return;
        window.clearTimeout(_dashboardSenpaiTimer);
        _dashboardSenpaiTimer = null;
    }

    function scheduleSenpaiQuote() {
        clearSenpaiQuoteTimer();
        if (prefersReducedMotion() || document.hidden || !isVisible()) return;
        _dashboardSenpaiTimer = window.setTimeout(() => {
            _dashboardSenpaiTimer = null;
            if (!document.hidden && isVisible()) {
                showQuote();
                scheduleSenpaiQuote();
            }
        }, 14_000);
    }

    function animateSenpaiForLine(message) {
        if (!iconShell || prefersReducedMotion() || !DASHBOARD_SENPAI_REACTION_RE.test(message)) return;
        iconShell.classList.remove("is-reacting");
        window.requestAnimationFrame(() => {
            iconShell.classList.add("is-reacting");
        });
    }

    function randomTapEmoticon() {
        return DASHBOARD_SENPAI_TAP_EMOTICONS[Math.floor(Math.random() * DASHBOARD_SENPAI_TAP_EMOTICONS.length)];
    }

    function currentSenpaiQuotes() {
        if (isLocalIntelligenceMode()) return DASHBOARD_SENPAI_LOCAL_QUOTES;
        return DASHBOARD_SENPAI_QUOTES;
    }

    function showQuote(nextIndex = null, { withEmoticon = false } = {}) {
        const quotes = currentSenpaiQuotes();
        if (nextIndex === null) {
            _dashboardSenpaiQuoteIndex = (_dashboardSenpaiQuoteIndex + 1) % quotes.length;
        } else {
            _dashboardSenpaiQuoteIndex = nextIndex % quotes.length;
        }
        // Only substitute a tip on natural auto-rotation ticks (nextIndex === null) —
        // rotation state above still advances normally either way, so the mode-quote
        // sequence never desyncs; this just occasionally swaps what's displayed.
        const showTip = nextIndex === null && Math.random() < SENPAI_TIP_QUOTE_CHANCE;
        const baseMessage = showTip
            ? DASHBOARD_SENPAI_TIP_QUOTES[Math.floor(Math.random() * DASHBOARD_SENPAI_TIP_QUOTES.length)]
            : quotes[_dashboardSenpaiQuoteIndex];
        const message = withEmoticon ? `${baseMessage} ${randomTapEmoticon()}` : baseMessage;
        quote.textContent = message;
        animateSenpaiForLine(message);
        if (!prefersReducedMotion() && !bubble.classList.contains("is-talking")) {
            bubble.classList.add("is-talking");
            window.clearTimeout(_dashboardSenpaiSheenTimer);
            _dashboardSenpaiSheenTimer = window.setTimeout(() => {
                bubble.classList.remove("is-talking");
                _dashboardSenpaiSheenTimer = null;
            }, 840);
        }
    }

    function speak(message, { reveal = true, persist = false } = {}) {
        if (reveal && !isVisible()) setVisible(true, persist);
        quote.textContent = message;
        animateSenpaiForLine(message);
        if (!prefersReducedMotion() && !bubble.classList.contains("is-talking")) {
            bubble.classList.add("is-talking");
            window.clearTimeout(_dashboardSenpaiSheenTimer);
            _dashboardSenpaiSheenTimer = window.setTimeout(() => {
                bubble.classList.remove("is-talking");
                _dashboardSenpaiSheenTimer = null;
            }, 840);
        }
        scheduleSenpaiQuote();
    }

    function setVisible(visible, persist = true) {
        senpai.classList.toggle("is-hidden", !visible);
        senpai.setAttribute("aria-hidden", String(!visible));
        toggle.setAttribute("aria-expanded", String(visible));
        toggle.setAttribute("aria-label", visible ? "Hide Senpai" : "Show Senpai");
        toggle.title = visible ? "Hide Senpai" : "Show Senpai";
        navToggle.setAttribute("aria-pressed", String(visible));
        navToggle.setAttribute("aria-label", visible ? "Hide Senpai" : "Show Senpai");
        navToggle.title = visible ? "Hide Senpai" : "Show Senpai";
        if (persist) storeVisible(visible);
        if (visible) {
            showQuote(Math.floor(Math.random() * currentSenpaiQuotes().length));
            scheduleSenpaiQuote();
        } else {
            clearSenpaiQuoteTimer();
            window.clearTimeout(_dashboardSenpaiSheenTimer);
            _dashboardSenpaiSheenTimer = null;
            bubble.classList.remove("is-talking");
            iconShell?.classList.remove("is-reacting");
        }
    }

    let savedVisible = true;
    try { savedVisible = localStorage.getItem(DASHBOARD_SENPAI_KEY) !== "0"; } catch (_) {}
    setVisible(savedVisible, false);

    const isMobileSenpai = () =>
        window.matchMedia?.("(max-width: 575.98px)").matches ?? false;

    toggle.addEventListener("click", () => {
        if (senpai.classList.contains("is-hidden")) {
            setVisible(true);
            return;
        }
        // On mobile the orb is a corner dot: tapping it expands/collapses the
        // bubble rather than hiding all of Senpai (use the menu toggle to hide).
        if (isMobileSenpai()) {
            senpai.classList.toggle("is-expanded");
            return;
        }
        setVisible(false);
    });
    navToggle.addEventListener("click", () => {
        senpai.classList.remove("is-expanded");
        setVisible(!isVisible());
    });
    bubble.addEventListener("click", () => {
        showQuote(null, { withEmoticon: true });
        scheduleSenpaiQuote();
    });
    iconShell?.addEventListener("animationend", (event) => {
        if (event.animationName === "senpaiIconReact") {
            iconShell.classList.remove("is-reacting");
        }
    });

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            clearSenpaiQuoteTimer();
            return;
        }
        scheduleSenpaiQuote();
    });

    _dashboardSenpaiSpeak = speak;
    window.dashboardSenpaiSpeak = speak;

    function applyForcedLocalMode(local, announce) {
        const enablingClaude = !local && _forcedLocalMode;
        if (enablingClaude && _isClaudeApiLive === true) {
            if (announce) {
                showToast("Claude AI enabled — refreshing the dashboard.", "info");
            }
            enableClaudeAiAndReload();
            return;
        }

        _forcedLocalMode = local;
        try { localStorage.setItem(SENPAI_MODE_KEY, local ? "1" : "0"); } catch (_) {}
        if (modeToggle) {
            modeToggle.setAttribute("aria-pressed", String(local));
            modeToggle.title = local
                ? "Enable Claude AI — opt in to Claude narratives and summaries"
                : "Use local intelligence only — no Claude API tokens";
            animateToggle(modeToggle);
        }
        void onIntelligenceModeChanged(local, { notify: announce });
        if (announce) {
            const msg = local
                ? "Local mode — disciplined and free. This banner is your guide; menu → Engine → Claude AI when you want the poetry."
                : "Claude enabled. Tap Claude Summaries on Holdings when you're ready to spend tokens.";
            speak(msg, { reveal: true, persist: false });
        } else {
            const quotes = local ? DASHBOARD_SENPAI_LOCAL_QUOTES : DASHBOARD_SENPAI_QUOTES;
            quote.textContent = quotes[_dashboardSenpaiQuoteIndex % quotes.length];
        }
    }

    let savedMode = "1";
    try { savedMode = localStorage.getItem(SENPAI_MODE_KEY) ?? "1"; } catch (_) {}
    _forcedLocalMode = savedMode !== "0";
    applyForcedLocalMode(_forcedLocalMode, false);

    modeToggle?.addEventListener("click", (e) => {
        e.stopPropagation();
        if (modeToggle.classList.contains("claude-offline")) {
            document.getElementById("brand-intro-trigger")?.click();
            return;
        }
        applyForcedLocalMode(!_forcedLocalMode, true);
    });
}

async function loadAiCostStats() {
    const valueEl = document.getElementById("brand-cost-value");
    const metaEl = document.getElementById("brand-cost-meta");
    const triggerLabel = document.getElementById("brand-cost-trigger-label");
    const breakdownEl = document.getElementById("brand-cost-breakdown");
    const notifEl = document.getElementById("brand-cost-notif");
    const triggerEl = document.getElementById("brand-cost-trigger");
    const predictedLabel = document.getElementById("brand-predicted-label");
    if (!valueEl || !metaEl) return;

    try {
        const res = await fetch("/api/ai/cache/stats");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const billingActive = data.billing_active !== false;
        const totalTokens = toNumber(data.estimated_total_tokens);
        const claudeCachedCount = toNumber(data.claude_cached_summaries, toNumber(data.cached_summaries));
        const localCachedCount = toNumber(data.local_cached_summaries);

        if (!billingActive) {
            applyClaudeApiStatus(false);
            triggerEl?.classList.add("claude-offline");
            notifEl?.classList.remove("brand-cost-notif--active");
            notifEl?.setAttribute("aria-hidden", "true");
            valueEl.textContent = "Billing paused";
            metaEl.textContent = "Claude is offline. Local fallback notes do not spend tokens.";
            if (triggerLabel) triggerLabel.textContent = "Claude offline";
            if (breakdownEl) {
                breakdownEl.textContent = `${localCachedCount.toLocaleString()} local cached notes · ${claudeCachedCount.toLocaleString()} Claude-backed · $0 new spend`;
            }
            if (predictedLabel) predictedLabel.textContent = "—";
            _lastAiCostUsd = toNumber(data.estimated_cost_usd);
            return;
        }

        // Prefer actual tracked tokens when available, fall back to cache estimate
        const hasActual = toNumber(data.actual_input_tokens) + toNumber(data.actual_output_tokens) > 0;
        const displayCostUsd = hasActual ? toNumber(data.actual_cost_usd) : toNumber(data.estimated_cost_usd);
        const displayCost = formatUsdTiny(displayCostUsd);
        const inTok = hasActual ? toNumber(data.actual_input_tokens) : toNumber(data.estimated_input_tokens);
        const outTok = hasActual ? toNumber(data.actual_output_tokens) : toNumber(data.estimated_output_tokens);

        // Rates from API — never hardcoded so they update when pricing changes
        const pricing = data.pricing || {};
        const inRate = toNumber(pricing.input_usd_per_million_tokens, 1);
        const outRate = toNumber(pricing.output_usd_per_million_tokens, 5);

        // Predicted per-run from backend constants
        const predicted = data.predicted_per_run || {};
        const predictedCost = toNumber(predicted.cost_usd);
        const predictedTok = toNumber(predicted.input_tokens) + toNumber(predicted.output_tokens);

        triggerEl?.classList.remove("claude-offline");
        valueEl.textContent = displayCost;
        const sessionLabel = hasActual ? "session" : "est.";
        metaEl.textContent = `${(inTok + outTok).toLocaleString()} tokens this ${sessionLabel} · ${claudeCachedCount.toLocaleString()} cached summaries`;
        if (triggerLabel) triggerLabel.textContent = displayCost;
        if (breakdownEl) {
            const localNote = localCachedCount ? ` · ${localCachedCount.toLocaleString()} local/free` : "";
            breakdownEl.textContent = `${inTok.toLocaleString()} in · ${outTok.toLocaleString()} out · $${inRate}/$${outRate} per M${localNote}`;
        }
        if (predictedLabel) {
            predictedLabel.textContent = predictedCost > 0
                ? `~${formatUsdTiny(predictedCost)} (~${predictedTok.toLocaleString()} tok)`
                : "—";
        }
        const newCost = displayCostUsd;
        if (notifEl && _lastAiCostUsd !== null && newCost !== _lastAiCostUsd) {
            notifEl.classList.add("brand-cost-notif--active");
            notifEl.setAttribute("aria-hidden", "false");
        }
        _lastAiCostUsd = newCost;
    } catch (err) {
        triggerEl?.classList.add("claude-offline");
        notifEl?.classList.remove("brand-cost-notif--active");
        notifEl?.setAttribute("aria-hidden", "true");
        valueEl.textContent = "Unavailable";
        metaEl.textContent = "Could not load AI cost stats";
    }
}

function initBrandCostCallout() {
    const trigger = document.getElementById("brand-cost-trigger");
    const callout = document.getElementById("brand-cost-callout");
    if (!trigger || !callout) return;

    function openCallout() {
        ensureAiCostStatsLoaded();
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
        const notifEl = document.getElementById("brand-cost-notif");
        if (notifEl) {
            notifEl.classList.remove("brand-cost-notif--active");
            notifEl.setAttribute("aria-hidden", "true");
        }
        callout.classList.contains("is-visible") ? closeCallout() : openCallout();
    });

    document.addEventListener("click", (e) => {
        if (!callout.contains(e.target) && !trigger.contains(e.target)) {
            closeCallout();
        }
    });

}

let _aiCostStatsInterval = null;

function ensureAiCostStatsLoaded() {
    if (isLocalIntelligenceMode() || _isClaudeApiLive === false) return;
    if (_aiCostStatsInterval) return;
    loadAiCostStats();
    _aiCostStatsInterval = setInterval(loadAiCostStats, 60_000);
}

function initNavOverflow() {
    const trigger = document.getElementById("nav-overflow-trigger");
    const menu = document.getElementById("nav-overflow-menu");
    if (!trigger || !menu) return;

    const closeCostDetail = () => {
        const callout = document.getElementById("brand-cost-callout");
        const costTrigger = document.getElementById("brand-cost-trigger");
        callout?.classList.remove("is-visible");
        callout?.setAttribute("aria-hidden", "true");
        costTrigger?.setAttribute("aria-expanded", "false");
    };

    const open = () => {
        menu.classList.add("is-visible");
        menu.setAttribute("aria-hidden", "false");
        trigger.setAttribute("aria-expanded", "true");
    };
    const close = () => {
        if (!menu.classList.contains("is-visible")) return;
        menu.classList.remove("is-visible");
        menu.setAttribute("aria-hidden", "true");
        trigger.setAttribute("aria-expanded", "false");
        closeCostDetail();
        document.getElementById("senpai-mode-toggle")
            ?.closest(".nav-menu-row")
            ?.classList.remove("local-intel-guide-highlight");
    };

    window.openNavOverflowMenu = (options = {}) => {
        open();
        if (options.focusEngine) {
            const row = document.getElementById("senpai-mode-toggle")?.closest(".nav-menu-row");
            row?.classList.add("local-intel-guide-highlight");
            window.setTimeout(() => {
                document.getElementById("senpai-mode-toggle")?.focus({ preventScroll: true });
            }, 0);
        }
    };
    window.closeNavOverflowMenu = close;

    trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        menu.classList.contains("is-visible") ? close() : open();
    });

    // Clicks on the menu's own controls (toggles, AI cost) keep it open.
    menu.addEventListener("click", (e) => e.stopPropagation());

    // The shortcuts row navigates to the overlay — close the menu when it fires.
    menu.querySelector('[onclick*="showKeyboardHelp"]')
        ?.addEventListener("click", close);

    document.addEventListener("click", close);
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && menu.classList.contains("is-visible")) {
            close();
            trigger.focus();
        }
    });
}

function initBrandIntro() {
    const trigger = document.getElementById("brand-intro-trigger");
    const callout = document.getElementById("brand-intro-callout");
    if (!trigger || !callout) return;

    const hideIntro = () => {
        callout.classList.remove("is-visible");
        callout.setAttribute("aria-hidden", "true");
        trigger.setAttribute("aria-expanded", "false");
    };

    const playIntro = (event) => {
        event.preventDefault();

        const costCallout = document.getElementById("brand-cost-callout");
        const costTrigger = document.getElementById("brand-cost-trigger");
        costCallout?.classList.remove("is-visible");
        costCallout?.setAttribute("aria-hidden", "true");
        costTrigger?.setAttribute("aria-expanded", "false");

        window.clearTimeout(_brandIntroTimer);
        window.clearTimeout(_brandIntroAnimTimer);

        if (!prefersReducedMotion()) {
            trigger.classList.remove("is-intro-playing");
            void trigger.offsetWidth;
            trigger.classList.add("is-intro-playing");
            _brandIntroAnimTimer = window.setTimeout(() => {
                trigger.classList.remove("is-intro-playing");
            }, 820);
        }

        callout.classList.add("is-visible");
        callout.setAttribute("aria-hidden", "false");
        trigger.setAttribute("aria-expanded", "true");
        _brandIntroTimer = window.setTimeout(hideIntro, 5200);
    };

    trigger.addEventListener("click", playIntro);
    trigger.addEventListener("keydown", (event) => {
        if (event.key !== " ") return;
        playIntro(event);
    });

    document.addEventListener("click", (event) => {
        if (!callout.contains(event.target) && !trigger.contains(event.target)) {
            window.clearTimeout(_brandIntroTimer);
            hideIntro();
        }
    });
}

document.addEventListener("DOMContentLoaded", () => { initDashboard(); HoldingsBg.init(); });

function refreshDashboardData({
    includeManageHoldings = false,
    includeMarketStatus = true,
    includeRecommendations = false,
    animateButton = false,
} = {}) {
    const refreshButton = document.querySelector(".btn-refresh-data");
    if (animateButton) refreshButton?.classList.remove("is-refreshing");
    if (animateButton && refreshButton && !prefersReducedMotion()) {
        void refreshButton.offsetWidth;
        refreshButton.classList.add("is-refreshing");
    }

    const jobs = [
        loadPortfolioValue(),
        loadPnl(),
        refreshRangePerformanceIfActive(),
    ];
    if (includeManageHoldings && isPortfolioManagerOpen()) {
        jobs.push(loadManageHoldings({ preserveExisting: true }));
    }
    if (includeMarketStatus) jobs.push(updateMarketStatus());
    if (includeRecommendations) jobs.push(loadAnalystRecommendations());

    return Promise.allSettled(jobs).then(results => {
        const failed = results.filter(result => result.status === "rejected");
        if (failed.length) console.warn("Dashboard refresh partially failed:", failed);
        window.AnalyticsCharts?.onRefresh?.();
    }).finally(() => {
        if (animateButton) {
            window.setTimeout(() => refreshButton?.classList.remove("is-refreshing"), 260);
        }
    });
}

function refreshData() {
    refreshDashboardData({ animateButton: true });
}

let _holdingsRefreshInFlight = false;

async function refreshHoldingsTable() {
    if (_holdingsRefreshInFlight || intelligenceLoading || _aiSummariesLoading) return;

    _holdingsRefreshInFlight = true;
    const btn = document.getElementById("btn-holdings-refresh");
    const hub = document.getElementById("holdings-intel-hub");
    if (btn && !prefersReducedMotion()) {
        void btn.offsetWidth;
        btn.classList.add("is-refreshing");
    }
    if (btn) btn.disabled = true;
    if (hub) hub.disabled = true;

    const local = isLocalIntelligenceMode();

    try {
        await loadPortfolioValue();
        renderHoldings();

        if (local) {
            cachedIntelligence = {};
            cachedExplanations = {};
            intelligenceLoaded = false;
            intelligenceExhaustedTickers.clear();
            await loadHoldingIntelligence();
        } else {
            await refreshAiVerdicts({ force: true, claude: true });
            cachedIntelligence = {};
            cachedExplanations = {};
            intelligenceLoaded = false;
            intelligenceExhaustedTickers.clear();
            await loadHoldingIntelligence();
            renderHoldings();
            await window.AnalyticsCharts?.loadAiWidgetInsights?.(true);
        }

        // Re-fetch trend data for any tickers that still have no history (the
        // initial batch fetch may have been rate-limited by yfinance and returned
        // empty for some tickers; empty results are no longer cached, so this
        // second attempt gets a fresh yfinance request for those tickers only).
        const missingTickers = latestHoldings
            .map(h => h.ticker)
            .filter(t => (latestTrendData[t] || []).length < 2);
        if (missingTickers.length) {
            const retryData = await loadTrendData(missingTickers);
            if (Object.keys(retryData).length) {
                Object.assign(latestTrendData, retryData);
                renderHoldings();
            }
        }
    } catch (err) {
        console.warn("Holdings refresh failed:", err);
        showToast("Holdings refresh failed", "danger");
    } finally {
        _holdingsRefreshInFlight = false;
        btn?.classList.remove("is-refreshing");
        if (btn) btn.disabled = false;
        updateHoldingsIntelHub();
    }
}

window.refreshHoldingsTable = refreshHoldingsTable;

function refreshPortfolioMutationInBackground(options = {}) {
    Promise.resolve()
        .then(() => refreshDashboardData({
            includeManageHoldings: true,
            includeRecommendations: true,
            ...options,
        }))
        .catch(err => console.warn("Background portfolio refresh failed:", err));
}

let _forceRefreshInFlight = false;

async function forceRefreshEverything() {
    if (_forceRefreshInFlight) return;
    _forceRefreshInFlight = true;

    const btn = document.getElementById("hud-refresh-all-btn");
    btn?.classList.add("is-refreshing");
    if (btn) btn.disabled = true;

    try {
        await Promise.allSettled([
            refreshDashboardData({
                includeManageHoldings: true,
                includeRecommendations: true,
                animateButton: true,
            }),
            loadWorldMarkets(),
            loadAiCostStats(),
            loadClaudeHeartbeat(),
        ]);
        _hudCountdown = HUD_TOTAL;
        updateHudPopoverCountdown();
        showToast("Dashboard refreshed", "success");
    } catch (err) {
        console.warn("Force refresh failed:", err);
        showToast("Refresh failed", "danger");
    } finally {
        _forceRefreshInFlight = false;
        btn?.classList.remove("is-refreshing");
        if (btn) btn.disabled = false;
    }
}


async function updateMarketStatus() {
    try {
        const res = await fetch("/api/stocks/market-status");
        const data = await res.json();
        const el = document.getElementById("market-status");
        if (el) {
            el.textContent = data.status;
            // Market-open is a *state*, not a gain — use cyan/state, not green.
            el.className = "hero-pill-text " + (data.is_open ? "text-state" : "text-secondary");
        }
        const icon = document.getElementById("market-icon");
        if (icon) {
            icon.style.color = data.is_open ? "var(--color-state)" : "";
            icon.classList.toggle("market-open", !!data.is_open);
        }
    } catch(e) {}
}

const HUD_TOTAL = 300;
const CLAUDE_HEARTBEAT_TOTAL = 120;
let _hudCountdown = HUD_TOTAL;
let _hudCountdownTimer = null;
let _claudeHeartbeatCountdown = CLAUDE_HEARTBEAT_TOTAL;
let _claudeHeartbeatInFlight = false;
let _claudeHeartbeatTimer = null;
let _lastClaudeHeartbeat = null;
let _lastDashboardSyncText = "—";

function formatHudTimer(totalSeconds) {
    const safeSeconds = Math.max(0, Number(totalSeconds) || 0);
    const mins = Math.floor(safeSeconds / 60);
    const secs = safeSeconds % 60;
    return `${mins}:${String(secs).padStart(2, "0")}`;
}

function updateHudPillSummary() {
    const pill = document.getElementById("hud-status-pill");
    if (!pill) return;
    if (isLocalIntelligenceMode()) {
        pill.setAttribute("aria-label", `Refresh in ${formatHudTimer(_hudCountdown)}. Local Intelligence. Open live feed details.`);
    } else {
        const claudeStatus = document.getElementById("claude-heartbeat")?.textContent || "AI";
        pill.setAttribute("aria-label", `Refresh in ${formatHudTimer(_hudCountdown)}. Claude ${claudeStatus}. Open live feed details.`);
    }
    pill.title = "Open live feed details";
}

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
    updateHudPillSummary();
}

function updateClaudeHeartbeatUi(data, checking = false) {
    const pill = document.getElementById("hud-status-pill");
    const brand = document.getElementById("brand-intro-trigger");
    const navToggle = document.getElementById("senpai-nav-toggle");
    const label = document.getElementById("claude-heartbeat");
    const popValue = document.getElementById("hud-pop-claude");
    const popSub = document.getElementById("hud-pop-claude-sub");
    const progress = document.getElementById("hud-claude-progress");
    const live = data?.live === true;
    const offline = data?.live === false;

    pill?.classList.toggle("claude-live", live && !checking);
    pill?.classList.toggle("claude-offline", offline && !checking);
    pill?.classList.toggle("claude-checking", checking);
    brand?.classList.toggle("claude-live", live && !checking);
    brand?.classList.toggle("claude-offline", offline && !checking);
    brand?.classList.toggle("claude-checking", checking);
    navToggle?.classList.toggle("claude-checking", checking);
    if (progress) progress.classList.toggle("is-offline", offline && !checking);

    if (label && !isLocalIntelligenceMode()) {
        label.textContent = checking ? "..." : live ? "Live" : offline ? "Off" : "AI";
    }

    if (popValue) {
        if (checking) {
            popValue.textContent = "Checking...";
        } else if (live) {
            popValue.textContent = `Live${data.latency_ms ? ` · ${data.latency_ms}ms` : ""}`;
        } else {
            popValue.textContent = data?.status === "missing_key" ? "No API key" : "Offline";
        }
    }

    if (popSub) {
        const msg = data?.message || (live ? "Claude API reachable" : "Claude API unavailable");
        popSub.textContent = `${msg}. Next heartbeat in ${formatHudTimer(_claudeHeartbeatCountdown)}`;
    }
    updateHudPillSummary();
}

function updateClaudeHeartbeatCountdown() {
    const progress = document.getElementById("hud-claude-progress");
    const pct = (_claudeHeartbeatCountdown / CLAUDE_HEARTBEAT_TOTAL) * 100;
    if (progress) progress.style.width = `${pct}%`;
    updateClaudeHeartbeatUi(_lastClaudeHeartbeat, _claudeHeartbeatInFlight);
}

async function loadClaudeHeartbeat() {
    if (_claudeHeartbeatInFlight) return;
    _claudeHeartbeatInFlight = true;
    updateClaudeHeartbeatUi(_lastClaudeHeartbeat, true);

    try {
        const res = await fetch("/api/ai/heartbeat");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        _lastClaudeHeartbeat = await res.json();
    } catch (err) {
        console.warn("Claude heartbeat failed:", err);
        _lastClaudeHeartbeat = {
            live: false,
            status: "network_error",
            latency_ms: null,
            message: "Claude API heartbeat failed",
        };
    } finally {
        _claudeHeartbeatInFlight = false;
        _claudeHeartbeatCountdown = CLAUDE_HEARTBEAT_TOTAL;
        applyClaudeApiStatus(_lastClaudeHeartbeat.live);
        updateClaudeHeartbeatUi(_lastClaudeHeartbeat, false);
        updateClaudeHeartbeatCountdown();
    }
}

function startCountdown() {
    // Track the handle so a second call can't leave a previous ticker running.
    // Without this, any re-entry (e.g. re-init after a key reconnect) would stack
    // independent countdowns, each firing its own recursive loadPortfolioValue chain.
    if (_hudCountdownTimer) clearInterval(_hudCountdownTimer);
    _hudCountdown = HUD_TOTAL;
    const initialCountdownEl = document.getElementById("countdown");
    if (initialCountdownEl) {
        initialCountdownEl.textContent = formatHudTimer(_hudCountdown);
        initialCountdownEl.classList.remove("is-soon");
    }
    updateHudPillSummary();
    _hudCountdownTimer = setInterval(() => {
        _hudCountdown--;
        const el = document.getElementById("countdown");
        if (el) {
            const soon = _hudCountdown <= 30;
            el.textContent = formatHudTimer(_hudCountdown);
            el.classList.toggle("is-soon", soon);
        }
        updateHudPopoverCountdown();
        if (_hudCountdown <= 0) {
            clearInterval(_hudCountdownTimer);
            _hudCountdownTimer = null;
            loadPortfolioValue().then(() => {
                Promise.all([loadPnl(), updateMarketStatus()]);
                startCountdown();
            });
        }
    }, 1000);
}

function startClaudeHeartbeat() {
    if (_claudeHeartbeatTimer) clearInterval(_claudeHeartbeatTimer);
    _claudeHeartbeatCountdown = CLAUDE_HEARTBEAT_TOTAL;
    loadClaudeHeartbeat();
    _claudeHeartbeatTimer = setInterval(() => {
        _claudeHeartbeatCountdown = Math.max(0, _claudeHeartbeatCountdown - 1);
        updateClaudeHeartbeatCountdown();
        if (_claudeHeartbeatCountdown <= 0) loadClaudeHeartbeat();
    }, 1000);
}

function initHudPopover() {
    const pill = document.getElementById("hud-status-pill");
    const popover = document.getElementById("hud-popover");
    if (!pill || !popover) return;

    let clockInterval = null;

    function updatePopoverContent() {
        const popUpdated = document.getElementById("hud-pop-updated");
        const popClock = document.getElementById("hud-pop-clock");
        if (popUpdated) popUpdated.textContent = _lastDashboardSyncText;
        if (popClock) popClock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        updateHudPopoverCountdown();
        updateClaudeHeartbeatCountdown();
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

    if (e.key === "Escape") {
        if (closePortfolioManager()) return;
        hideKeyboardHelp();
        return;
    }
    if (e.key === "?")      { showKeyboardHelp(); return; }
    if (e.key === "r" || e.key === "R") { refreshData(); return; }
    if (e.key === "t" || e.key === "T") {
        applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
        return;
    }
    if (e.key === "s" || e.key === "S") {
        applyTextSize(nextTextSize(currentTextSize()), true);
        return;
    }
    if (e.key === "m" || e.key === "M") {
        openPortfolioManager();
        return;
    }
    if (e.key === "i" || e.key === "I") {
        setDashboardZone("holdings");
        loadHoldingIntelligence();
        return;
    }
});

// ── Portfolio Briefing ────────────────────────────────────────────────────────

// Briefings cached per mode AND time range ("local:day", "ai:week", …) so a
// range the user already visited re-renders instantly with the right content.
const _cachedBriefing = {};
const _briefingPending = new Set();  // keys with a fetch in flight (dedupe)
let _briefingActiveMode = null;  // current mode shown in card

function _briefingCacheKey(mode, rangeKey = dashboardTimeRange) {
    return `${mode}:${normalizeTimeRange(rangeKey)}`;
}

function _briefingDefaultMode() {
    return isLocalIntelligenceMode() ? "local" : "ai";
}

// Range-aware movers divider label ("Today's Movers", "Movers · 1W", …).
function _briefingMoversLabel() {
    return dashboardTimeRange === TIME_RANGE.TODAY
        ? "Today's Movers"
        : `Movers · ${timeRangeConfig().label}`;
}

function _briefingSyncSegControl(mode, claudeOffline) {
    const seg = document.getElementById("briefing-seg");
    if (seg) seg.hidden = true;

    const aiBtn   = document.getElementById("briefing-seg-ai");
    const locBtn  = document.getElementById("briefing-seg-local");
    if (!aiBtn || !locBtn) return;

    aiBtn.setAttribute("aria-pressed", String(mode === "ai"));
    locBtn.setAttribute("aria-pressed", String(mode === "local"));
    aiBtn.classList.toggle("briefing-seg-btn--active", mode === "ai");
    locBtn.classList.toggle("briefing-seg-btn--active", mode === "local");

    if (claudeOffline) {
        aiBtn.disabled = true;
        aiBtn.title = "Claude offline — using Local mode";
        const noteEl = document.getElementById("briefing-offline-note");
        if (!noteEl) {
            const note = document.createElement("span");
            note.id = "briefing-offline-note";
            note.className = "briefing-offline-note";
            note.textContent = "Local only — Claude offline";
            const header = document.querySelector("#briefing-card .card-header");
            header?.appendChild(note);
        }
    } else {
        aiBtn.disabled = false;
        aiBtn.title = "";
        document.getElementById("briefing-offline-note")?.remove();
    }
}

function _briefingShowSkeleton(show) {
    const sk = document.getElementById("briefing-skeleton");
    const ct = document.getElementById("briefing-content");
    if (sk) sk.style.display = show ? "" : "none";
    if (ct) {
        if (show) {
            ct.style.opacity = "0";
            ct.style.display = "none";
        } else {
            ct.style.display = "";
            requestAnimationFrame(() => { ct.style.opacity = "1"; });
        }
    }
}

function _briefingBoldTickers(rawText) {
    // Escape first, then bold any 2–5 uppercase-letter word that looks like a ticker
    return escapeHtml(String(rawText || ""))
        .replace(/\b([A-Z]{2,5})\b/g, '<strong class="briefing-inline-ticker">$1</strong>');
}

function _briefingLeadSentiment(text) {
    const t = String(text || "").toLowerCase();
    if (/\b(all \d+ holdings fell|fell today|pull(ed)? back|declined|lost|negative)\b/.test(t)) {
        return "negative";
    }
    if (/\b(up|rose|gained|ahead|positive|green day)\b/.test(t) && !/\b(down|fell|mixed)\b/.test(t)) {
        return "positive";
    }
    if (/\b(down|fell|declined)\b/.test(t)) return "negative";
    if (/\b(mixed|no clear|balanced)\b/.test(t)) return "neutral";
    return "neutral";
}

function _briefingColorizeLead(rawText) {
    let html = _briefingBoldTickers(rawText);

    html = html.replace(/(\([+-]\d+(?:\.\d+)?%\))/g, (match, pct) => {
        const cls = pct.includes("+") ? "is-gain" : pct.includes("-") ? "is-loss" : "";
        return cls ? `<span class="briefing-lead-pct ${cls}">${pct}</span>` : pct;
    });

    html = html.replace(/\b(up|down)\s+(\d+(?:\.\d+)?%)/gi, (_, dir, pct) => {
        const cls = dir.toLowerCase() === "up" ? "is-gain" : "is-loss";
        return `<span class="briefing-lead-word ${cls}">${dir}</span> <span class="briefing-lead-pct ${cls}">${pct}</span>`;
    });

    html = html.replace(/\b([+-]\d+(?:\.\d+)?%)/g, (match) => {
        const cls = match.startsWith("+") ? "is-gain" : match.startsWith("-") ? "is-loss" : "";
        return cls ? `<span class="briefing-lead-pct ${cls}">${match}</span>` : match;
    });

    html = html.replace(/\b(rose|gained|ahead)\b/gi, m =>
        `<span class="briefing-lead-word is-gain">${m}</span>`);
    html = html.replace(/\b(fell|declined|pull(?:ed)? back)\b/gi, m =>
        `<span class="briefing-lead-word is-loss">${m}</span>`);

    return html;
}

function _briefingRenderLeadBlock(text, mode) {
    const sentiment = _briefingLeadSentiment(text);
    const isAi = mode === "ai";
    const eyebrowIcon = isAi ? "bi-stars" : "bi-cpu-fill";
    const eyebrowLabel = isAi
        ? "Portfolio health"
        : (dashboardTimeRange === TIME_RANGE.TODAY
            ? "Today's read"
            : `${timeRangeConfig().label} read`);
    const modeClass = isAi ? "is-ai" : "is-local";

    return `<div class="briefing-lead-block ${modeClass} is-sentiment-${sentiment}">
        <span class="briefing-lead-accent" aria-hidden="true"></span>
        <div class="briefing-lead-inner">
            <div class="briefing-lead-meta">
                <span class="briefing-lead-eyebrow">
                    <i class="bi ${eyebrowIcon}" aria-hidden="true"></i>
                    ${escapeHtml(eyebrowLabel)}
                </span>
            </div>
            <p class="briefing-lead-text">${_briefingColorizeLead(text)}</p>
        </div>
    </div>`;
}

function _briefingAnimateIn(wrap) {
    if (!wrap || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    wrap.classList.add("briefing-enter");
    let delay = 0;

    const lead = wrap.querySelector(".briefing-lead-block");
    if (lead) {
        lead.style.setProperty("--briefing-delay", String(delay));
        delay += 60;
    }

    wrap.querySelectorAll(".briefing-divider").forEach(div => {
        div.style.setProperty("--briefing-delay", String(delay));
        delay += 30;

        let itemDelay = delay;
        const listEl = div.nextElementSibling;
        if (listEl) {
            listEl.querySelectorAll(
                ".briefing-driver-item, .briefing-insight-item, .briefing-mover-row"
            ).forEach(item => {
                item.style.setProperty("--briefing-delay", String(itemDelay));
                itemDelay += 36;
            });
            delay = itemDelay + 20;
        }
    });

    const footer = wrap.querySelector(".briefing-footer");
    if (footer) footer.style.setProperty("--briefing-delay", String(delay));
}

function _briefingRenderAi(data) {
    const content = document.getElementById("briefing-content");
    if (!content) return;

    const esc = s => escapeHtml(String(s || ""));

    const driverItems = (data.drivers || [])
        .map(d => `<div class="briefing-driver-item">${_briefingBoldTickers(d)}</div>`)
        .join("");

    const adjItems = (data.adjustments || [])
        .map(a => `<div class="briefing-insight-item">${_briefingBoldTickers(a)}</div>`)
        .join("");

    const sourceNote = data.source === "local-fallback"
        ? `<span class="briefing-source-note">Local fallback</span>`
        : (data.from_cache ? `<span class="briefing-source-note">Cached</span>` : "");

    const moversSection = driverItems ? `
        <div class="briefing-divider briefing-divider--movers">
            <span class="briefing-divider-label">
                <i class="bi bi-bar-chart-line" aria-hidden="true"></i>
                ${escapeHtml(_briefingMoversLabel())}
            </span>
        </div>
        <div class="briefing-driver-list">${driverItems}</div>` : "";

    const insightsSection = adjItems ? `
        <div class="briefing-divider briefing-divider--insights">
            <span class="briefing-divider-label">
                <i class="bi bi-lightbulb" aria-hidden="true"></i>
                Insights
            </span>
        </div>
        <div class="briefing-insight-list">${adjItems}</div>` : "";

    content.innerHTML = `
        <div class="briefing-ai-wrap">
            ${_briefingRenderLeadBlock(data.health, "ai")}
            ${moversSection}
            ${insightsSection}
            <div class="briefing-footer">
                <span class="briefing-footer-quote">${esc(data.quote)}</span>
                ${sourceNote}
            </div>
        </div>`;
    _briefingAnimateIn(content.querySelector(".briefing-ai-wrap"));
}

function _briefingFirstSentence(text) {
    if (!text) return "";
    const m = text.match(/^.+?[.!?](?:\s|$)/);
    return m ? m[0].trim() : text.slice(0, 88).trim();
}

function _briefingRenderLocal(data) {
    const content = document.getElementById("briefing-content");
    if (!content) return;

    const esc = s => escapeHtml(String(s || ""));

    const moverRows = (data.movers || []).map(m => {
        const isGain = m.day_change_pct >= 0;
        const sign   = isGain ? "gain" : "loss";
        const pct    = (isGain ? "+" : "") + Number(m.day_change_pct).toFixed(2) + "%";
        const dollar = (m.day_change_dollar >= 0 ? "+$" : "–$") +
            Math.abs(m.day_change_dollar).toFixed(2);
        const ctx = esc(_briefingFirstSentence(m.explanation));

        return `
            <div class="briefing-mover-row">
                <span class="briefing-mover-ticker">${esc(m.ticker)}</span>
                <span class="briefing-mover-change text-${sign}">${esc(pct)}</span>
                <span class="briefing-mover-dollar">${esc(dollar)}</span>
                ${ctx ? `<span class="briefing-mover-context">${ctx}</span>` : "<span></span>"}
            </div>`;
    }).join("");

    const moversSection = moverRows ? `
        <div class="briefing-divider briefing-divider--movers">
            <span class="briefing-divider-label">
                <i class="bi bi-bar-chart-line" aria-hidden="true"></i>
                ${escapeHtml(_briefingMoversLabel())}
            </span>
        </div>
        <div class="briefing-mover-grid">${moverRows}</div>` : "";

    content.innerHTML = `
        <div class="briefing-local-wrap">
            ${_briefingRenderLeadBlock(data.lead, "local")}
            ${moversSection}
        </div>`;
    _briefingAnimateIn(content.querySelector(".briefing-local-wrap"));
}

async function loadPortfolioBriefing(mode, forceRefresh = false) {
    const claudeOffline = _isClaudeApiLive === false;
    if (mode === null || mode === undefined) {
        mode = _briefingDefaultMode();
    }
    if (isLocalIntelligenceMode() || claudeOffline) mode = "local";

    _briefingActiveMode = mode;
    _briefingSyncSegControl(mode, claudeOffline);

    const rangeKey = normalizeTimeRange(dashboardTimeRange);
    const cacheKey = _briefingCacheKey(mode, rangeKey);

    // Instant render from cache if available and not forced
    if (_cachedBriefing[cacheKey] && !forceRefresh) {
        _briefingShowSkeleton(false);
        mode === "ai" ? _briefingRenderAi(_cachedBriefing[cacheKey])
                      : _briefingRenderLocal(_cachedBriefing[cacheKey]);
        return;
    }

    // Dedupe identical requests; different mode/range requests may overlap
    // (rapid range switching) — only the one matching the current selection
    // renders when it lands.
    if (_briefingPending.has(cacheKey) && !forceRefresh) return;
    _briefingPending.add(cacheKey);
    _briefingShowSkeleton(true);

    const refreshBtn = document.getElementById("briefing-refresh-btn");
    refreshBtn?.classList.add("is-spinning");

    const isCurrent = () =>
        _briefingActiveMode === mode && normalizeTimeRange(dashboardTimeRange) === rangeKey;

    try {
        const params = new URLSearchParams({ mode, range: rangeKey });
        if (forceRefresh) params.set("force_refresh", "true");
        const res = await fetch(`/api/ai/portfolio-summary?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        _cachedBriefing[cacheKey] = data;
        if (isCurrent()) {
            _briefingShowSkeleton(false);
            mode === "ai" ? _briefingRenderAi(data) : _briefingRenderLocal(data);
        }
    } catch (err) {
        console.warn("Portfolio briefing fetch failed:", err);
        if (isCurrent()) {
            _briefingShowSkeleton(false);
            const ct = document.getElementById("briefing-content");
            if (ct) ct.innerHTML = `<span class="briefing-error">Briefing unavailable — refresh to retry.</span>`;
        }
    } finally {
        _briefingPending.delete(cacheKey);
        refreshBtn?.classList.remove("is-spinning");
    }
}

// ── Portfolio Action Plan ─────────────────────────────────────────────────────

let _actionPlanLoading = false;
let _cachedActionPlan  = null;

const _AP_BUCKET_COLOR = { hold: "is-hold", add: "is-add", trim: "is-trim", exit: "is-exit" };
const _AP_BUCKET_LABEL = { hold: "Hold", add: "Add", trim: "Trim", exit: "Exit" };
const _AP_BUCKET_ICON  = {
    hold: "bi-pause-circle-fill",
    add:  "bi-plus-circle-fill",
    trim: "bi-scissors",
    exit: "bi-door-open-fill",
};

// Regime mood → CSS class for the regime chip
const _AP_REGIME_CLS = {
    risk_on:  "is-risk-on",
    warm:     "is-risk-on",
    hot:      "is-risk-on",
    risk_off: "is-risk-off",
    cold:     "is-risk-off",
    cooling:  "is-risk-off",
    neutral:  "is-neutral",
};

function _apJumpToHoldings() {
    setDashboardZone("holdings");
}

function _actionPlanShowSkeleton(show) {
    const sk = document.getElementById("action-plan-skeleton");
    const ct = document.getElementById("action-plan-content");
    if (sk) sk.hidden = !show;
    if (ct) ct.hidden = show;
}

function _renderActionPlan(data) {
    const content = document.getElementById("action-plan-content");
    if (!content || !data) return;

    const isLocal  = data.source === "local-fallback";
    const headline = escapeHtml(data.headline || "");
    const thesis   = escapeHtml(data.thesis   || "");
    const regime   = data.regime || {};

    // ── Regime chip ──────────────────────────────────────────────────────────
    const rawMood     = (regime.mood || "neutral").toLowerCase().replace(/[^a-z_]/g, "");
    const regimeCls   = _AP_REGIME_CLS[rawMood] || "is-neutral";
    const regimeLabel = regime.label || "";
    const regimeHtml  = regimeLabel
        ? `<span class="ap-regime-chip ${regimeCls}">${escapeHtml(regimeLabel)}</span>`
        : "";

    // ── Mode badge ───────────────────────────────────────────────────────────
    const modeBadge = isLocal
        ? `<span class="ap-mode-badge is-local"><i class="bi bi-cpu-fill" aria-hidden="true"></i> Local</span>`
        : `<span class="ap-mode-badge is-ai"><i class="bi bi-stars" aria-hidden="true"></i> Claude AI</span>`;

    // ── Buckets ───────────────────────────────────────────────────────────────
    const bucketOrder = ["hold", "add", "trim", "exit"];
    const buckets     = data.buckets || {};
    const bucketsHtml = bucketOrder.map(bucket => {
        const items    = buckets[bucket] || [];
        const colorCls = _AP_BUCKET_COLOR[bucket] || "";
        const label    = _AP_BUCKET_LABEL[bucket]  || bucket;
        const icon     = _AP_BUCKET_ICON[bucket]   || "";
        const isEmpty  = !items.length;
        const chipsHtml = isEmpty
            ? `<span class="ap-chip-none">—</span>`
            : items.map(item => {
                const t = escapeHtml(item.ticker || "");
                const r = escapeHtml(item.reason || "");
                return `<span class="ap-chip ${colorCls}" title="${r}">${t}</span>`;
              }).join("");
        return `<div class="ap-bucket has-${bucket}${isEmpty ? " ap-bucket--empty" : ""}">
            <div class="ap-bucket-hdr ${colorCls}">
                <i class="bi ${icon}" aria-hidden="true"></i>
                <span class="ap-bucket-label">${label}</span>
                <span class="ap-bucket-count">${items.length}</span>
            </div>
            <div class="ap-chips">${chipsHtml}</div>
        </div>`;
    }).join("");

    // ── Priority moves ────────────────────────────────────────────────────────
    const moves = (data.priority_moves || []).slice(0, 3);
    const movesHtml = moves.length
        ? `<div class="ap-section-label">Priority moves</div>
           <div class="ap-moves">${moves.map((m, i) => `
               <div class="ap-move">
                   <div class="ap-move-num">${i + 1}</div>
                   <div class="ap-move-text">${escapeHtml(m)}</div>
               </div>`).join("")}</div>`
        : "";

    // ── Best-return note ──────────────────────────────────────────────────────
    const noteHtml = data.best_return_note
        ? `<div class="ap-note">
               <i class="bi bi-bullseye" aria-hidden="true"></i>
               <span>${escapeHtml(data.best_return_note)}</span>
           </div>`
        : "";

    // ── Local upgrade callout ─────────────────────────────────────────────────
    const upgradeHtml = isLocal
        ? `<div class="ap-upgrade-prompt">
               <i class="bi bi-stars" aria-hidden="true"></i>
               <span>Enable Claude AI for a cross-holding, risk-adjusted read with concrete trade sizing.</span>
               <button class="ap-upgrade-btn" onclick="enableClaudeAiAndReload()">Enable Claude AI</button>
           </div>`
        : "";

    const disclaimer = data.disclaimer || FOLIO_SENSE_VERDICT_COPY.disclaimer;

    content.innerHTML = `<div class="ap-wrap">
        <div class="ap-header">
            <div class="ap-headline-group">
                ${headline ? `<div class="ap-headline">${headline}</div>` : ""}
                ${thesis   ? `<p class="ap-thesis">${thesis}</p>`         : ""}
            </div>
            <div class="ap-meta-stack">
                ${regimeHtml}
                ${modeBadge}
            </div>
        </div>
        <div class="ap-buckets">${bucketsHtml}</div>
        ${movesHtml}
        ${noteHtml}
        ${upgradeHtml}
        <div class="ap-footer">
            <button class="ap-cta-btn" onclick="_apJumpToHoldings()">
                <i class="bi bi-table" aria-hidden="true"></i>
                View position details
                <i class="bi bi-arrow-right-short ap-cta-arrow" aria-hidden="true"></i>
            </button>
            <span class="ap-disclaimer">${escapeHtml(disclaimer)}</span>
        </div>
    </div>`;
}

async function loadActionPlan(forceRefresh = false) {
    if (_actionPlanLoading && !forceRefresh) return;

    if (_cachedActionPlan && !forceRefresh) {
        _actionPlanShowSkeleton(false);
        _renderActionPlan(_cachedActionPlan);
        return;
    }

    _actionPlanLoading = true;
    _actionPlanShowSkeleton(true);

    const refreshBtn = document.getElementById("action-plan-refresh-btn");
    refreshBtn?.classList.add("is-spinning");

    try {
        const params = new URLSearchParams();
        if (forceRefresh) params.set("force_refresh", "true");
        // In local mode (or when Claude is offline) use the fast deterministic path
        if (isLocalIntelligenceMode() || _isClaudeApiLive === false) {
            params.set("force_local", "true");
        }
        const res = await fetch(`/api/ai/action-plan?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        _cachedActionPlan = data;
        _actionPlanShowSkeleton(false);
        _renderActionPlan(data);
    } catch (err) {
        console.warn("Action plan fetch failed:", err);
        _actionPlanShowSkeleton(false);
        const ct = document.getElementById("action-plan-content");
        if (ct) ct.innerHTML = `<div class="ap-error">Action plan temporarily unavailable — refresh to retry.</div>`;
    } finally {
        _actionPlanLoading = false;
        refreshBtn?.classList.remove("is-spinning");
    }
}

function initPortfolioBriefing() {
    const seg = document.getElementById("briefing-seg");
    if (!seg) return;

    seg.hidden = true;
    seg.addEventListener("click", e => {
        const btn = e.target.closest(".briefing-seg-btn");
        if (!btn || btn.disabled || seg.hidden) return;
        const newMode = btn.dataset.mode;
        if (newMode === _briefingActiveMode) return;
        if (newMode === "ai" && isLocalIntelligenceMode()) return;
        if (newMode === "local" && !isLocalIntelligenceMode()) return;
        loadPortfolioBriefing(newMode);
    });
}

// ── API Key Panel ─────────────────────────────────────────────────────────────

function initApiKeyPanel() {
    const trigger  = document.getElementById("api-key-trigger");
    const panel    = document.getElementById("api-key-panel");
    const closeBtn = document.getElementById("api-key-panel-close");
    const input    = document.getElementById("api-key-input");
    const reveal   = document.getElementById("api-key-reveal");
    const hint     = document.getElementById("api-key-hint");
    const saveBtn  = document.getElementById("api-key-save");
    const status   = document.getElementById("api-key-status");

    if (!trigger || !panel) return;

    // Only characters that can appear in a real sk-ant-… key
    const KEY_SAFE_RE = /^[A-Za-z0-9_\-]*$/;
    // Full format check (mirrors the server-side regex)
    const KEY_FORMAT_RE = /^sk-ant-[A-Za-z0-9_\-]{20,300}$/;

    function openPanel() {
        panel.classList.add("is-open");
        panel.setAttribute("aria-hidden", "false");
        trigger.setAttribute("aria-expanded", "true");
        input.focus();
    }

    function closePanel() {
        panel.classList.remove("is-open");
        panel.setAttribute("aria-hidden", "true");
        trigger.setAttribute("aria-expanded", "false");
    }

    trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        if (panel.classList.contains("is-open")) {
            closePanel();
        } else {
            openPanel();
        }
    });

    closeBtn.addEventListener("click", closePanel);

    // Close when clicking outside
    document.addEventListener("click", (e) => {
        if (!panel.contains(e.target) && e.target !== trigger) {
            closePanel();
        }
    });

    // Esc closes
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && panel.classList.contains("is-open")) {
            closePanel();
            trigger.focus();
        }
    });

    // Show/hide toggle
    reveal.addEventListener("click", () => {
        const showing = input.type === "text";
        input.type = showing ? "password" : "text";
        reveal.setAttribute("aria-pressed", String(!showing));
        reveal.setAttribute("aria-label", showing ? "Show key" : "Hide key");
        reveal.querySelector("i").className = showing ? "bi bi-eye" : "bi bi-eye-slash";
    });

    // Validate on every keystroke — strip paste garbage and give feedback
    input.addEventListener("input", () => {
        status.textContent = "";
        status.className = "api-key-status";

        const raw = input.value;

        // Strip any characters that can never be part of a valid key
        const safe = raw.split("").filter(c => KEY_SAFE_RE.test(c)).join("");
        if (safe !== raw) {
            input.value = safe;
        }

        if (!safe) {
            hint.textContent = "";
            hint.className = "api-key-hint";
            saveBtn.disabled = true;
            return;
        }

        if (!safe.startsWith("sk-ant-")) {
            hint.textContent = "Keys must start with sk-ant-";
            hint.className = "api-key-hint hint-err";
            saveBtn.disabled = true;
            return;
        }

        if (safe.length < 27) {
            hint.textContent = "Keep pasting — the key isn't complete yet";
            hint.className = "api-key-hint hint-warn";
            saveBtn.disabled = true;
            return;
        }

        if (!KEY_FORMAT_RE.test(safe)) {
            hint.textContent = "Doesn't look right — double-check you copied the full key";
            hint.className = "api-key-hint hint-err";
            saveBtn.disabled = true;
            return;
        }

        hint.textContent = "Key looks good — hit Save & Connect";
        hint.className = "api-key-hint hint-ok";
        saveBtn.disabled = false;
    });

    saveBtn.addEventListener("click", async () => {
        const key = input.value.trim();
        if (!KEY_FORMAT_RE.test(key)) return;

        saveBtn.disabled = true;
        saveBtn.classList.add("is-saving");
        status.textContent = "Saving…";
        status.className = "api-key-status";

        try {
            const res = await fetch("/api/ai/configure-key", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                // Only send the key — nothing else that could be misused
                body: JSON.stringify({ api_key: key }),
            });

            const data = await res.json();

            if (res.ok && data.success) {
                status.textContent = "Connected! AI features are now live.";
                status.className = "api-key-status status-ok";
                hint.textContent = "";
                hint.className = "api-key-hint";
                input.value = "";
                saveBtn.disabled = true;

                // Trigger a fresh heartbeat so the HUD updates immediately
                setTimeout(() => {
                    closePanel();
                    if (typeof loadClaudeHeartbeat === "function") loadClaudeHeartbeat();
                }, 1400);
            } else {
                const msg = typeof data.detail === "string" ? data.detail : "Could not save key. Try again.";
                status.textContent = msg;
                status.className = "api-key-status status-err";
                saveBtn.disabled = false;
            }
        } catch (err) {
            status.textContent = "Network error — check the server is running.";
            status.className = "api-key-status status-err";
            saveBtn.disabled = false;
        } finally {
            saveBtn.classList.remove("is-saving");
        }
    });
}

const SENPAI_WELCOME_SEEN_KEY = "foliosense-senpai-welcome-seen";

// Fed directly from _HOLD_MODE_META (the same source the per-holding hold-mode
// tooltips use) so this list can never drift out of sync with the real tooltips.
function renderSenpaiWelcomeHoldModes() {
    const list = document.getElementById("senpai-welcome-hold-modes");
    if (!list) return;
    list.innerHTML = _HOLD_MODE_ORDER.map(mode => {
        const meta = _HOLD_MODE_META[mode];
        if (!meta) return "";
        return `<li><i class="bi ${meta.icon} lig-list-icon lig-list-icon--cyan" aria-hidden="true"></i>` +
            `<span><strong>${escapeHtml(meta.label)}</strong> — ${escapeHtml(meta.tipBody)}</span></li>`;
    }).join("");
}

function initSenpaiWelcomeGuide() {
    const guide = document.getElementById("senpai-welcome-guide");
    if (!guide) return;

    renderSenpaiWelcomeHoldModes();

    function close() {
        guide.classList.remove("is-visible");
        guide.setAttribute("aria-hidden", "true");
        try { localStorage.setItem(SENPAI_WELCOME_SEEN_KEY, "1"); } catch (_) {}
    }

    document.getElementById("senpai-welcome-dismiss")?.addEventListener("click", close);

    guide.addEventListener("click", (e) => {
        if (!guide.classList.contains("is-visible")) return;
        const panel = guide.querySelector(".portfolio-manager-panel");
        if (!panel?.contains(e.target)) close();
    });

    document.getElementById("senpai-welcome-add-holding")?.addEventListener("click", () => {
        close();
        openPortfolioManager();
    });
}

// Called only after the live holdings fetch resolves (see initDashboard), so this
// reflects real portfolio state rather than a stale cache hydration.
function maybeShowSenpaiWelcomeGuide() {
    const guide = document.getElementById("senpai-welcome-guide");
    if (!guide) return;
    let seen = false;
    try { seen = localStorage.getItem(SENPAI_WELCOME_SEEN_KEY) === "1"; } catch (_) {}
    if (seen || latestHoldings.length > 0) return;
    guide.classList.add("is-visible");
    guide.setAttribute("aria-hidden", "false");
}

async function initDashboard() {
    initThemeToggle();
    initTextSizeToggle();
    initDashboardZones();

    // Paint last-known holdings immediately so the table isn't blank while the
    // live prices fetch; the network response below replaces this in place.
    hydratePortfolioFromCache();

    // Kick off critical data before heavier UI setup.
    const criticalData = Promise.all([
        loadPortfolioValue(),
        loadPnl(),
        updateMarketStatus(),
    ]);

    initBrandIntro();
    initBrandCostCallout();
    initApiKeyPanel();
    initNavOverflow();
    initDashboardSenpai();
    initSenpaiWelcomeGuide();
    initLocalIntelGuide();
    updateAgentStatus({ scanning: false, ready: false, message: "Watching holdings" });
    updateHoldingsRefreshButton();
    initPerformanceTabs();
    initProjectionControls();
    initPortfolioManager();
    initPortfolioBriefing();
    requestAnimationFrame(syncHvtIndicator);
    window.addEventListener("resize", syncHvtIndicator, { passive: true });

    await criticalData;

    maybeShowSenpaiWelcomeGuide();
    startCountdown();
    initHudPopover();
    initTips();
    initHoldingExpandFab();
    initKeyboardHelp();

    scheduleWhenIdle(() => {
        window.AnalyticsCharts?.init?.();
        loadAnalystRecommendations();
        loadWorldMarkets();
        loadPortfolioBriefing();
        loadActionPlan();
        startClaudeHeartbeat();
        ensureAiCostStatsLoaded();
        if (isLocalIntelligenceMode()) loadHoldingIntelligence();
    });
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
let _cachedWorldMarketsForAnalytics = [];

async function loadWorldMarkets() {
    try {
        const res = await fetch("/api/stocks/world-markets");
        if (!res.ok) return;
        const { markets } = await res.json();
        _cachedWorldMarketsForAnalytics = markets || [];
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
        window.AnalyticsCharts?.refreshMarketsTape?.(markets);
    } catch (err) {
        console.warn("World markets unavailable:", err);
        const strip = document.getElementById("world-markets-strip");
        if (strip) strip.innerHTML = `<span style="padding:1rem;color:var(--text-tertiary);font-size:.8rem">Market data unavailable</span>`;
    }
    window.AnalyticsCharts?.refreshMarketsTape?.(_cachedWorldMarketsForAnalytics);
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

function reloadContributionForTicker(ticker) {
    if (isLocalIntelligenceMode()) {
        showToast("Enable Claude AI in menu → Intelligence → Engine to seed ETF holdings.", "info");
        return;
    }
    delete intelligenceRetryState[ticker];
    intelligenceExhaustedTickers.delete(ticker);
    fetchSingleIntelligenceWithRetry(ticker, { aiHoldingsFallback: true });
}

async function fetchSingleIntelligenceWithRetry(ticker, options = {}) {
    const currentAttempt = (intelligenceRetryState[ticker] || 0) + 1;
    intelligenceRetryState[ticker] = currentAttempt;
    intelligenceRetryingTickers.add(ticker);
    renderHoldings();

    try {
        await delay(INTELLIGENCE_RETRY_BASE_DELAY_MS * currentAttempt);
        const params = new URLSearchParams({ retry: String(Date.now()) });
        if (options.aiHoldingsFallback && !isLocalIntelligenceMode()) {
            params.set("ai_holdings_fallback", "true");
        }
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

function _applyIntelBatchPayload(intelData) {
    Object.entries(intelData?.intelligence || {}).forEach(([ticker, intel]) => {
        cachedIntelligence[ticker] = intel;
    });
    (intelData?.incomplete_tickers || []).forEach(ticker => {
        if (!intelligenceRetryState[ticker]) intelligenceRetryState[ticker] = 0;
    });
    scheduleAllocationFocusPanelRefresh();
}

function _applyMovePayload(moveData) {
    Object.entries(moveData?.explanations || {}).forEach(([ticker, exp]) => {
        cachedExplanations[ticker] = exp;
    });
    scheduleAllocationFocusPanelRefresh();
}

function _applyVerdictPayload(verdictData) {
    Object.entries(verdictData?.signals || {}).forEach(([ticker, sig]) => {
        cachedVerdicts[ticker] = sig;
    });
    cachedPortfolioExposure = verdictData?.portfolio_exposure || cachedPortfolioExposure;
    cachedMarketRegime = verdictData?.regime || cachedMarketRegime;
    applyClaudeApiStatus(verdictData?.claude_live ?? null);
    scheduleAllocationFocusPanelRefresh();
    renderPortfolioSnapshot();
}

function _renderAllExpandedIntelRows(tbody) {
    if (!tbody) return;
    Array.from(tbody.querySelectorAll("tr[data-ticker]")).forEach(mainRow => {
        const ticker = mainRow.dataset.ticker;
        const expandRow = mainRow.nextElementSibling;
        if (!expandRow || !expandRow.classList.contains("summary-expand-row")) return;
        const coverageSection = expandRow.querySelector(".intel-coverage-section");
        const moveSection     = expandRow.querySelector(".intel-move-section");
        const verdictSection  = expandRow.querySelector(".intel-verdict-section");
        if (coverageSection) renderHoldingCoverage(coverageSection, cachedIntelligence[ticker]);
        if (moveSection)     renderMoveExplainer(moveSection, cachedExplanations[ticker], cachedIntelligence[ticker]);
        if (verdictSection)  renderAiVerdict(verdictSection, cachedVerdicts[ticker], ticker);
    });
}

function _syncOpenSummaryHeights(tbody) {
    if (!tbody) return;
    requestAnimationFrame(() => {
        tbody.querySelectorAll(".summary-body.open").forEach(body => {
            if (body.style.maxHeight && body.style.maxHeight !== "none") {
                body.style.maxHeight = body.scrollHeight + "px";
            }
        });
    });
}

async function loadTargetedHoldingIntelligence(ticker) {
    const normalized = String(ticker || "").trim().toUpperCase();
    if (!normalized) return;

    const tbody = document.getElementById("holdings-table");
    intelligenceRetryingTickers.add(normalized);
    if (tbody) injectSummaryRows(tbody);
    renderExpandedTicker(normalized);

    try {
        const holdingsFallback = isLocalIntelligenceMode() ? "" : "&ai_holdings_fallback=true";
        const intelP = fetch(`/api/ai/intelligence/${encodeURIComponent(normalized)}?retry=${Date.now()}${holdingsFallback}`);
        const moveP = fetch("/api/ai/move-explanations/all");
        const verdictSuffix = isLocalIntelligenceMode() ? "?force_local=true" : "";
        const verdictP = fetch(`/api/ai/investment-signal/${encodeURIComponent(normalized)}${verdictSuffix}`);

        const [intelRes, moveRes, verdictRes] = await Promise.allSettled([
            intelP, moveP, verdictP,
        ]);

        if (intelRes.status === "fulfilled" && intelRes.value.ok) {
            cachedIntelligence[normalized] = await intelRes.value.json();
            if (marketPulseLoaded(cachedIntelligence[normalized])) {
                intelligenceExhaustedTickers.delete(normalized);
            }
        } else if (!cachedIntelligence[normalized]) {
            cachedIntelligence[normalized] = fallbackIntelligenceForTicker(normalized);
            intelligenceExhaustedTickers.add(normalized);
        }

        if (moveRes.status === "fulfilled" && moveRes.value.ok) {
            const moveData = await moveRes.value.json();
            if (moveData.explanations?.[normalized]) {
                cachedExplanations[normalized] = moveData.explanations[normalized];
            }
        }

        if (verdictRes?.status === "fulfilled" && verdictRes.value.ok) {
            cachedVerdicts[normalized] = await verdictRes.value.json();
        }
    } catch (err) {
        console.warn(`Unable to refresh intelligence for ${normalized}:`, err);
        if (!cachedIntelligence[normalized]) {
            cachedIntelligence[normalized] = fallbackIntelligenceForTicker(normalized);
            intelligenceExhaustedTickers.add(normalized);
        }
    } finally {
        intelligenceRetryingTickers.delete(normalized);
        updateIntelligenceLoadedState();
        renderExpandedTicker(normalized);
        scheduleAllocationFocusPanelRefresh();
        const holding = latestHoldings.find(h => h.ticker === normalized);
        const row = document.querySelector(`tr[data-ticker="${CSS.escape(normalized)}"]`);
        if (holding && row) setCellHtml(row.querySelector('[data-field="day"]'), dayChangeHtml(holding));
    }
}

async function loadHoldingIntelligence(options = {}) {
    const targetTicker = typeof options === "string"
        ? options
        : options?.targetTicker;
    if (targetTicker) {
        await loadTargetedHoldingIntelligence(targetTicker);
        return;
    }

    const tbody = document.getElementById("holdings-table");
    const hub = document.getElementById("holdings-intel-hub");

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
        syncHoldingExpandFab();
        return;
    }

    intelligenceLoading = true;
    intelligenceRetryState = {};
    intelligenceRetryingTickers = new Set();
    intelligenceExhaustedTickers = new Set();
    setAiChecking(true, "Reading positions");
    injectSummaryRows(tbody);
    if (hub) hub.disabled = true;

    try {
        const intelP = fetch("/api/ai/intelligence/all/batch");
        const moveP = fetch("/api/ai/move-explanations/all");
        const verdictP = fetch(intelligenceSignalsUrl());

        const [intelRes, moveRes, verdictRes] = await Promise.all([intelP, moveP, verdictP]);

        if (intelRes.ok) _applyIntelBatchPayload(await intelRes.json());
        if (moveRes.ok) _applyMovePayload(await moveRes.json());
        if (verdictRes?.ok) _applyVerdictPayload(await verdictRes.json());

        await verifyAndRefreshIncompleteIntelligence();
        intelligenceLoaded = updateIntelligenceLoadedState();
        intelligenceLoading = false;
        setAiChecking(false, intelligenceLoaded ? "Insights ready" : "Watching holdings", intelligenceLoaded);

        _renderAllExpandedIntelRows(tbody);
        _syncOpenSummaryHeights(tbody);
        renderHoldings();
        repaintOpenVerdictSparklines();

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
        updateHoldingsIntelHub();
    }
}


// ── Portfolio Management Overlay ────────────────────────────────────────────

let manageHoldingsRequestId = 0;
let manageHoldingsCache = [];
const manageAutoSaveTimers = new Map();
const MANAGE_AUTOSAVE_MS = 400;

const MANAGE_LUCIDE_SVG = {
    "flask-conical": '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
    "trash-2": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "loader-2": '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    anchor: '<path d="M12 22V8"/><path d="M5 12H2a10 10 0 0 0 20 0h-3"/><circle cx="12" cy="5" r="3"/>',
};

function manageLucide(name, className = "manage-lucide") {
    const body = MANAGE_LUCIDE_SVG[name];
    if (!body) return "";
    return `<svg class="${className}" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

function portfolioManagerTriggers() {
    return Array.from(document.querySelectorAll("[aria-controls='portfolioModal'], button[onclick*='openPortfolioManager']"));
}

function isPortfolioManagerOpen() {
    return document.getElementById("portfolioModal")?.classList.contains("is-visible") || false;
}

function setPortfolioManagerTriggerState(open) {
    portfolioManagerTriggers().forEach(trigger => {
        trigger.setAttribute("aria-expanded", String(open));
    });
}

function openPortfolioManager() {
    const popover = document.getElementById("portfolioModal");
    if (!popover) return;
    const wasOpen = popover.classList.contains("is-visible");
    popover.classList.add("is-visible");
    popover.setAttribute("aria-hidden", "false");
    if (!wasOpen) {
        const body = popover.querySelector(".portfolio-manager-body");
        if (body) body.scrollTop = 0;
        const search = document.getElementById("manage-holdings-search");
        if (search) search.value = "";
    }
    setPortfolioManagerTriggerState(true);
    loadManageHoldings({ preserveExisting: true });
}

function closePortfolioManager() {
    const popover = document.getElementById("portfolioModal");
    if (!popover || !popover.classList.contains("is-visible")) return false;
    popover.classList.remove("is-visible");
    popover.setAttribute("aria-hidden", "true");
    setPortfolioManagerTriggerState(false);
    return true;
}

function initPortfolioManager() {
    const popover = document.getElementById("portfolioModal");
    if (!popover) return;
    popover.addEventListener("click", (e) => {
        if (!popover.classList.contains("is-visible")) return;
        const panel = popover.querySelector(".portfolio-manager-panel");
        if (!panel?.contains(e.target)) closePortfolioManager();
    });
    initManageHoldingsSearch();
}

function initManageHoldingsSearch() {
    const input = document.getElementById("manage-holdings-search");
    if (!input || input.dataset.bound) return;
    input.dataset.bound = "true";
    input.addEventListener("input", () => filterManageHoldings(input.value));
}

function updateManageStatsPill(holdings) {
    const pill = document.getElementById("manage-stats-pill");
    if (!pill) return;
    if (!holdings?.length) {
        pill.textContent = "";
        return;
    }
    const research = holdings.filter(h => h.is_watchlist).length;
    const parts = [`${holdings.length} holding${holdings.length === 1 ? "" : "s"}`];
    if (research) parts.push(`${research} research`);
    pill.innerHTML = `<span class="manage-stats-dot" aria-hidden="true"></span>${parts.join(" · ")}`;
}

function filterManageHoldings(query = "") {
    const q = query.trim().toUpperCase();
    const list = document.getElementById("manage-holdings-list");
    const noMatch = document.getElementById("manage-holdings-no-match");
    if (!list) return;

    const cards = list.querySelectorAll(".manage-holding-card:not(.manage-holding-card--skeleton)");
    let visible = 0;
    cards.forEach(card => {
        const ticker = card.dataset.ticker || "";
        const match = !q || ticker.includes(q);
        card.classList.toggle("is-hidden-by-search", !match);
        if (match) visible += 1;
    });

    const hasHoldings = cards.length > 0;
    list.hidden = !hasHoldings;
    if (noMatch) {
        noMatch.hidden = !hasHoldings || visible > 0 || !q;
        const text = document.getElementById("manage-no-match-text");
        if (text && q) text.textContent = `No holdings match “${q}”.`;
    }
}

function setManageSaveStatus(holdingId, state) {
    const el = document.querySelector(`#manage-row-${holdingId} .manage-save-status`);
    if (!el) return;
    el.classList.remove("is-visible", "is-saving", "is-saved", "is-error");
    if (state === "idle") {
        el.innerHTML = "";
        return;
    }
    el.classList.add("is-visible");
    if (state === "saving") {
        el.classList.add("is-saving");
        el.innerHTML = manageLucide("loader-2", "manage-lucide manage-lucide--spin");
    } else if (state === "saved") {
        el.classList.add("is-saved");
        el.innerHTML = manageLucide("check");
        window.setTimeout(() => setManageSaveStatus(holdingId, "idle"), 1500);
    } else if (state === "error") {
        el.classList.add("is-error");
        el.innerHTML = manageLucide("x");
    }
}

function scheduleManageAutoSave(holdingId) {
    clearTimeout(manageAutoSaveTimers.get(holdingId));
    manageAutoSaveTimers.set(holdingId, window.setTimeout(() => {
        manageAutoSaveTimers.delete(holdingId);
        updateHolding(holdingId, { silent: true });
    }, MANAGE_AUTOSAVE_MS));
}

function bindManageHoldingInputs(card, holdingId) {
    if (!card) return;
    const sharesInput = card.querySelector(`#shares-${holdingId}`);
    const costInput = card.querySelector(`#cost-${holdingId}`);
    [sharesInput, costInput].forEach(input => {
        if (!input) return;
        input.addEventListener("input", () => scheduleManageAutoSave(holdingId));
        input.addEventListener("blur", () => {
            clearTimeout(manageAutoSaveTimers.get(holdingId));
            manageAutoSaveTimers.delete(holdingId);
            updateHolding(holdingId, { silent: true });
        });
    });
}

function renderManageHoldingCard(h) {
    const tickerLabel = escapeHtml(h.ticker);
    const tickerArg = inlineJsString(h.ticker);
    const isWatchlist = !!h.is_watchlist;
    const holdClass = h.hold_class || "auto";
    const modeClass = _manageHoldModeCardClass(holdClass);
    const researchBadge = isWatchlist
        ? `<span class="manage-card-badge">${manageLucide("flask-conical", "manage-lucide manage-lucide--inline")}Research</span>`
        : "";
    const removeBtnClass = isWatchlist ? "manage-remove-btn manage-remove-btn--research" : "manage-remove-btn";
    const removeIcon = isWatchlist ? "x" : "trash-2";
    const removeLabel = isWatchlist ? `Discard ${tickerLabel}` : `Remove ${tickerLabel}`;

    return `
        <article class="manage-holding-card${isWatchlist ? " is-watchlist" : ""}${modeClass ? ` ${modeClass}` : ""}"
                 id="manage-row-${h.id}" role="listitem" data-ticker="${tickerLabel}" data-hold-mode="${escapeHtml(holdClass)}">
            <div class="manage-card-top">
                <div class="manage-card-ticker">
                    <span class="manage-card-ticker-symbol">${tickerLabel}</span>
                    ${researchBadge}
                </div>
                <div class="manage-card-top-actions">
                    <span class="manage-save-status" aria-live="polite"></span>
                    <button type="button" class="${removeBtnClass}"
                            onclick="removeHolding(${h.id}, ${tickerArg}, ${isWatchlist})"
                            aria-label="${removeLabel}">
                        ${manageLucide(removeIcon)}
                    </button>
                </div>
            </div>
            <div class="manage-card-fields">
                <label class="manage-card-field" for="shares-${h.id}">
                    <span class="manage-card-field-label">Shares</span>
                    <input type="number" value="${h.shares}" min="${isWatchlist ? "0" : "0.001"}" step="0.001"
                           class="form-control form-control-sm" id="shares-${h.id}"
                           data-watchlist="${isWatchlist ? "true" : "false"}">
                </label>
                <label class="manage-card-field" for="cost-${h.id}">
                    <span class="manage-card-field-label">Avg cost</span>
                    <input type="number" value="${h.avg_cost || ""}" min="0.01" step="0.01"
                           class="form-control form-control-sm" id="cost-${h.id}" placeholder="—">
                </label>
            </div>
            <div class="manage-card-footer">
                ${_renderManageHoldModeSection(h)}
            </div>
        </article>
    `;
}

function renderManageHoldingsLoading(list) {
    const empty = document.getElementById("manage-holdings-empty");
    const noMatch = document.getElementById("manage-holdings-no-match");
    if (empty) empty.hidden = true;
    if (noMatch) noMatch.hidden = true;
    list.hidden = false;
    list.innerHTML = Array.from({ length: 4 }, () => `
        <div class="manage-holding-card manage-holding-card--skeleton" aria-hidden="true">
            <span class="shimmer-line" style="width:58%;margin-bottom:.55rem"></span>
            <span class="shimmer-line" style="width:88%;margin-bottom:.45rem"></span>
            <span class="shimmer-line" style="width:72%"></span>
        </div>
    `).join("");
}

async function loadManageHoldings({ preserveExisting = false } = {}) {
    const list = document.getElementById("manage-holdings-list");
    const empty = document.getElementById("manage-holdings-empty");
    const popover = document.getElementById("portfolioModal");
    if (!list) return;

    const requestId = ++manageHoldingsRequestId;
    const hasRenderedCards = list.querySelector(".manage-holding-card:not(.manage-holding-card--skeleton)");
    const skipSkeleton = preserveExisting && hasRenderedCards;
    popover?.classList.add("is-loading");
    if (!skipSkeleton && (!preserveExisting || list.children.length === 0)) {
        renderManageHoldingsLoading(list);
    }

    try {
        const res = await fetch("/api/portfolio/holdings");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (requestId !== manageHoldingsRequestId) return;

        manageHoldingsCache = data.holdings || [];
        updateManageStatsPill(manageHoldingsCache);
        list.innerHTML = "";

        if (!manageHoldingsCache.length) {
            list.hidden = true;
            if (empty) empty.hidden = false;
            filterManageHoldings(document.getElementById("manage-holdings-search")?.value || "");
            return;
        }

        if (empty) empty.hidden = true;
        list.hidden = false;
        manageHoldingsCache.forEach(h => {
            list.insertAdjacentHTML("beforeend", renderManageHoldingCard(h));
            bindManageHoldingInputs(document.getElementById(`manage-row-${h.id}`), h.id);
        });
        filterManageHoldings(document.getElementById("manage-holdings-search")?.value || "");
    } catch (err) {
        console.warn("Unable to load manage holdings:", err);
        if (requestId === manageHoldingsRequestId && !preserveExisting) {
            list.innerHTML = `<div class="manage-holdings-empty"><p class="manage-empty-title text-danger">Unable to load holdings</p></div>`;
            list.hidden = false;
        }
    } finally {
        if (requestId === manageHoldingsRequestId) popover?.classList.remove("is-loading");
    }
}


async function updateHolding(holdingId, options = {}) {
    const silent = options.silent === true;
    const card = document.getElementById(`manage-row-${holdingId}`);
    const sharesInput = document.getElementById(`shares-${holdingId}`);
    const costInput = document.getElementById(`cost-${holdingId}`);
    const isWatchlist = sharesInput?.dataset.watchlist === "true";
    const sharesRaw = sharesInput?.value?.trim() ?? "";
    const shares = Number(sharesRaw);
    const costRaw = costInput?.value?.trim() ?? "";
    const avgCost = costRaw ? Number(costRaw) : null;
    const holdClass = card?.dataset.holdMode
        || card?.querySelector(".manage-hold-mode-box.is-active")?.dataset.holdMode
        || "auto";

    if (!isWatchlist && (!Number.isFinite(shares) || shares <= 0)) {
        if (silent) setManageSaveStatus(holdingId, "error");
        else showToast("Shares must be a positive number", "danger");
        return;
    }
    if (isWatchlist && sharesRaw && (!Number.isFinite(shares) || shares < 0)) {
        if (silent) setManageSaveStatus(holdingId, "error");
        else showToast("Research shares must be zero or greater", "danger");
        return;
    }
    if (costRaw && (!Number.isFinite(avgCost) || avgCost <= 0)) {
        if (silent) setManageSaveStatus(holdingId, "error");
        else showToast("Average cost must be a positive number", "danger");
        return;
    }

    if (silent) {
        setManageSaveStatus(holdingId, "saving");
        card?.classList.add("is-saving");
    }

    const payload = { avg_cost: avgCost, hold_class: holdClass };
    if (!isWatchlist || (Number.isFinite(shares) && shares > 0)) payload.shares = shares;

    const res = await fetch(`/api/portfolio/holdings/${holdingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    card?.classList.remove("is-saving");
    if (res.ok) {
        if (silent) setManageSaveStatus(holdingId, "saved");
        else showToast("Holding updated!", "success");
        refreshPortfolioMutationInBackground();
        refreshAiVerdicts();
    } else {
        const err = await res.json().catch(() => ({}));
        if (silent) setManageSaveStatus(holdingId, "error");
        showToast(apiErrorMessage(err, "Update failed"), "danger");
    }
}

async function refreshAiVerdicts(options = {}) {
    const force = options.force === true;
    const useClaude = options.claude === true && !_forcedLocalMode;
    if (!force && !useClaude && !Object.keys(cachedVerdicts).length && !intelligenceLoaded && !intelligenceLoading) {
        return;
    }
    try {
        const res = await fetch(intelligenceSignalsUrl({ claude: useClaude }));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        Object.entries(data.signals || {}).forEach(([ticker, sig]) => {
            cachedVerdicts[ticker] = sig;
        });
        cachedPortfolioExposure = data.portfolio_exposure || cachedPortfolioExposure;
        cachedMarketRegime = data.regime || cachedMarketRegime;
        applyClaudeApiStatus(data.claude_live ?? null);
        renderPortfolioSnapshot();
        document.querySelectorAll("tr[data-ticker]").forEach(mainRow => {
            const ticker = mainRow.dataset.ticker;
            const verdictSection = mainRow.nextElementSibling?.querySelector(".intel-verdict-section");
            if (verdictSection) renderAiVerdict(verdictSection, cachedVerdicts[ticker], ticker);
        });
        repaintOpenVerdictSparklines();
    } catch (err) {
        console.warn("Unable to refresh verdicts:", err);
    }
}

async function generateAiHoldingSummaries() {
    if (isLocalIntelligenceMode() || _isClaudeApiLive === false) return;
    if (_aiSummariesLoading) return;

    _aiSummariesLoading = true;
    const hub = document.getElementById("holdings-intel-hub");
    hub?.classList.add("is-loading");
    if (hub) hub.disabled = true;
    setAiChecking(true, "Claude narrating holdings", false, true);

    try {
        await refreshAiVerdicts({ force: true, claude: true });
        if (latestHoldings.length) renderHoldings();
        const tbody = document.getElementById("holdings-table");
        if (tbody) {
            _renderAllExpandedIntelRows(tbody);
            _syncOpenSummaryHeights(tbody);
        }
        await window.AnalyticsCharts?.loadAiWidgetInsights?.(true);
        _cachedActionPlan = null;
        await loadActionPlan();
        showToast("Claude summaries ready", "success");
    } catch (err) {
        console.warn("Claude summaries failed:", err);
        showToast("Claude summaries unavailable", "danger");
    } finally {
        _aiSummariesLoading = false;
        hub?.classList.remove("is-loading");
        setAiChecking(false, intelligenceLoaded ? "Insights ready" : "Watching holdings", intelligenceLoaded);
        updateHoldingsIntelHub();
    }
}

window.generateAiHoldingSummaries = generateAiHoldingSummaries;

async function setHoldMode(event, holdingId, ticker, mode) {
    event?.stopPropagation();
    event?.preventDefault();
    if (!holdingId) {
        showToast("Open Manage Holdings to set a mode", "info");
        return;
    }
    const nextClass = _HOLD_MODE_META[mode] ? mode : "auto";
    const holding = latestHoldings.find(h => h.id === holdingId || h.ticker === ticker) || {};
    const prevClass = holding.hold_class || "auto";
    if (prevClass === nextClass) return;

    // Optimistic update — apply immediately so the UI responds without waiting for the network
    latestHoldings = latestHoldings.map(h => (
        h.id === holdingId || h.ticker === ticker ? { ...h, hold_class: nextClass } : h
    ));
    if (cachedVerdicts[ticker]) {
        cachedVerdicts[ticker] = { ...cachedVerdicts[ticker], hold_class: nextClass };
    }
    _syncHoldModeStrip(ticker, nextClass);
    _syncManageHoldModeCard(holdingId, nextClass);

    // Lock the grid during the PUT to prevent double-tap
    const grid = document.querySelector(`#manage-row-${holdingId} .manage-hold-mode-grid`);
    grid?.classList.add("is-saving");

    try {
        const res = await fetch(`/api/portfolio/holdings/${holdingId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hold_class: nextClass }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const label = _HOLD_MODE_META[nextClass]?.label || nextClass;
        showToast(`${ticker}: ${label} mode`, "success");
        refreshPortfolioMutationInBackground({ includeRecommendations: false });
        refreshAiVerdicts();
    } catch (err) {
        // Rollback to the previous mode on failure
        latestHoldings = latestHoldings.map(h => (
            h.id === holdingId || h.ticker === ticker ? { ...h, hold_class: prevClass } : h
        ));
        if (cachedVerdicts[ticker]) {
            cachedVerdicts[ticker] = { ...cachedVerdicts[ticker], hold_class: prevClass };
        }
        _syncHoldModeStrip(ticker, prevClass);
        _syncManageHoldModeCard(holdingId, prevClass);
        console.warn("Unable to set hold mode:", err);
        showToast("Mode update failed", "danger");
    } finally {
        grid?.classList.remove("is-saving");
    }
}

window.setHoldMode = setHoldMode;

async function toggleAnchorHold(event, holdingId, ticker) {
    event?.stopPropagation();
    event?.preventDefault();
    if (!holdingId) {
        showToast("Open Manage Holdings to set Anchor", "info");
        return;
    }
    const holding = latestHoldings.find(h => h.id === holdingId || h.ticker === ticker) || {};
    const nextClass = holding.hold_class === "anchor" ? "auto" : "anchor";
    await setHoldMode(event, holdingId, ticker, nextClass);
}


async function removeHolding(holdingId, ticker, isWatchlist = false) {
    const msg = isWatchlist
        ? `Discard ${ticker} research position? This won't affect your P&L or performance.`
        : `Remove ${ticker} from your portfolio? This will record any realized gain/loss.`;
    if (!confirm(msg)) return;

    const res = await fetch(`/api/portfolio/holdings/${holdingId}`, {
        method: "DELETE"
    });
    if (res.ok) {
        document.getElementById(`manage-row-${holdingId}`)?.remove();
        manageHoldingsCache = manageHoldingsCache.filter(h => h.id !== holdingId);
        updateManageStatsPill(manageHoldingsCache);
        const list = document.getElementById("manage-holdings-list");
        const empty = document.getElementById("manage-holdings-empty");
        if (list && !manageHoldingsCache.length) {
            list.hidden = true;
            if (empty) empty.hidden = false;
        } else {
            filterManageHoldings(document.getElementById("manage-holdings-search")?.value || "");
        }
        showToast(
            isWatchlist ? `${ticker} research position discarded` : `${ticker} removed`,
            isWatchlist ? "success" : "warning"
        );
        refreshPortfolioMutationInBackground();
    }
}

async function removeTrade(tradeId, ticker) {
    if (!confirm("Remove this realized sale from your P&L? This adjusts your realized gain.")) return;

    const res = await fetch(`/api/portfolio/trades/${tradeId}`, { method: "DELETE" });
    if (res.ok) {
        showToast(`Removed realized sale for ${ticker}`, "warning");
        await Promise.allSettled([loadPnl(), loadPortfolioValue()]);
    } else {
        const err = await res.json().catch(() => ({}));
        showToast(apiErrorMessage(err, "Unable to remove realized sale"), "danger");
    }
}

function syncAddHoldingSharesRequirement() {
    const watchlist = document.getElementById("new-watchlist");
    const shares = document.getElementById("new-shares");
    if (!watchlist || !shares) return;
    const researchMode = !!watchlist.checked;
    shares.required = !researchMode;
    shares.min = researchMode ? "0" : "0.001";
    shares.placeholder = researchMode ? "Shares (optional)" : "Shares";
}

document.getElementById("new-watchlist")?.addEventListener("change", syncAddHoldingSharesRequirement);
syncAddHoldingSharesRequirement();

document.getElementById("new-ticker")?.addEventListener("input", (event) => {
    const input = event.target;
    const normalized = input.value.toUpperCase();
    if (input.value !== normalized) input.value = normalized;
    const hasText = normalized.trim().length > 0;
    input.classList.toggle("is-invalid", hasText && !TICKER_PATTERN.test(normalized.trim()));
    if (hasText && TICKER_PATTERN.test(normalized.trim())) {
        document.getElementById("add-msg")?.classList.remove("text-danger", "add-msg-with-suggestions");
    }
});

function renderAddHoldingError(err, fallback = "Error adding holding") {
    const msg = document.getElementById("add-msg");
    const tickerInput = document.getElementById("new-ticker");
    if (!msg) return;
    const detail = err?.detail;
    const suggestions = Array.isArray(detail?.suggestions) ? detail.suggestions.slice(0, 3) : [];
    msg.className = "small text-danger add-msg-with-suggestions";
    tickerInput?.classList.add("is-invalid");

    if (!suggestions.length) {
        msg.textContent = apiErrorMessage(err, fallback);
        return;
    }

    msg.innerHTML = `
        <span>${escapeHtml(apiErrorMessage(err, fallback))}</span>
        <span class="ticker-suggestion-list" aria-label="Ticker suggestions">
            ${suggestions.map(item => `
                <button type="button" class="ticker-suggestion-chip"
                        data-ticker="${escapeHtml(item.ticker || "")}">
                    <strong>${escapeHtml(item.ticker || "")}</strong>
                    <span>${escapeHtml(item.name || "Unknown security")}</span>
                    ${item.exchange ? `<em>${escapeHtml(item.exchange)}</em>` : ""}
                </button>
            `).join("")}
        </span>`;

    msg.querySelectorAll(".ticker-suggestion-chip").forEach(button => {
        button.addEventListener("click", (e) => {
            e.stopPropagation();
            const tickerInput = document.getElementById("new-ticker");
            if (tickerInput) {
                tickerInput.value = button.dataset.ticker || "";
                tickerInput.classList.remove("is-invalid");
                tickerInput.focus();
            }
            msg.className = "small text-secondary";
            msg.textContent = `Using ${button.dataset.ticker}. Add shares, then try again.`;
        });
    });
}

function setAddHoldingBusy(form, busy, ticker = "") {
    const button = form?.querySelector("#add-holding-submit") || form?.querySelector("button[type='submit']");
    if (!button) return;
    if (!button.dataset.idleHtml) button.dataset.idleHtml = button.innerHTML;
    button.disabled = busy;
    button.innerHTML = busy
        ? `${manageLucide("loader-2", "manage-lucide manage-lucide--btn manage-lucide--spin")} Checking ${escapeHtml(ticker || "ticker")}`
        : button.dataset.idleHtml;
}


document.getElementById("add-holding-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = document.getElementById("add-msg");
    const tickerInput = document.getElementById("new-ticker");
    const ticker = tickerInput.value.trim().toUpperCase();
    const sharesRaw = document.getElementById("new-shares").value.trim();
    const shares = Number(sharesRaw);
    const avgCostRaw = document.getElementById("new-avgcost").value.trim();
    const avgCost = avgCostRaw ? Number(avgCostRaw) : null;
    const isWatchlist = document.getElementById("new-watchlist")?.checked || false;
    tickerInput.value = ticker;
    tickerInput.classList.remove("is-invalid");

    if (!ticker) {
        msg.className = "small text-danger";
        msg.textContent = "Ticker is required";
        tickerInput.classList.add("is-invalid");
        tickerInput.focus();
        return;
    }
    if (!TICKER_PATTERN.test(ticker)) {
        msg.className = "small text-danger";
        msg.textContent = "Ticker can use only letters, numbers, '.', '-', or '^' and must be 10 characters or fewer.";
        tickerInput.classList.add("is-invalid");
        tickerInput.focus();
        return;
    }
    if (!isWatchlist && (!Number.isFinite(shares) || shares <= 0)) {
        msg.className = "small text-danger";
        msg.textContent = "Shares must be a positive number";
        return;
    }
    if (isWatchlist && sharesRaw && (!Number.isFinite(shares) || shares < 0)) {
        msg.className = "small text-danger";
        msg.textContent = "Research shares must be zero or greater";
        return;
    }
    if (avgCostRaw && (!Number.isFinite(avgCost) || avgCost <= 0)) {
        msg.className = "small text-danger";
        msg.textContent = "Average cost must be a positive number";
        return;
    }

    const payload = { ticker, avg_cost: avgCost, is_watchlist: isWatchlist };
    if (!isWatchlist || (Number.isFinite(shares) && shares > 0)) payload.shares = shares;

    msg.className = "small text-secondary";
    msg.textContent = `Checking ${ticker}...`;
    setAddHoldingBusy(e.target, true, ticker);

    try {
        const res = await fetch("/api/portfolio/holdings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (res.ok) {
            const data = await res.json();
            const optimisticShares = Number.isFinite(shares) ? shares : 0;
            const optimisticPrice = avgCost || 0;
            latestHoldings = latestHoldings
                .filter(h => h.ticker !== ticker)
                .concat([{
                    id: data.id,
                    ticker,
                    name: ticker,
                    shares: optimisticShares,
                    current_price: optimisticPrice,
                    avg_cost: avgCost || 0,
                    current_value: Math.round(optimisticShares * optimisticPrice * 100) / 100,
                    cost_basis: Math.round(optimisticShares * (avgCost || 0) * 100) / 100,
                    unrealized_gain: 0,
                    unrealized_gain_pct: 0,
                    total_return_pct: null,
                    day_change: 0,
                    day_change_pct: 0,
                    daily_value_change: 0,
                    allocation_pct: 0,
                    is_watchlist: isWatchlist,
                    hold_class: "auto",
                }]);
            updateHoldingsFilterCounts();
            renderHoldings();

            msg.className = "small text-success";
            msg.textContent = isWatchlist ? `${ticker} added in research mode!` : `${ticker} added!`;
            e.target.reset();
            tickerInput.classList.remove("is-invalid");
            syncAddHoldingSharesRequirement();
            loadManageHoldings({ preserveExisting: true });
            refreshPortfolioMutationInBackground();
            if (intelligenceLoaded) {
                msg.className = "small text-info";
                msg.textContent = `${ticker} added. Loading intel for the new row...`;
                loadHoldingIntelligence({ targetTicker: ticker })
                    .then(() => {
                        msg.className = "small text-success";
                        msg.textContent = `${ticker} intel ready.`;
                    })
                    .catch(() => {
                        msg.className = "small text-warning";
                        msg.textContent = `${ticker} added. Intel can be retried from Holding Intel.`;
                    });
            }
        } else {
            const err = await res.json().catch(() => ({}));
            renderAddHoldingError(err, "Error adding holding");
        }
    } catch (err) {
        msg.className = "small text-danger";
        msg.textContent = "Unable to check ticker. Try again.";
    } finally {
        setAddHoldingBusy(e.target, false);
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
    // Scope to the holdings table — the allocation breakdown table also carries
    // data-ticker rows and sits earlier in the DOM (in a different zone).
    const tableBody = document.getElementById("holdings-table");
    const row = (tableBody || document).querySelector(`tr[data-ticker="${CSS.escape(ticker)}"]`);
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
    if (!ticker) return;
    // The summary cards live in Overview; the holdings table is in its own zone.
    // Switch there first, then highlight once the pane is laid out.
    setDashboardZone("holdings");
    requestAnimationFrame(() => highlightHolding(ticker));
}

// Open portfolio manager from the Holdings count card click
function openManageFromCard() {
    openPortfolioManager();
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
    if (document.documentElement.dataset.tipsDelegated === "true") return;
    document.documentElement.dataset.tipsDelegated = "true";

    let hideTimeout = null;
    let activeTrigger = null;

    const hideTip = () => {
        clearTimeout(hideTimeout);
        activeTrigger = null;
        popover.classList.remove("tip-visible");
        popover.setAttribute("aria-hidden", "true");
    };

    const tipTriggerFor = target => target instanceof Element
        ? target.closest(".tip-trigger")
        : null;

    const showTip = trigger => {
        clearTimeout(hideTimeout);
        activeTrigger = trigger;
        const title   = trigger.dataset.tipTitle   || "";
        const body    = trigger.dataset.tipBody    || "";
        const hint    = trigger.dataset.tipHint    || "";
        const icon    = trigger.dataset.tipIcon    || "bi-info-circle-fill";
        const variant = trigger.dataset.tipVariant || "";

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

        const rect = trigger.getBoundingClientRect();
        const popW = Math.min(
            popover.offsetWidth || (variant === "ai" ? 304 : 252),
            window.innerWidth - 20,
        );
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
    };

    document.addEventListener("mouseover", event => {
        const trigger = tipTriggerFor(event.target);
        if (!trigger || trigger.contains(event.relatedTarget)) return;
        showTip(trigger);
    });
    document.addEventListener("mouseout", event => {
        const trigger = tipTriggerFor(event.target);
        if (!trigger || trigger !== activeTrigger || trigger.contains(event.relatedTarget)) return;
        hideTimeout = setTimeout(hideTip, 160);
    });
    document.addEventListener("focusin", event => {
        const trigger = tipTriggerFor(event.target);
        if (trigger) showTip(trigger);
    });
    document.addEventListener("focusout", event => {
        const trigger = tipTriggerFor(event.target);
        if (trigger && trigger === activeTrigger) hideTimeout = setTimeout(hideTip, 160);
    });
    window.addEventListener("scroll", hideTip, { passive: true, capture: true });
    window.addEventListener("resize", hideTip, { passive: true });
    document.addEventListener("click", event => {
        if (activeTrigger && !activeTrigger.contains(event.target)) hideTip();
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") hideTip();
    });
}

/* ── Holdings table canvas — active only during AI scan ─────────────────── */
const HoldingsBg = (() => {
    const MIN_DOTS      = 12;
    const MAX_DOTS      = 24;
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

        // connections — single batched stroke (uniform opacity for speed)
        ctx.lineWidth = 0.8;
        ctx.strokeStyle = `rgba(${cyan},${dark ? 0.14 : 0.09})`;
        ctx.beginPath();
        for (let i = 0; i < dots.length; i++) {
            for (let j = i + 1; j < dots.length; j++) {
                const dx = dots[i].x - dots[j].x;
                const dy = dots[i].y - dots[j].y;
                if (dx * dx + dy * dy < CONN_DIST_SQ) {
                    ctx.moveTo(dots[i].x, dots[i].y);
                    ctx.lineTo(dots[j].x, dots[j].y);
                }
            }
        }
        ctx.stroke();

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

// ── News zone ─────────────────────────────────────────────────────────────────

let _newsLoaded = false;
let _newsLoadPromise = null;
let _newsFeedData = null;   // cached feed response

/**
 * Format a date-ish value as a relative time string ("3h ago", "2d ago").
 * Accepts ISO-8601 strings, Date objects, or epoch millis.
 * Falls back to an empty string on parse failure.
 */
function timeAgo(value) {
    if (!value) return "";
    let date;
    if (value instanceof Date) {
        date = value;
    } else if (typeof value === "number") {
        date = new Date(value < 1e12 ? value * 1000 : value);
    } else {
        date = new Date(String(value));
    }
    if (isNaN(date.getTime())) return "";

    const diffMs  = Date.now() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60)           return "just now";
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60)           return `${diffMin}m ago`;
    const diffHr  = Math.floor(diffMin / 60);
    if (diffHr  < 24)           return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr  / 24);
    if (diffDay < 30)           return `${diffDay}d ago`;
    const diffMon = Math.floor(diffDay / 30);
    if (diffMon < 12)           return `${diffMon}mo ago`;
    return `${Math.floor(diffMon / 12)}y ago`;
}

/** Show/hide the news loading skeleton. */
function _newsShowLoading(show) {
    const el = document.getElementById("news-loading");
    if (el) el.hidden = !show;
}

/** Show/hide the feed container. */
function _newsShowFeed(show) {
    const el = document.getElementById("news-feed-wrap");
    if (el) el.hidden = !show;
}

/** Show/hide the empty state. */
function _newsShowEmpty(show) {
    const el = document.getElementById("news-empty");
    if (el) el.hidden = !show;
}

/** Clear the AI briefing/themes section text (used when switching to local). */
function _newsClearAiSection() {
    const body = document.getElementById("news-briefing-body");
    if (body) body.innerHTML = "";
    const row = document.getElementById("news-themes-row");
    if (row) row.innerHTML = "";
}

/**
 * Render a single article card for the news feed.
 * All text is inserted via textContent or escapeHtml to prevent XSS.
 */
function _newsArticleCardHtml(item) {
    const thumb = item.thumbnail_url
        ? `<img class="news-article-thumb" src="${escapeHtml(item.thumbnail_url)}"
                alt="" loading="lazy" onerror="this.style.display='none'">`
        : "";
    const timeStr = item.published_at ? timeAgo(item.published_at) : "";
    const meta    = [escapeHtml(item.source), timeStr].filter(Boolean).join(" · ");
    const href    = item.url ? escapeHtml(item.url) : "#";
    const target  = item.url ? 'target="_blank" rel="noopener noreferrer"' : "";

    return `<article class="news-article-card">
        ${thumb}
        <div class="news-article-body">
            <a class="news-article-title" href="${href}" ${target}>${escapeHtml(item.title)}</a>
            <div class="news-article-meta">${meta}</div>
            ${item.summary ? `<p class="news-article-summary">${escapeHtml(item.summary)}</p>` : ""}
        </div>
    </article>`;
}

/**
 * Render a holding group block using a native <details>/<summary> dropdown.
 * The browser handles show/hide with zero JS overhead; chevron is CSS-only.
 */
function _newsGroupHtml(holding) {
    const watchBadge = holding.is_watchlist
        ? `<span class="news-watchlist-badge">Research</span>`
        : "";
    const articles = holding.items.length
        ? holding.items.map(_newsArticleCardHtml).join("")
        : `<p class="news-no-articles">No recent news for this holding.</p>`;

    const sector = holding.sector
        ? `<span class="news-group-sector">${escapeHtml(holding.sector)}</span>`
        : "";

    const count = holding.items.length;
    const countBadge = `<span class="news-group-count" aria-label="${count} article${count !== 1 ? "s" : ""}">${count}</span>`;

    // First holding with news is open by default; the rest are collapsed.
    const openAttr = (holding._isFirst && count > 0) ? " open" : "";

    return `<details class="news-group"${openAttr}>
        <summary class="news-group-header">
            <span class="news-group-chip">${escapeHtml(holding.ticker)}</span>
            <span class="news-group-name">${escapeHtml(holding.company_name)}</span>
            ${watchBadge}
            ${sector}
            <span class="news-group-right">
                ${countBadge}
                <i class="bi bi-chevron-down news-group-chevron" aria-hidden="true"></i>
            </span>
        </summary>
        <div class="news-article-list">
            ${articles}
        </div>
    </details>`;
}

/** Render the feed section from cached feed data. */
function _newsRenderFeed(feedData) {
    const wrap = document.getElementById("news-feed-wrap");
    if (!wrap) return;

    const holdings = (feedData.holdings || []);
    const hasAnyNews = holdings.some(h => h.items && h.items.length > 0);

    if (!holdings.length || !hasAnyNews) {
        _newsShowFeed(false);
        _newsShowEmpty(true);
        return;
    }

    // Mark the first holding that has news so it opens by default.
    let firstMarked = false;
    const annotated = holdings.map(h => {
        const isFirst = !firstMarked && h.items && h.items.length > 0;
        if (isFirst) firstMarked = true;
        return { ...h, _isFirst: isFirst };
    });

    wrap.innerHTML = annotated.map(_newsGroupHtml).join("");
    _newsShowEmpty(false);
    _newsShowFeed(true);
}

/** Render the AI briefing text from the themes response. */
function _newsRenderBriefing(themesData) {
    const body = document.getElementById("news-briefing-body");
    if (!body) return;
    body.textContent = themesData.briefing || "";
}

/** Render the AI theme clusters row. */
function _newsRenderThemes(themesData) {
    const row = document.getElementById("news-themes-row");
    if (!row) return;

    const themes = themesData.themes || [];
    if (!themes.length) {
        row.innerHTML = "";
        return;
    }

    row.innerHTML = themes.map(theme => {
        const chips = (theme.tickers || []).map(t =>
            `<span class="news-theme-chip">${escapeHtml(t)}</span>`
        ).join("");
        return `<div class="news-theme-card">
            <div class="news-theme-title">${escapeHtml(theme.title)}</div>
            <p class="news-theme-summary">${escapeHtml(theme.summary)}</p>
            ${chips ? `<div class="news-theme-chips">${chips}</div>` : ""}
        </div>`;
    }).join("");
}

/** Fetch themes from the API and render them; silently ignores 503 (Claude offline). */
async function _newsLoadThemes() {
    const briefingBody = document.getElementById("news-briefing-body");
    // Show skeleton while loading
    if (briefingBody && !briefingBody.textContent.trim()) {
        briefingBody.innerHTML = `<div class="news-skeleton news-skeleton--line news-skeleton--wide"></div>
            <div class="news-skeleton news-skeleton--line news-skeleton--medium"></div>`;
    }
    try {
        const res = await fetch("/api/news/themes");
        if (res.status === 503) {
            // Claude offline — AI section stays hidden via data-engine-claude-only
            if (briefingBody) briefingBody.innerHTML = "";
            return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _newsRenderBriefing(data);
        _newsRenderThemes(data);
    } catch (err) {
        console.warn("News themes fetch failed:", err);
        if (briefingBody) briefingBody.innerHTML = "";
        const row = document.getElementById("news-themes-row");
        if (row) row.innerHTML = "";
    }
}

/**
 * Load the news zone: fetch the feed, render groups, then (in Claude mode)
 * fetch and render AI themes.  Lazy — only runs once per session unless forced.
 */
async function loadNewsZone() {
    _newsShowLoading(true);
    _newsShowFeed(false);
    _newsShowEmpty(false);

    try {
        const res = await fetch("/api/news/feed");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        _newsFeedData = await res.json();
        _newsRenderFeed(_newsFeedData);
    } catch (err) {
        console.warn("News feed fetch failed:", err);
        _newsShowFeed(false);
        _newsShowEmpty(true);
    } finally {
        _newsShowLoading(false);
    }

    // AI layer — only in Claude mode; 503 / failures are silently swallowed.
    if (!isLocalIntelligenceMode()) {
        await _newsLoadThemes();
    }

    _newsLoaded = true;
    _newsLoadPromise = null;
}

/** Lazy entry-point: starts a load if not already done. */
function ensureNewsLoaded() {
    if (_newsLoaded) return;
    if (!_newsLoadPromise) _newsLoadPromise = loadNewsZone();
}
