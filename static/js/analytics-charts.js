/**
 * Analytics sub-tab charts — lazy-rendered, theme-aware visualizations.
 * Depends on globals from dashboard.js (chartTheme, uiScale, cssVar, etc.).
 */
const AnalyticsCharts = (() => {
    const ANALYTICS_PANES = ["performance", "risk", "exposure", "signals", "markets"];
    let activePane = "performance";
    const rendered = new Set(["performance"]);
    let contributionPeriod = "day";

    let riskRewardChart = null;
    let benchmarkChart = null;
    let rollingVolChart = null;
    let macroAlignmentChart = null;
    let benchmarkRange = "1y";
    let _correlationData = null;
    let _correlationState = { cells: [], hover: null };
    let _correlationHoverKey = null;
    let _correlationEventsBound = false;
    let _correlationScrollBound = false;
    let drawdownChart = null;
    let treemapChart = null;
    let _lastHhi = 0;
    let _lastConcentrationSectors = [];
    let _lastBeta = 1;
    let _gaugeReady = false;
    let _betaGaugeReady = false;
    let _benchmarkData = null;
    const INVESTOR_AVERAGE_HHI = 0.18;
    const INVESTOR_AVERAGE_BETA = 1.0;

    let _tapeRaf = null;
    let _tapePaused = false;
    let _tapeInView = true;
    let _cachedMarkets = [];

    let _moduleInsightsCache = { ai: null, local: null };
    let _moduleInsightsLoading = false;
    let _portfolioExposureCache = null;
    let _portfolioExposurePromise = null;

    // Sector tilt live-selection state
    let _sectorTiltFull = [];
    let _sectorHoldingContribs = {};
    let _sectorTiltSelectedTicker = null;

    async function fetchPortfolioExposure({ refresh = false } = {}) {
        if (!refresh && _portfolioExposureCache) return _portfolioExposureCache;
        if (!refresh && typeof cachedPortfolioExposure !== "undefined" && cachedPortfolioExposure) {
            _portfolioExposureCache = cachedPortfolioExposure;
            return cachedPortfolioExposure;
        }
        if (!refresh && _portfolioExposurePromise) return _portfolioExposurePromise;
        _portfolioExposurePromise = fetch("/api/ai/portfolio-exposure")
            .then((res) => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then((data) => {
                _portfolioExposureCache = data;
                return data;
            })
            .finally(() => {
                _portfolioExposurePromise = null;
            });
        return _portfolioExposurePromise;
    }
    const MODULE_LABELS = {
        performance: "Performance",
        risk: "Risk",
        exposure: "Exposure",
        signals: "Signals",
        markets: "Markets",
    };

    const $ = (id) => document.getElementById(id);

    function token(name, fallback) {
        const v = typeof cssVar === "function" ? cssVar(name) : "";
        return v || fallback;
    }

    function escapeText(value) {
        const s = String(value ?? "");
        if (typeof escapeHtml === "function") return escapeHtml(s);
        return s
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll("\"", "&quot;")
            .replaceAll("'", "&#039;");
    }

    function showLoading(id, on) {
        const el = $(id);
        if (el) {
            el.style.display = on ? "" : "none";
            el.setAttribute("aria-hidden", on ? "false" : "true");
        }
    }

    function showEmpty(id, on) {
        const el = $(id);
        if (el) el.style.display = on ? "" : "none";
    }

    function actionColor(action) {
        const a = (action || "hold").toLowerCase();
        if (a === "buy" || a === "add") return token("--accent-green", "#30d158");
        if (a === "trim" || a === "sell") return token("--accent-red", "#ff453a");
        return token("--accent-cyan", "#64d2ff");
    }

    function colorToRgb(color) {
        if (!color) return { r: 255, g: 69, b: 58 };
        const c = color.trim();
        if (c.startsWith("#")) {
            const h = c.slice(1);
            const full = h.length === 3 ? h.split("").map(x => x + x).join("") : h;
            return {
                r: parseInt(full.slice(0, 2), 16),
                g: parseInt(full.slice(2, 4), 16),
                b: parseInt(full.slice(4, 6), 16),
            };
        }
        const m = c.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
        if (m) return { r: +m[1], g: +m[2], b: +m[3] };
        return { r: 255, g: 69, b: 58 };
    }

    /** Pick readable label colors for a treemap tile background. */
    function contrastTextOn(bgColor) {
        const { r, g, b } = colorToRgb(bgColor);
        const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
        if (lum > 0.62) {
            return ["#1C1C1E", "rgba(28, 28, 30, 0.72)"];
        }
        return ["#ffffff", "rgba(255, 255, 255, 0.82)"];
    }

    /** Apple-style sector palette + Bootstrap icon per GICS-style sector. */
    const SECTOR_THEMES = [
        { match: /tech/i,                        color: "#2F6FB0", icon: "bi-cpu-fill" },
        { match: /health/i,                      color: "#B23A55", icon: "bi-heart-pulse-fill" },
        { match: /financ/i,                      color: "#4B49A0", icon: "bi-bank" },
        { match: /energy/i,                      color: "#C07628", icon: "bi-lightning-charge-fill" },
        { match: /industri/i,                    color: "#2A8C84", icon: "bi-gear-wide-connected" },
        { match: /consumer disc|discretionary/i, color: "#BD5232", icon: "bi-bag-fill" },
        { match: /consumer stap|staples/i,       color: "#3C8C58", icon: "bi-cart-fill" },
        { match: /real estate|reit/i,            color: "#8A6B4A", icon: "bi-building" },
        { match: /utilit/i,                      color: "#B58A1E", icon: "bi-plug-fill" },
        { match: /material/i,                    color: "#8A4FA8", icon: "bi-box-seam" },
        { match: /communi/i,                     color: "#3681A6", icon: "bi-broadcast" },
        { match: /aero|defense|defence/i,        color: "#1F8A72", icon: "bi-airplane-fill" },
    ];
    const SECTOR_THEME_DEFAULT = { color: "#5C5C66", icon: "bi-diagram-3" };

    function sectorTheme(name) {
        const n = (name || "").toLowerCase();
        return SECTOR_THEMES.find(t => t.match.test(n)) || SECTOR_THEME_DEFAULT;
    }

    function sectorTileFill(name) {
        const { color } = sectorTheme(name);
        const { r, g, b } = colorToRgb(color);
        const isLight = typeof currentTheme === "function" && currentTheme() === "light";
        const alpha = isLight ? 0.78 : 0.86;
        return `rgba(${r},${g},${b},${alpha})`;
    }

    function treemapTileBg(ctx) {
        if (ctx.type !== "data") return "transparent";
        const name = ctx.raw?.g ?? ctx.raw?._data?.sector ?? "";
        return sectorTileFill(name);
    }

    function clearTreemapOverlay() {
        $("treemap-label-overlay")?.replaceChildren();
    }

    function renderTreemapLabelOverlay(chart) {
        const overlay = $("treemap-label-overlay");
        const meta = chart?.getDatasetMeta?.(0);
        if (!overlay || !meta?.data?.length) {
            clearTreemapOverlay();
            return;
        }

        const scale = uiScale();
        const frag = document.createDocumentFragment();

        meta.data.forEach((el, i) => {
            const raw = chart.data.datasets[0]?.data?.[i];
            if (!raw || raw.v == null) return;

            const { x, y, width, height } = el.getProps(["x", "y", "width", "height"], true);
            if (width < 42 || height < 36) return;

            const name = raw.g ?? raw._data?.sector ?? "Sector";
            const theme = sectorTheme(name);
            const fill = sectorTileFill(name);
            const textTone = contrastTextOn(fill)[0] === "#ffffff" ? "light" : "dark";
            const pct = raw.v;
            const pctLabel = Number.isInteger(pct) ? `${pct}%` : `${Number(pct).toFixed(1)}%`;
            const showIcon = width >= 54 && height >= 52;
            const showName = width >= 48 && height >= 44;
            const esc = typeof escapeHtml === "function" ? escapeHtml : s => s;

            const tile = document.createElement("div");
            tile.className = "treemap-tile-label";
            tile.dataset.tone = textTone;
            tile.style.left = `${x}px`;
            tile.style.top = `${y}px`;
            tile.style.width = `${width}px`;
            tile.style.height = `${height}px`;

            tile.innerHTML = `<div class="treemap-tile-label__inner">
                ${showIcon ? `<span class="treemap-tile-label__icon" style="--sector-accent:${theme.color}"><i class="bi ${theme.icon}" aria-hidden="true"></i></span>` : ""}
                ${showName ? `<span class="treemap-tile-label__name">${esc(name)}</span>` : ""}
                <span class="treemap-tile-label__pct">${pctLabel}</span>
            </div>`;
            tile.style.setProperty("--label-scale", String(scale));
            frag.appendChild(tile);
        });

        overlay.replaceChildren(frag);
    }

    let _treemapLabelPluginReady = false;
    function ensureTreemapLabelPlugin() {
        if (_treemapLabelPluginReady || typeof Chart === "undefined") return;
        Chart.register({
            id: "foliSenseTreemapLabels",
            afterUpdate(chart) {
                if (chart !== treemapChart) return;
                renderTreemapLabelOverlay(chart);
            },
        });
        _treemapLabelPluginReady = true;
    }

    /** Canvas-safe correlation cell fill (CSS color-mix/vars do not work on canvas). */
    function corrCellRgba(value, isDiagonal = false) {
        const isLight = typeof currentTheme === "function" && currentTheme() === "light";
        if (isDiagonal) {
            return isLight ? "rgba(0,0,0,0.045)" : "rgba(255,255,255,0.055)";
        }
        const t = Math.max(-1, Math.min(1, value));
        if (Math.abs(t) < 0.12) {
            const neutral = colorToRgb(token("--text-tertiary", "#8e8e93"));
            return `rgba(${neutral.r},${neutral.g},${neutral.b},${isLight ? 0.18 : 0.22})`;
        }
        const alpha = 0.18 + Math.abs(t) * 0.52;
        const base = t >= 0
            ? token("--accent-red", "#ff453a")
            : token("--accent-blue", "#0a84ff");
        const { r, g, b } = colorToRgb(base);
        return `rgba(${r},${g},${b},${alpha.toFixed(3)})`;
    }

    function registerPlugins() {
        if (typeof Chart === "undefined") return;
        const matrix = window.ChartMatrix || window["chartjs-chart-matrix"];
        if (matrix?.MatrixController) {
            Chart.register(matrix.MatrixController, matrix.MatrixElement);
        }
        const treemap = window.ChartTreemap || window["chartjs-chart-treemap"];
        if (treemap?.TreemapController) {
            Chart.register(treemap.TreemapController, treemap.TreemapElement);
        }
    }

    function analyticsSignalsUrl() {
        const local = typeof isLocalIntelligenceMode === "function" && isLocalIntelligenceMode();
        return `/api/ai/investment-signals/all${local ? "?force_local=true" : ""}`;
    }

    function widgetInsightMode() {
        const claudeOffline = typeof _isClaudeApiLive !== "undefined"
            && (_isClaudeApiLive === false || _forcedLocalMode);
        const local = typeof isLocalIntelligenceMode === "function" && isLocalIntelligenceMode();
        return claudeOffline || local ? "local" : "ai";
    }

    function aiWidgetInsightsMap() {
        const payload = _moduleInsightsCache.ai;
        if (!payload || payload.source !== "claude") return {};
        return payload.widget_insights || {};
    }

    function renderWidgetInsight(el, value, useAi) {
        const esc = typeof escapeHtml === "function" ? escapeHtml : s => s;
        const iconClass = useAi ? "bi-stars" : "bi-cpu-fill";
        const modeLabel = useAi ? "AI Tip" : "Local Intel";
        const eyebrow =
            `<span class="wi-eyebrow"><i class="bi ${iconClass}"></i>${modeLabel}</span>`;

        if (typeof value === "object" && value !== null && value.insight) {
            el.innerHTML =
                eyebrow +
                `<strong class="wi-headline">${esc(value.headline || "")}</strong>` +
                `<span class="wi-text">${esc(value.insight)}</span>`;
            return;
        }

        if (useAi) {
            el.innerHTML = eyebrow + `<span class="wi-text">${esc(String(value))}</span>`;
            return;
        }

        el.textContent = String(value);
    }

    function applyWidgetInsights() {
        const mode = widgetInsightMode();
        const localWidgets = _moduleInsightsCache.local?.widget_insights || {};
        const aiWidgets = mode === "ai" ? aiWidgetInsightsMap() : {};
        if (!Object.keys(localWidgets).length && !Object.keys(aiWidgets).length) return;

        const useAi = mode === "ai";

        document.querySelectorAll("[data-widget-insight]").forEach(el => {
            const key = el.dataset.widgetInsight;
            if (!key) return;

            const value = useAi ? (aiWidgets[key] ?? "") : (localWidgets[key] ?? "");

            if (!value && value !== 0) {
                el.textContent = "";
                el.hidden = true;
                return;
            }

            el.hidden = false;
            el.dataset.insightMode = useAi ? "ai" : "local";
            renderWidgetInsight(el, value, useAi);
        });
    }

    async function loadWidgetInsights(forceRefresh = false) {
        if (_moduleInsightsCache.local && !forceRefresh) {
            applyWidgetInsights();
            if (widgetInsightMode() === "ai") {
                void loadAiWidgetInsights(false);
            }
            return;
        }
        if (_moduleInsightsLoading && !forceRefresh) return;

        _moduleInsightsLoading = true;
        try {
            const res = await fetch("/api/ai/analytics-insights?mode=local");
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            _moduleInsightsCache.local = await res.json();
            applyWidgetInsights();
            if (widgetInsightMode() === "ai") {
                void loadAiWidgetInsights(false);
            }
        } catch (err) {
            console.warn("Analytics widget insights fetch failed:", err);
        } finally {
            _moduleInsightsLoading = false;
        }
    }

    async function loadAiWidgetInsights(forceRefresh = false) {
        if (typeof isLocalIntelligenceMode === "function" && isLocalIntelligenceMode()) return;
        if (_moduleInsightsCache.ai && !forceRefresh) {
            applyWidgetInsights();
            return;
        }
        applyWidgetInsights();
        try {
            const params = new URLSearchParams({ mode: "ai" });
            if (forceRefresh) params.set("force_refresh", "true");
            const res = await fetch(`/api/ai/analytics-insights?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const payload = await res.json();
            if (payload?.source === "claude") {
                _moduleInsightsCache.ai = payload;
            } else {
                _moduleInsightsCache.ai = null;
            }
            applyWidgetInsights();
        } catch (err) {
            console.warn("Claude analytics tips fetch failed:", err);
            _moduleInsightsCache.ai = null;
            applyWidgetInsights();
        }
    }

    function syncSubPaneIndicator() {
        const track = $("analytics-zone-tabs");
        if (!track) return;
        track.dataset.activePane = activePane;
        track.querySelectorAll(".analytics-zone-tab").forEach(btn => {
            const on = btn.dataset.analyticsPane === activePane;
            btn.classList.toggle("is-active", on);
            btn.setAttribute("aria-selected", String(on));
        });
        document.querySelectorAll(".analytics-sub-pane").forEach(pane => {
            const on = pane.dataset.analyticsPane === activePane;
            pane.classList.toggle("is-active", on);
            pane.hidden = !on;
        });
    }

    function setSubPane(pane) {
        if (!ANALYTICS_PANES.includes(pane)) pane = "performance";
        if (pane === activePane) return;
        activePane = pane;
        syncSubPaneIndicator();
        if (!rendered.has(pane)) {
            rendered.add(pane);
            loadPane(pane);
        } else if (pane === "markets") {
            refreshMarketsTape(_cachedMarkets);
        } else if (pane === "performance") {
            loadPerformancePane();
        }
        requestAnimationFrame(resizeCharts);
    }

    function initSubTabs() {
        const track = $("analytics-zone-tabs");
        if (!track) return;
        track.querySelectorAll("[data-analytics-pane]").forEach(btn => {
            btn.addEventListener("click", () => setSubPane(btn.dataset.analyticsPane));
        });
        syncSubPaneIndicator();

        const periodGroup = $("contribution-period-tabs");
        periodGroup?.querySelectorAll("[data-period]").forEach(btn => {
            btn.addEventListener("click", () => {
                contributionPeriod = btn.dataset.period || "day";
                periodGroup.dataset.activePeriod = contributionPeriod;
                periodGroup.querySelectorAll(".contribution-period-btn").forEach(b => {
                    const on = b.dataset.period === contributionPeriod;
                    b.classList.toggle("is-active", on);
                    b.setAttribute("aria-pressed", String(on));
                });
                loadContributionChart();
            });
        });

        const benchGroup = $("benchmark-range-tabs");
        benchGroup?.querySelectorAll("[data-range]").forEach(btn => {
            btn.addEventListener("click", () => {
                benchmarkRange = btn.dataset.range || "1y";
                benchGroup.dataset.activeRange = benchmarkRange;
                benchGroup.querySelectorAll(".benchmark-range-btn").forEach(b => {
                    const on = b.dataset.range === benchmarkRange;
                    b.classList.toggle("is-active", on);
                    b.setAttribute("aria-pressed", String(on));
                });
                if (_benchmarkData) renderBenchmarkChart(_benchmarkData);
            });
        });
    }

    function loadPane(pane) {
        switch (pane) {
            case "performance": return loadPerformancePane();
            case "risk": return loadRiskPane();
            case "exposure": return loadExposurePane();
            case "signals": return loadSignalsPane();
            case "markets": return loadMarketsPane();
            default: break;
        }
    }

    async function loadPerformancePane() {
        await loadBenchmarkChart();
    }

    async function loadRiskPane() {
        await Promise.all([
            loadRiskRewardChart(),
            loadCorrelationChart(),
            loadConcentrationGauge(),
            loadDrawdownChart(),
            loadBetaGauge(),
            loadRollingVolChart(),
        ]);
    }

    async function loadExposurePane() {
        await Promise.all([
            loadSectorTreemap(),
            loadGeoExposure(),
            loadSectorTilt(),
        ]);
    }

    async function loadSignalsPane() {
        await loadContributionChart();
        await Promise.all([
            loadSignalsBundle(),
            loadConvictionGaps(),
            loadConfidenceSpectrum(),
        ]);
    }

    function normSignalBucket(action) {
        const a = (action || "hold").toLowerCase();
        if (a === "buy" || a === "add") return "add";
        if (a === "trim" || a === "sell") return "trim";
        if (a === "hold" || a === "wait") return "hold";
        return "unknown";
    }

    function verdictBucketLabel(bucket) {
        return { add: "Add / buy", hold: "Hold", trim: "Trim / sell", unknown: "Unclear" }[bucket] || bucket;
    }

    function concentrationPlain(band) {
        return { low: "Well spread", medium: "Moderate", high: "Concentrated" }[band] || band;
    }

    async function loadSignalsBundle() {
        showLoading("signal-board-loading", true);
        showLoading("portfolio-outlook-loading", true);
        showEmpty("signal-board-empty", false);
        showEmpty("portfolio-outlook-empty", false);

        try {
            const res = await fetch(analyticsSignalsUrl());
            if (!res.ok) throw new Error("signals unavailable");
            const data = await res.json();
            renderSignalBoard(data);
            renderPortfolioOutlook(data);
        } catch (err) {
            console.warn("Signals bundle failed:", err);
            showEmpty("signal-board-empty", true);
            showEmpty("portfolio-outlook-empty", true);
        } finally {
            showLoading("signal-board-loading", false);
            showLoading("portfolio-outlook-loading", false);
        }
    }

    async function loadMarketsPane() {
        await Promise.all([
            refreshMarketsFromApi(),
            loadMacroAlignment(),
        ]);
    }

    async function loadRiskRewardChart() {
        showLoading("risk-reward-loading", true);
        showEmpty("risk-reward-empty", false);
        try {
            const [riskRes, sigRes] = await Promise.all([
                fetch("/api/portfolio/risk-metrics"),
                fetch(analyticsSignalsUrl()),
            ]);
            const data = await riskRes.json();
            const sigData = sigRes.ok ? await sigRes.json() : {};
            const signals = sigData.signals || {};

            if (!data.has_data) {
                showEmpty("risk-reward-empty", true);
                riskRewardChart?.destroy();
                riskRewardChart = null;
                return;
            }

            data.holdings.forEach(h => {
                if (!h.action && signals[h.ticker]) h.action = signals[h.ticker].action;
            });

            const theme = chartTheme();
            const scale = uiScale();
            const ctx = $("risk-reward-chart")?.getContext("2d");
            if (!ctx) return;

            const holdings = data.holdings.map(h => ({
                x: h.annual_vol_pct,
                y: h.annual_return_pct,
                r: Math.max(6, Math.min(28, h.allocation_pct * 0.55)),
                ticker: h.ticker,
                action: h.action,
            }));

            const refs = [];
            if (data.portfolio) {
                refs.push({
                    x: data.portfolio.annual_vol_pct,
                    y: data.portfolio.annual_return_pct,
                    r: 12,
                    label: data.portfolio.label,
                    kind: "portfolio",
                });
            }
            if (data.benchmark) {
                refs.push({
                    x: data.benchmark.annual_vol_pct,
                    y: data.benchmark.annual_return_pct,
                    r: 10,
                    label: data.benchmark.label,
                    kind: "benchmark",
                });
            }

            riskRewardChart?.destroy();
            riskRewardChart = new Chart(ctx, {
                type: "bubble",
                data: {
                    datasets: [
                        {
                            label: "Holdings",
                            data: holdings,
                            backgroundColor: holdings.map(h =>
                                actionColor(h.action) + "99"),
                            borderColor: holdings.map(h => actionColor(h.action)),
                            borderWidth: 1.5,
                        },
                        {
                            label: "Reference",
                            data: refs,
                            backgroundColor: refs.map(r =>
                                r.kind === "portfolio"
                                    ? token("--accent-yellow", "#ffd60a") + "cc"
                                    : token("--accent-blue", "#0a84ff") + "cc"),
                            borderColor: refs.map(r =>
                                r.kind === "portfolio"
                                    ? token("--accent-yellow", "#ffd60a")
                                    : token("--accent-blue", "#0a84ff")),
                            borderWidth: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            ...tooltipOptions(),
                            callbacks: {
                                label(ctx) {
                                    const d = ctx.raw;
                                    if (d.ticker) {
                                        return `${d.ticker}: ${d.y.toFixed(1)}% return, ${d.x.toFixed(1)}% vol`;
                                    }
                                    return `${d.label}: ${d.y.toFixed(1)}% return, ${d.x.toFixed(1)}% vol`;
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            title: { display: true, text: "Volatility (annual %)", color: theme.tick, font: { size: 10 * scale } },
                            ticks: { color: theme.tick, font: { size: 10 * scale } },
                            grid: { color: theme.grid },
                        },
                        y: {
                            title: { display: true, text: "Return (annual %)", color: theme.tick, font: { size: 10 * scale } },
                            ticks: { color: theme.tick, font: { size: 10 * scale } },
                            grid: { color: theme.grid },
                        },
                    },
                },
            });
        } catch (err) {
            console.warn("Risk/reward chart failed:", err);
            showEmpty("risk-reward-empty", true);
        } finally {
            showLoading("risk-reward-loading", false);
        }
    }

    function corrPlainLabel(value) {
        const v = Number(value) || 0;
        if (v > 0.6) return "move together often";
        if (v < -0.2) return "tend to move apart";
        return "weakly related";
    }

    function roundRectPath(ctx, x, y, w, h, r) {
        const radius = Math.min(r, w / 2, h / 2);
        ctx.beginPath();
        if (typeof ctx.roundRect === "function") {
            ctx.roundRect(x, y, w, h, radius);
            return;
        }
        ctx.moveTo(x + radius, y);
        ctx.arcTo(x + w, y, x + w, y + h, radius);
        ctx.arcTo(x + w, y + h, x, y + h, radius);
        ctx.arcTo(x, y + h, x, y, radius);
        ctx.arcTo(x, y, x + w, y, radius);
        ctx.closePath();
    }

    function correlationLabelWidth(tickers, scale) {
        const probe = document.createElement("canvas").getContext("2d");
        const fontSize = Math.max(10, Math.round(11 * scale));
        probe.font = `500 ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
        const maxText = Math.max(...tickers.map((t) => probe.measureText(t).width), 28);
        return Math.ceil(maxText) + 14;
    }

    function correlationXLabelPad(cellSize) {
        return cellSize >= 28 ? 0 : Math.max(4, Math.round(cellSize * 0.25));
    }

    function correlationXLabelHeight(tickers, scale, cellSize) {
        const probe = document.createElement("canvas").getContext("2d");
        const fontSize = Math.max(9, Math.round(10 * scale));
        probe.font = `500 ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
        const maxTextW = Math.max(...tickers.map((t) => probe.measureText(t).width), 20);

        if (cellSize >= 28) {
            return Math.ceil(fontSize + 8);
        }

        // Visual height of text rotated -45° = (textWidth + lineHeight) / √2, plus a small buffer.
        return Math.ceil((maxTextW + fontSize) / Math.SQRT2 + 10);
    }

    function computeCorrelationLayout(frameWrap, tickers, scale) {
        const n = tickers.length;
        const gap = Math.max(3, Math.round(4 * scale));
        const labelGap = Math.max(10, Math.round(12 * scale));
        const frameGap = Math.max(8, Math.round(10 * scale));
        const yLabelWidth = correlationLabelWidth(tickers, scale);
        const maxPlotSize = Math.round(205 * scale);
        const maxViewportHeight = Math.round(268 * scale);

        const containerW = frameWrap?.clientWidth || 320;
        const scrollViewportW = Math.max(120, containerW - yLabelWidth - frameGap);

        const widthCell = (scrollViewportW - gap * (n - 1)) / n;
        const heightCell = (maxPlotSize - gap * (n - 1)) / n;
        const cellSize = Math.max(14, Math.min(widthCell, heightCell));

        const gridWidth = n * cellSize + gap * (n - 1);
        const xLabelHeight = correlationXLabelHeight(tickers, scale, cellSize);
        const xLabelPad = correlationXLabelPad(cellSize);
        const contentHeight = gridWidth + labelGap + xLabelHeight;
        const innerWidth = yLabelWidth + frameGap + gridWidth + xLabelPad * 2;

        const needsHorizontalScroll = innerWidth > containerW + 1;
        const needsVerticalScroll = contentHeight > maxViewportHeight + 1;

        return {
            n,
            gap,
            labelGap,
            frameGap,
            yLabelWidth,
            cellSize,
            gridWidth,
            innerWidth,
            scrollInnerWidth: Math.max(containerW, innerWidth),
            contentHeight,
            viewportHeight: Math.min(maxViewportHeight, contentHeight),
            xLabelHeight,
            xLabelPad,
            xLabelsHorizontal: cellSize >= 28,
            needsHorizontalScroll,
            needsVerticalScroll,
            needsScroll: needsHorizontalScroll || needsVerticalScroll,
        };
    }

    function syncCorrelationLabels(tickers, layout) {
        const yEl = $("correlation-y-labels");
        const xEl = $("correlation-x-labels");
        const frame = $("correlation-chart-frame");
        const inner = $("correlation-scroll-inner");
        const scroll = $("correlation-scroll");
        if (!yEl || !xEl || !frame) return;

        const {
            cellSize,
            gap,
            yLabelWidth,
            gridWidth,
            labelGap,
            xLabelHeight,
            xLabelsHorizontal,
            frameGap,
            scrollInnerWidth,
            contentHeight,
            viewportHeight,
            xLabelPad,
            needsScroll,
            needsHorizontalScroll,
            needsVerticalScroll,
        } = layout;

        yEl.innerHTML = tickers.map((t) =>
            `<span class="correlation-axis-label" title="${t}">${t}</span>`
        ).join("");

        if (xLabelsHorizontal) {
            xEl.classList.add("correlation-x-labels--horizontal");
            xEl.innerHTML = tickers.map((t, index) => {
                const left = index * (cellSize + gap);
                return `<span class="correlation-axis-label correlation-axis-label--x" style="left:${left}px;width:${cellSize}px" title="${t}">${t}</span>`;
            }).join("");
        } else {
            xEl.classList.remove("correlation-x-labels--horizontal");
            xEl.innerHTML = tickers.map((t, index) => {
                const left = index * (cellSize + gap) + cellSize / 2;
                return `<span class="correlation-axis-label correlation-axis-label--x" style="left:${left}px" title="${t}">${t}</span>`;
            }).join("");
        }

        yEl.hidden = false;
        xEl.hidden = false;
        yEl.setAttribute("aria-hidden", "false");
        xEl.setAttribute("aria-hidden", "false");

        frame.style.setProperty("--corr-gap", `${gap}px`);
        frame.style.setProperty("--corr-cell", `${cellSize}px`);
        frame.style.setProperty("--corr-y-label-width", `${yLabelWidth}px`);
        frame.style.setProperty("--corr-label-gap", `${labelGap}px`);
        frame.style.setProperty("--corr-x-label-height", `${xLabelHeight}px`);
        frame.style.setProperty("--corr-grid-width", `${gridWidth}px`);
        frame.style.setProperty("--corr-frame-gap", `${frameGap}px`);
        frame.style.setProperty("--corr-x-label-pad", `${xLabelPad}px`);

        if (inner) {
            inner.style.width = `${scrollInnerWidth}px`;
            inner.style.minHeight = needsVerticalScroll ? `${contentHeight}px` : "";
            inner.style.setProperty("--corr-inner-width", `${scrollInnerWidth}px`);
            inner.style.setProperty("--corr-grid-width", `${gridWidth}px`);
            inner.style.setProperty("--corr-label-gap", `${labelGap}px`);
            inner.style.setProperty("--corr-x-label-height", `${xLabelHeight}px`);
        }

        xEl.style.width = `${gridWidth}px`;
        xEl.style.height = `${xLabelHeight}px`;
        yEl.style.height = `${gridWidth}px`;

        if (scroll) {
            scroll.classList.toggle("correlation-scroll--overflow", needsScroll);
            scroll.classList.toggle("correlation-scroll--overflow-x", needsHorizontalScroll);
            scroll.classList.toggle("correlation-scroll--overflow-y", needsVerticalScroll);
            if (needsVerticalScroll) {
                scroll.style.maxHeight = `${viewportHeight}px`;
                frame.style.setProperty("--corr-viewport-height", `${viewportHeight}px`);
            } else {
                scroll.style.maxHeight = "";
                frame.style.removeProperty("--corr-viewport-height");
            }
        }

        const frameWrap = frame.closest(".correlation-chart-frame-wrap");
        if (frameWrap) {
            frameWrap.style.setProperty("--corr-y-label-width", `${yLabelWidth}px`);
        }
    }

    function clearCorrelationLabels() {
        const yEl = $("correlation-y-labels");
        const xEl = $("correlation-x-labels");
        if (yEl) {
            yEl.innerHTML = "";
            yEl.hidden = true;
        }
        if (xEl) {
            xEl.innerHTML = "";
            xEl.hidden = true;
        }
    }

    function showCorrelationScale(on) {
        const scale = $("correlation-scale");
        if (scale) scale.hidden = !on;
    }

    function ensureCorrelationEvents() {
        if (_correlationEventsBound) return;
        const canvas = $("correlation-chart");
        if (!canvas) return;
        _correlationEventsBound = true;
        // Re-parent the fixed-position tooltip to <body>. Analytics cards keep a
        // residual transform from the `cardIn` animation (fill-mode: both), and a
        // transformed ancestor becomes the containing block for position:fixed —
        // which would place the tooltip relative to the card instead of the
        // viewport and push it off-screen. Anchoring it to <body> avoids that.
        const tip = $("correlation-cell-tip");
        if (tip && tip.parentElement !== document.body) {
            document.body.appendChild(tip);
        }
        canvas.addEventListener("mousemove", onCorrelationHover);
        canvas.addEventListener("mouseleave", onCorrelationLeave);
        bindCorrelationScroll();
    }

    function bindCorrelationScroll() {
        if (_correlationScrollBound) return;
        const scroll = $("correlation-scroll");
        if (!scroll) return;
        _correlationScrollBound = true;

        let drag = null;

        scroll.addEventListener("pointerdown", (event) => {
            if (!scroll.classList.contains("correlation-scroll--overflow")) return;
            if (event.button !== 0) return;
            drag = {
                id: event.pointerId,
                x: event.clientX,
                y: event.clientY,
                sl: scroll.scrollLeft,
                st: scroll.scrollTop,
            };
            scroll.classList.add("correlation-scroll--dragging");
            scroll.setPointerCapture(event.pointerId);
        });

        scroll.addEventListener("pointermove", (event) => {
            if (!drag || drag.id !== event.pointerId) return;
            scroll.scrollLeft = drag.sl - (event.clientX - drag.x);
            scroll.scrollTop = drag.st - (event.clientY - drag.y);
        });

        const endDrag = (event) => {
            if (!drag || drag.id !== event.pointerId) return;
            drag = null;
            scroll.classList.remove("correlation-scroll--dragging");
            try {
                scroll.releasePointerCapture(event.pointerId);
            } catch (_) {
                /* pointer already released */
            }
        };

        scroll.addEventListener("pointerup", endDrag);
        scroll.addEventListener("pointercancel", endDrag);
    }

    function positionCorrelationTip(tip, clientX, clientY) {
        if (!tip) return;

        const pad = 8;
        const gap = 10;
        tip.hidden = false;

        const tipW = tip.offsetWidth;
        const tipH = tip.offsetHeight;
        const halfW = tipW / 2;

        // Clamp within viewport
        const left = Math.max(pad + halfW, Math.min(clientX, window.innerWidth - pad - halfW));

        if (clientY - tipH - gap < pad) {
            tip.style.transform = `translate(-50%, ${gap}px)`;
        } else {
            tip.style.transform = `translate(-50%, calc(-100% - ${gap}px))`;
        }

        tip.style.left = `${left}px`;
        tip.style.top = `${clientY}px`;
    }

    function onCorrelationLeave() {
        _correlationHoverKey = null;
        _correlationState.hover = null;
        const canvas = $("correlation-chart");
        const tip = $("correlation-cell-tip");
        if (canvas) canvas.style.cursor = "";
        if (tip) tip.hidden = true;
        if (_correlationData) drawCorrelationHeatmap();
    }

    function onCorrelationHover(event) {
        const canvas = $("correlation-chart");
        const tip = $("correlation-cell-tip");
        if (!canvas || !_correlationData?.tickers?.length) return;

        const rect = canvas.getBoundingClientRect();
        const mx = event.clientX - rect.left;
        const my = event.clientY - rect.top;
        const hit = _correlationState.cells.find(
            (c) => mx >= c.x && mx <= c.x + c.w && my >= c.y && my <= c.y + c.h
        );
        const key = hit ? `${hit.row}-${hit.col}` : null;

        if (key !== _correlationHoverKey) {
            _correlationHoverKey = key;
            _correlationState.hover = hit || null;
            drawCorrelationHeatmap();
        }

        if (!hit || !tip) {
            canvas.style.cursor = "";
            if (tip) tip.hidden = true;
            return;
        }

        const rowTicker = _correlationData.tickers[hit.row];
        const colTicker = _correlationData.tickers[hit.col];
        tip.textContent = `${rowTicker} × ${colTicker}: ${(hit.v * 100).toFixed(0)}% — ${corrPlainLabel(hit.v)}`;
        positionCorrelationTip(tip, event.clientX, event.clientY);
        canvas.style.cursor = "pointer";
    }

    function drawCorrelationHeatmap() {
        const canvas = $("correlation-chart");
        const plot = $("correlation-plot");
        const frameWrap = plot?.closest(".correlation-chart-frame-wrap");
        if (!canvas || !plot || !_correlationData) return;

        const { tickers, matrix } = _correlationData;
        const n = tickers.length;
        if (n < 2) return;

        const scale = uiScale();
        const layout = computeCorrelationLayout(frameWrap, tickers, scale);
        const { cellSize, gap, gridWidth } = layout;
        const radius = Math.min(6, cellSize * 0.18);
        const dpr = window.devicePixelRatio || 1;

        plot.style.width = `${gridWidth}px`;
        plot.style.height = `${gridWidth}px`;

        canvas.width = Math.round(gridWidth * dpr);
        canvas.height = Math.round(gridWidth * dpr);
        canvas.style.width = `${gridWidth}px`;
        canvas.style.height = `${gridWidth}px`;

        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, gridWidth, gridWidth);

        _correlationState.cells = [];

        for (let i = 0; i < n; i++) {
            for (let j = 0; j < n; j++) {
                const v = matrix[i]?.[j] ?? 0;
                const x = j * (cellSize + gap);
                const y = i * (cellSize + gap);
                const isDiagonal = i === j;
                const isHover = _correlationState.hover
                    && _correlationState.hover.row === i
                    && _correlationState.hover.col === j;

                ctx.fillStyle = corrCellRgba(v, isDiagonal);
                roundRectPath(ctx, x, y, cellSize, cellSize, radius);
                ctx.fill();

                if (isHover) {
                    ctx.strokeStyle = token("--text-secondary", "rgba(235,235,245,0.72)");
                    ctx.lineWidth = 1.25;
                    roundRectPath(ctx, x - 0.5, y - 0.5, cellSize + 1, cellSize + 1, radius + 0.5);
                    ctx.stroke();
                }

                _correlationState.cells.push({ x, y, w: cellSize, h: cellSize, row: i, col: j, v });
            }
        }

        syncCorrelationLabels(tickers, layout);
    }

    async function loadCorrelationChart() {
        showLoading("correlation-loading", true);
        showEmpty("correlation-empty", false);
        showCorrelationScale(false);
        try {
            const res = await fetch("/api/portfolio/correlation");
            const data = await res.json();
            const tickers = data.tickers || [];

            if (tickers.length < 2) {
                showEmpty("correlation-empty", true);
                _correlationData = null;
                clearCorrelationLabels();
                return;
            }

            _correlationData = { tickers, matrix: data.matrix || [] };
            _correlationHoverKey = null;
            _correlationState = { cells: [], hover: null };
            ensureCorrelationEvents();
            drawCorrelationHeatmap();
            showCorrelationScale(true);
        } catch (err) {
            console.warn("Correlation chart failed:", err);
            showEmpty("correlation-empty", true);
            _correlationData = null;
            clearCorrelationLabels();
        } finally {
            showLoading("correlation-loading", false);
        }
    }

    function clampPct(value) {
        return Math.max(0, Math.min(100, Number(value) || 0));
    }

    function scalePct(value, min, max) {
        const span = max - min || 1;
        return clampPct(((Number(value) - min) / span) * 100);
    }

    function renderRiskLens(id, config) {
        const el = $(id);
        if (!el) return;

        const you = clampPct(config.youPct);
        const avg = clampPct(config.avgPct);
        el.dataset.tone = config.tone || "neutral";
        el.innerHTML = `
            <div class="risk-lens-head">
                <div class="risk-lens-metric">
                    <span class="risk-lens-eyebrow">${escapeText(config.eyebrow || "Your position")}</span>
                    <strong>${escapeText(config.metric)}</strong>
                    <span>${escapeText(config.state)}</span>
                </div>
                <div class="risk-lens-badge">${escapeText(config.badge)}</div>
            </div>
            <div class="risk-lens-rail" style="--you-pos:${you.toFixed(1)}%;--avg-pos:${avg.toFixed(1)}%">
                <div class="risk-lens-track" aria-hidden="true">
                    <i class="risk-lens-marker risk-lens-marker--you"></i>
                    <i class="risk-lens-marker risk-lens-marker--avg"></i>
                </div>
                <div class="risk-lens-axis">
                    <span>${escapeText(config.axisStart)}</span>
                    <span>${escapeText(config.axisMid)}</span>
                    <span>${escapeText(config.axisEnd)}</span>
                </div>
            </div>
            <div class="risk-lens-compare">
                <span class="risk-lens-chip risk-lens-chip--you">
                    <i></i><span>You</span><strong>${escapeText(config.metric)}</strong>
                </span>
                <span class="risk-lens-chip risk-lens-chip--avg">
                    <i></i><span>Investor avg</span><strong>${escapeText(config.avgMetric)}</strong>
                </span>
            </div>
            <div class="risk-lens-context">
                ${(config.context || []).map(item => `
                    <span class="risk-lens-context-item">
                        <small>${escapeText(item.label)}</small>
                        <strong>${escapeText(item.value)}</strong>
                    </span>
                `).join("")}
            </div>
            <div class="risk-lens-takeaway">
                <i class="bi ${escapeText(config.icon || "bi-lightning-charge-fill")}" aria-hidden="true"></i>
                <span>${escapeText(config.takeaway)}</span>
            </div>
        `;
    }

    function clearRiskLens(id) {
        $(id)?.replaceChildren();
    }

    function hhiLabel(hhi) {
        return `HHI ${(Math.max(0, Number(hhi) || 0) * 100).toFixed(0)}`;
    }

    function concentrationLevel(hhi) {
        const val = Number(hhi) || 0;
        if (val < 0.25) return "Well spread";
        if (val < 0.5) return "Moderate";
        if (val < 0.75) return "Concentrated";
        return "Very concentrated";
    }

    function concentrationComparison(hhi) {
        const diff = ((Number(hhi) || 0) - INVESTOR_AVERAGE_HHI) * 100;
        if (Math.abs(diff) < 2) {
            return { value: "Near average", sub: "Your spread is close to the investor baseline." };
        }
        const lower = diff < 0;
        return {
            value: `${Math.abs(diff).toFixed(0)} pts ${lower ? "lower" : "higher"}`,
            sub: lower ? "More diversified than the investor baseline." : "More concentrated than the investor baseline.",
        };
    }

    async function loadConcentrationGauge() {
        showLoading("concentration-loading", true);
        showEmpty("concentration-empty", false);
        try {
            const data = await fetchPortfolioExposure();
            const hhi = data.concentration_hhi ?? 0;
            const sectors = data.sector_exposure || [];

            if (!sectors.length) {
                showEmpty("concentration-empty", true);
                clearRiskLens("concentration-lens");
                return;
            }

            _lastConcentrationSectors = sectors;
            drawConcentrationGauge(hhi, sectors);
            _lastHhi = hhi;
            _gaugeReady = true;
        } catch (err) {
            console.warn("Concentration gauge failed:", err);
            showEmpty("concentration-empty", true);
            clearRiskLens("concentration-lens");
        } finally {
            showLoading("concentration-loading", false);
        }
    }

    function drawConcentrationGauge(hhi, sectors = _lastConcentrationSectors) {
        const val = Math.max(0, Math.min(1, Number(hhi) || 0));
        const list = sectors || [];
        const biggest = list[0] ? `${list[0].name} ${list[0].weight_pct}%` : "Balanced";
        // Effective number of independent bets implied by the HHI (1 / HHI),
        // capped by the number of sectors actually held. This is the plain-English
        // read of the index: "your money behaves like ~N equal sectors".
        const effBets = val > 0
            ? Math.max(1, Math.min(list.length || 1, Math.round(1 / val)))
            : (list.length || 1);
        const comparison = concentrationComparison(val);

        renderRiskLens("concentration-lens", {
            tone: val < 0.25 ? "calm" : val < 0.5 ? "watch" : "hot",
            metric: hhiLabel(val),
            state: concentrationLevel(val),
            badge: comparison.value,
            avgMetric: hhiLabel(INVESTOR_AVERAGE_HHI),
            youPct: scalePct(val, 0, 0.6),
            avgPct: scalePct(INVESTOR_AVERAGE_HHI, 0, 0.6),
            axisStart: "Spread out",
            axisMid: "Average",
            axisEnd: "Crowded",
            context: [
                { label: "Biggest sector", value: biggest },
                { label: "Spreads like", value: `~${effBets} even sectors` },
            ],
            icon: val <= INVESTOR_AVERAGE_HHI ? "bi-check2-circle" : "bi-exclamation-triangle",
            takeaway: `Behaves like about ${effBets} equal-sized sectors. ${comparison.sub}`,
        });
    }

    async function loadDrawdownChart() {
        showLoading("drawdown-loading", true);
        showEmpty("drawdown-empty", false);
        try {
            const res = await fetch("/api/portfolio/drawdown");
            const data = await res.json();

            if (!data.has_data) {
                showEmpty("drawdown-empty", true);
                drawdownChart?.destroy();
                drawdownChart = null;
                return;
            }

            const ann = $("drawdown-annotation");
            if (ann) {
                ann.textContent = data.max_drawdown_pct < 0
                    ? `Max drawdown: ${data.max_drawdown_pct.toFixed(1)}%${data.max_drawdown_date ? ` on ${data.max_drawdown_date}` : ""}`
                    : "";
            }

            const theme = chartTheme();
            const scale = uiScale();
            const ctx = $("drawdown-chart")?.getContext("2d");
            if (!ctx) return;

            const labels = data.series.map(s => s.date);
            const values = data.series.map(s => s.drawdown_pct);
            const red = token("--accent-red", "#ff453a");

            drawdownChart?.destroy();
            drawdownChart = new Chart(ctx, {
                type: "line",
                data: {
                    labels,
                    datasets: [{
                        label: "Drawdown %",
                        data: values,
                        borderColor: red,
                        backgroundColor: red + "33",
                        fill: true,
                        tension: 0.25,
                        pointRadius: 0,
                        borderWidth: 2,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            ...tooltipOptions(),
                            callbacks: {
                                label(item) {
                                    const v = item.parsed?.y ?? item.raw;
                                    return `Drawdown: ${Number(v).toFixed(1)}%`;
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            ticks: { color: theme.tick, maxTicksLimit: 6, font: { size: 9 * scale } },
                            grid: { color: theme.grid },
                        },
                        y: {
                            ticks: {
                                color: theme.tick,
                                font: { size: 10 * scale },
                                callback: v => `${Number(v).toFixed(1)}%`,
                            },
                            grid: { color: theme.grid },
                            max: 0,
                        },
                    },
                },
            });
        } catch (err) {
            console.warn("Drawdown chart failed:", err);
            showEmpty("drawdown-empty", true);
        } finally {
            showLoading("drawdown-loading", false);
        }
    }

    const MONTH_LABELS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

    function filterBenchmarkSeries(series, rangeKey) {
        if (!series?.length) return [];
        const days = { "1m": 30, "3m": 90, "1y": 365, max: null }[rangeKey];
        if (!days || series.length <= days) return series;
        return series.slice(-days);
    }

    function updateBenchmarkStats(data, rangeKey) {
        const row = $("benchmark-stat-row");
        const stats = data.ranges?.[rangeKey];
        if (!row || !stats) {
            row?.setAttribute("hidden", "");
            return;
        }
        row.hidden = false;
        const fmt = v => `${v >= 0 ? "+" : ""}${Number(v).toFixed(1)}%`;
        const portEl = $("benchmark-port-pct");
        const spyEl = $("benchmark-spy-pct");
        const alphaEl = $("benchmark-alpha-pct");
        if (portEl) {
            portEl.textContent = fmt(stats.portfolio_pct);
            portEl.className = `benchmark-stat-value ${stats.portfolio_pct >= 0 ? "text-success" : "text-danger"}`;
        }
        if (spyEl) spyEl.textContent = fmt(stats.benchmark_pct);
        if (alphaEl) {
            alphaEl.textContent = fmt(stats.alpha_pct);
            alphaEl.className = `benchmark-stat-value ${stats.alpha_pct >= 0 ? "text-success" : "text-danger"}`;
        }
    }

    function renderBenchmarkChart(data) {
        const ctx = $("benchmark-chart")?.getContext("2d");
        if (!ctx || !data?.series?.length) return;

        const filtered = filterBenchmarkSeries(data.series, benchmarkRange);
        const theme = chartTheme();
        const scale = uiScale();
        const labels = filtered.map(s => s.date);
        const portColor = token("--accent-cyan", "#64d2ff");
        const spyColor = token("--text-tertiary", "#8e8e93");

        benchmarkChart?.destroy();
        benchmarkChart = new Chart(ctx, {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        label: "Portfolio",
                        data: filtered.map(s => s.portfolio_pct),
                        borderColor: portColor,
                        backgroundColor: portColor + "22",
                        fill: false,
                        tension: 0.25,
                        pointRadius: 0,
                        borderWidth: 2,
                    },
                    {
                        label: "S&P 500",
                        data: filtered.map(s => s.benchmark_pct),
                        borderColor: spyColor,
                        borderDash: [5, 4],
                        fill: false,
                        tension: 0.25,
                        pointRadius: 0,
                        borderWidth: 1.5,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        labels: { color: theme.tick, boxWidth: 10, font: { size: 10 * scale } },
                    },
                    tooltip: {
                        ...tooltipOptions(),
                        callbacks: {
                            label(item) {
                                const v = item.parsed?.y ?? item.raw;
                                return `${item.dataset.label}: ${Number(v).toFixed(1)}%`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        ticks: { color: theme.tick, maxTicksLimit: 6, font: { size: 9 * scale } },
                        grid: { color: theme.grid },
                    },
                    y: {
                        ticks: {
                            color: theme.tick,
                            font: { size: 10 * scale },
                            callback: v => `${Number(v).toFixed(0)}%`,
                        },
                        grid: { color: theme.grid },
                    },
                },
            },
        });
        updateBenchmarkStats(data, benchmarkRange);
    }

    async function loadBenchmarkChart() {
        showLoading("benchmark-loading", true);
        showEmpty("benchmark-empty", false);
        try {
            const res = await fetch("/api/portfolio/benchmark-comparison");
            const data = await res.json();
            if (!data.has_data) {
                showEmpty("benchmark-empty", true);
                benchmarkChart?.destroy();
                benchmarkChart = null;
                _benchmarkData = null;
                return;
            }
            _benchmarkData = data;
            if (!data.ranges?.[benchmarkRange]) {
                benchmarkRange = data.active_range || Object.keys(data.ranges || {})[0] || "1y";
                const tabs = $("benchmark-range-tabs");
                if (tabs) {
                    tabs.dataset.activeRange = benchmarkRange;
                    tabs.querySelectorAll(".benchmark-range-btn").forEach(b => {
                        const on = b.dataset.range === benchmarkRange;
                        b.classList.toggle("is-active", on);
                        b.setAttribute("aria-pressed", String(on));
                    });
                }
            }
            renderBenchmarkChart(data);
        } catch (err) {
            console.warn("Benchmark chart failed:", err);
            showEmpty("benchmark-empty", true);
        } finally {
            showLoading("benchmark-loading", false);
        }
    }

    function betaLaymanNote(beta) {
        const b = Number(beta) || 1;
        const marketMove = (b * 1).toFixed(1);
        if (b < 0.85) {
            return `If the S&P 500 moves 1% in a day, your portfolio has tended to move about ${marketMove}% — quieter than the market.`;
        }
        if (b < 1.15) {
            return "If the S&P 500 moves 1% in a day, your portfolio has tended to move about the same — in step with the market.";
        }
        const extra = Math.round((b - 1) * 100);
        return `If the S&P 500 moves 1% in a day, your portfolio has tended to move about ${marketMove}% — roughly ${extra}% more swing than the market.`;
    }

    function betaLabel(beta) {
        const b = Number(beta);
        return `${(Number.isFinite(b) ? b : 0).toFixed(2)}x`;
    }

    function betaLevel(beta) {
        const n = Number(beta);
        const b = Number.isFinite(n) ? n : 1;
        if (b < 0.75) return "Defensive";
        if (b < 1.1) return "Market pace";
        return "Aggressive";
    }

    function betaComparison(beta) {
        const n = Number(beta);
        const diff = (Number.isFinite(n) ? n : 1) - INVESTOR_AVERAGE_BETA;
        if (Math.abs(diff) < 0.05) {
            return { value: "Near average", sub: "Your market swing is close to the investor baseline." };
        }
        const lower = diff < 0;
        return {
            value: `${Math.round(Math.abs(diff) * 100)}% ${lower ? "less" : "more"} swing`,
            sub: lower ? "Quieter than the investor baseline." : "More sensitive than the investor baseline.",
        };
    }

    function volLevel(pct) {
        const v = Number(pct) || 0;
        if (v < 14) return { key: "calm", label: "Calm", hint: "smaller day-to-day swings" };
        if (v < 22) return { key: "moderate", label: "Typical", hint: "normal for a stock portfolio" };
        return { key: "choppy", label: "Choppy", hint: "larger ups and downs lately" };
    }

    function volLaymanNote(current, level) {
        return `Right now your ride feels <strong>${level.label.toLowerCase()}</strong> — about <strong>${current.toFixed(1)}%</strong> yearly ups and downs (${level.hint}).`;
    }

    function drawBetaGauge(beta) {
        const val = Math.max(0, Math.min(2, beta));
        const comparison = betaComparison(val);

        renderRiskLens("beta-lens", {
            tone: val < 0.85 ? "cool" : val < 1.15 ? "calm" : "hot",
            metric: betaLabel(val),
            state: betaLevel(val),
            badge: comparison.value,
            avgMetric: betaLabel(INVESTOR_AVERAGE_BETA),
            youPct: scalePct(val, 0, 2),
            avgPct: scalePct(INVESTOR_AVERAGE_BETA, 0, 2),
            axisStart: "Defensive",
            axisMid: "Market",
            axisEnd: "Aggressive",
            context: [
                { label: "Typical 1% day", value: `~${val.toFixed(1)}% move` },
                { label: "Market falls 10%", value: `~${(val * 10).toFixed(0)}% drop` },
            ],
            icon: val <= 1.1 ? "bi-check2-circle" : "bi-activity",
            takeaway: comparison.sub,
        });
    }

    async function loadBetaGauge() {
        showLoading("beta-loading", true);
        showEmpty("beta-empty", false);
        try {
            const res = await fetch("/api/portfolio/beta");
            const data = await res.json();
            if (!data.has_data) {
                showEmpty("beta-empty", true);
                clearRiskLens("beta-lens");
                return;
            }
            const beta = Number(data.beta) || 1;
            const layman = $("beta-layman-note");
            if (layman) layman.textContent = betaLaymanNote(beta);
            drawBetaGauge(beta);
            _lastBeta = beta;
            _betaGaugeReady = true;
        } catch (err) {
            console.warn("Beta gauge failed:", err);
            showEmpty("beta-empty", true);
            clearRiskLens("beta-lens");
        } finally {
            showLoading("beta-loading", false);
        }
    }

    async function loadRollingVolChart() {
        showLoading("rolling-vol-loading", true);
        showEmpty("rolling-vol-empty", false);
        try {
            const res = await fetch("/api/portfolio/rolling-volatility");
            const data = await res.json();
            if (!data.has_data) {
                showEmpty("rolling-vol-empty", true);
                $("rolling-vol-summary")?.setAttribute("hidden", "");
                rollingVolChart?.destroy();
                rollingVolChart = null;
                return;
            }

            const current = Number(data.current_vol_pct) || 0;
            const level = volLevel(current);
            const series = data.series || [];
            const prior = series.length >= 20 ? Number(series[series.length - 20].vol_pct) : null;
            const trendDelta = prior != null ? current - prior : 0;

            const summary = $("rolling-vol-summary");
            const badge = $("rolling-vol-badge");
            const trendEl = $("rolling-vol-trend");
            const layman = $("rolling-vol-layman");
            const zones = $("rolling-vol-zones");

            if (summary) summary.hidden = false;
            if (badge) {
                badge.textContent = level.label;
                badge.className = `vol-level-badge vol-level-badge--${level.key}`;
            }
            if (trendEl) {
                if (prior == null) {
                    trendEl.textContent = "";
                    trendEl.hidden = true;
                } else {
                    trendEl.hidden = false;
                    const dir = trendDelta > 1 ? "Bumpier than a month ago" : trendDelta < -1 ? "Calmer than a month ago" : "Similar to a month ago";
                    const icon = trendDelta > 1 ? "↑" : trendDelta < -1 ? "↓" : "→";
                    trendEl.textContent = `${icon} ${dir}`;
                    trendEl.className = `rolling-vol-trend rolling-vol-trend--${trendDelta > 1 ? "up" : trendDelta < -1 ? "down" : "flat"}`;
                }
            }
            if (layman) layman.innerHTML = volLaymanNote(current, level);
            zones?.querySelectorAll(".vol-zone").forEach(el => {
                el.classList.toggle("is-active", el.classList.contains(`vol-zone--${level.key}`));
            });

            const theme = chartTheme();
            const scale = uiScale();
            const ctx = $("rolling-vol-chart")?.getContext("2d");
            if (!ctx) return;
            const labels = series.map(s => s.date);
            const values = series.map(s => s.vol_pct);
            const color = token("--accent-yellow", "#ffd60a");
            const calmLine = token("--accent-green", "#30d158");
            const typicalLine = token("--accent-cyan", "#64d2ff");

            rollingVolChart?.destroy();
            rollingVolChart = new Chart(ctx, {
                type: "line",
                data: {
                    labels,
                    datasets: [
                        {
                            label: "Calm guide (14%)",
                            data: labels.map(() => 14),
                            borderColor: calmLine + "55",
                            borderDash: [4, 4],
                            pointRadius: 0,
                            borderWidth: 1,
                            fill: false,
                        },
                        {
                            label: "Typical guide (22%)",
                            data: labels.map(() => 22),
                            borderColor: typicalLine + "55",
                            borderDash: [4, 4],
                            pointRadius: 0,
                            borderWidth: 1,
                            fill: false,
                        },
                        {
                            label: "Your bumpiness",
                            data: values,
                            borderColor: color,
                            backgroundColor: color + "28",
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0,
                            borderWidth: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            ...tooltipOptions(),
                            filter(item) {
                                return item.datasetIndex === 2;
                            },
                            callbacks: {
                                label(item) {
                                    const v = Number(item.parsed?.y ?? item.raw);
                                    const lvl = volLevel(v);
                                    return `Bumpiness: ${v.toFixed(1)}% (${lvl.label.toLowerCase()})`;
                                },
                            },
                        },
                    },
                    scales: {
                        x: { ticks: { color: theme.tick, maxTicksLimit: 5, font: { size: 9 * scale } }, grid: { color: theme.grid } },
                        y: {
                            title: {
                                display: true,
                                text: "Yearly swing size",
                                color: theme.tick,
                                font: { size: 10 * scale },
                            },
                            ticks: { color: theme.tick, font: { size: 10 * scale }, callback: v => `${v}%` },
                            grid: { color: theme.grid },
                            suggestedMin: 8,
                        },
                    },
                },
            });
        } catch (err) {
            console.warn("Rolling vol failed:", err);
            showEmpty("rolling-vol-empty", true);
        } finally {
            showLoading("rolling-vol-loading", false);
        }
    }

    function _buildSectorTiltListHTML(rows, maxTilt, esc, portLabel) {
        return rows.map((s, index) => {
            const side = s.tilt >= 0 ? "over" : "under";
            const absTilt = Math.abs(s.tilt);
            const w = Math.max(4, Math.round(absTilt / maxTilt * 50));
            const theme = sectorTheme(s.name);
            return `<div class="sector-tilt-row sector-tilt-row--${side}"
                style="--tilt-width:${w}%;--sector-accent:${theme.color};--row-index:${index}"
                data-sector="${esc(s.name)}"
                data-port-full="${s.portFull ?? s.port}"
                data-bench="${s.bench}"
                data-side="${side}">
                <div class="sector-tilt-sector">
                    <span class="sector-tilt-icon" aria-hidden="true"><i class="bi ${theme.icon}"></i></span>
                    <span class="sector-tilt-name">${esc(s.name)}</span>
                </div>
                <div class="sector-tilt-track" aria-label="${esc(s.name)} ${side === "over" ? "overweight" : "underweight"} by ${absTilt.toFixed(1)} percentage points">
                    <span class="sector-tilt-baseline"></span>
                    <span class="sector-tilt-bar"></span>
                </div>
                <div class="sector-tilt-values">
                    <span><small>${esc(portLabel)}</small>${s.port.toFixed(1)}%</span>
                    <span><small>S&amp;P</small>${s.bench.toFixed(1)}%</span>
                    <strong>${s.tilt >= 0 ? "+" : ""}${s.tilt.toFixed(1)}pp</strong>
                </div>
            </div>`;
        }).join("");
    }

    function _makeSectorTiltRows(sectors) {
        return (sectors || [])
            .map(s => ({
                name: s.name,
                tilt: Number(s.tilt_pct) || 0,
                port: Number(s.portfolio_pct) || 0,
                bench: Number(s.benchmark_pct) || 0,
            }))
            .sort((a, b) => Math.abs(b.tilt) - Math.abs(a.tilt));
    }

    function renderSectorTilt(sectors) {
        const root = $("sector-tilt-chart");
        if (!root) return;
        const rows = _makeSectorTiltRows(sectors);
        if (!rows.length) {
            root.innerHTML = "";
            return;
        }

        const maxTilt = Math.max(...rows.map(s => Math.abs(s.tilt)), 5);
        const largest = rows[0];
        const largestTheme = sectorTheme(largest.name);
        const overCount = rows.filter(s => s.tilt > 0.25).length;
        const underCount = rows.filter(s => s.tilt < -0.25).length;
        const activeTilt = rows.reduce((sum, s) => sum + Math.abs(s.tilt), 0) / 2;
        const esc = typeof escapeHtml === "function" ? escapeHtml : escapeText;
        const summaryTone = largest.tilt >= 0 ? "over" : "under";

        const summary = `<div class="sector-tilt-summary sector-tilt-summary--${summaryTone}"
            style="--sector-accent:${largestTheme.color}">
            <div class="sector-tilt-orb" aria-hidden="true">
                <i class="bi ${largestTheme.icon}"></i>
            </div>
            <div class="sector-tilt-summary-main">
                <span class="sector-tilt-eyebrow">Largest benchmark tilt</span>
                <strong>${esc(largest.name)}</strong>
                <span>Portfolio ${largest.port.toFixed(1)}% vs S&amp;P ${largest.bench.toFixed(1)}%</span>
            </div>
            <div class="sector-tilt-summary-delta">
                ${largest.tilt >= 0 ? "+" : ""}${largest.tilt.toFixed(1)}pp
                <small>${largest.tilt >= 0 ? "Overweight" : "Underweight"}</small>
            </div>
        </div>`;

        const stats = `<div class="sector-tilt-artifacts" aria-label="Benchmark tilt summary">
            <span class="sector-tilt-artifact">
                <i class="bi bi-crosshair2" aria-hidden="true"></i>
                <small>Active tilt</small>
                <strong>${activeTilt.toFixed(1)}pp</strong>
            </span>
            <span class="sector-tilt-artifact sector-tilt-artifact--over">
                <i class="bi bi-arrow-up-right" aria-hidden="true"></i>
                <small>Overweights</small>
                <strong>${overCount}</strong>
            </span>
            <span class="sector-tilt-artifact sector-tilt-artifact--under">
                <i class="bi bi-arrow-down-left" aria-hidden="true"></i>
                <small>Underweights</small>
                <strong>${underCount}</strong>
            </span>
        </div>`;

        const legend = `<div class="sector-tilt-axis" aria-hidden="true">
            <span>Underweight</span>
            <span>S&amp;P 500 baseline</span>
            <span>Overweight</span>
        </div>`;

        const listHTML = _buildSectorTiltListHTML(rows, maxTilt, esc, "Port");

        root.innerHTML = `${summary}${stats}${legend}<div class="sector-tilt-list">${listHTML}</div>`;

        // Reapply any active selection (e.g. user was on overview tab, then switched here)
        if (_sectorTiltSelectedTicker) {
            applySectorTiltSelection(_sectorTiltSelectedTicker, { skipFade: true });
        }
    }

    function updateSectorTiltModePill(root, ticker) {
        let pill = root.querySelector(".sector-tilt-mode-pill");
        if (!pill) {
            pill = document.createElement("div");
            pill.className = "sector-tilt-mode-pill";
            root.prepend(pill);
        }

        if (ticker) {
            pill.innerHTML = `<i class="bi bi-funnel-fill" aria-hidden="true"></i>
                <span>Viewing <strong>${ticker}</strong> contribution only</span>
                <button class="sector-tilt-mode-clear" aria-label="Clear selection"
                    onclick="if(typeof selectAllocationTicker==='function')selectAllocationTicker(null)">
                    <i class="bi bi-x-lg"></i>
                </button>`;
            pill.style.display = "";
        } else {
            pill.style.display = "none";
        }
    }

    function applySectorTiltSelection(ticker, { skipFade = false } = {}) {
        const root = $("sector-tilt-chart");
        if (!root || !_sectorTiltFull.length) return;

        const esc = typeof escapeHtml === "function" ? escapeHtml : escapeText;
        const useContribs = ticker ? (_sectorHoldingContribs[ticker] || null) : null;

        // Compute new rows using either full portfolio or holding contribution data
        const modRows = _makeSectorTiltRows(_sectorTiltFull).map(r => {
            const port = useContribs ? (useContribs[r.name] || 0) : r.port;
            return {
                name: r.name,
                port,
                portFull: r.port,
                bench: r.bench,
                tilt: port - r.bench,
            };
        }).sort((a, b) => Math.abs(b.tilt) - Math.abs(a.tilt));

        const maxTilt = Math.max(...modRows.map(r => Math.abs(r.tilt)), 5);
        const largest = modRows[0];
        const portLabel = ticker || "Port";

        const doUpdate = () => {
            // Rebuild the list with updated values
            const list = root.querySelector(".sector-tilt-list");
            if (list) {
                list.innerHTML = _buildSectorTiltListHTML(modRows, maxTilt, esc, portLabel);

                // Dim rows where the selected holding has zero contribution
                if (useContribs) {
                    list.querySelectorAll(".sector-tilt-row").forEach(row => {
                        const sectorName = row.dataset.sector;
                        const contrib = useContribs[sectorName] || 0;
                        row.style.opacity = contrib === 0 ? "0.28" : "";
                    });
                }
            }

            // Update summary card
            const summaryEl = root.querySelector(".sector-tilt-summary");
            if (summaryEl && largest) {
                const largestTheme = sectorTheme(largest.name);
                const tone = largest.tilt >= 0 ? "over" : "under";
                summaryEl.className = `sector-tilt-summary sector-tilt-summary--${tone}`;
                summaryEl.style.setProperty("--sector-accent", largestTheme.color);

                const orbEl = summaryEl.querySelector(".sector-tilt-orb i");
                if (orbEl) orbEl.className = `bi ${largestTheme.icon}`;

                const nameEl = summaryEl.querySelector(".sector-tilt-summary-main strong");
                if (nameEl) nameEl.textContent = largest.name;

                const detailEl = summaryEl.querySelector(".sector-tilt-summary-main span:last-child");
                if (detailEl) {
                    detailEl.innerHTML = `${esc(portLabel)} ${largest.port.toFixed(1)}% vs S&amp;P ${largest.bench.toFixed(1)}%`;
                }

                const deltaEl = summaryEl.querySelector(".sector-tilt-summary-delta");
                if (deltaEl) {
                    deltaEl.innerHTML = `${largest.tilt >= 0 ? "+" : ""}${largest.tilt.toFixed(1)}pp<small>${largest.tilt >= 0 ? "Overweight" : "Underweight"}</small>`;
                }
            }

            // Update artifact stats
            const overCount = modRows.filter(r => r.tilt > 0.25).length;
            const underCount = modRows.filter(r => r.tilt < -0.25).length;
            const activeTilt = modRows.reduce((sum, r) => sum + Math.abs(r.tilt), 0) / 2;
            const artifactEls = root.querySelectorAll(".sector-tilt-artifact strong");
            if (artifactEls[0]) artifactEls[0].textContent = `${activeTilt.toFixed(1)}pp`;
            if (artifactEls[1]) artifactEls[1].textContent = overCount;
            if (artifactEls[2]) artifactEls[2].textContent = underCount;

            // Update eyebrow label
            const eyebrow = root.querySelector(".sector-tilt-eyebrow");
            if (eyebrow) {
                eyebrow.textContent = ticker ? `${ticker} benchmark contribution` : "Largest benchmark tilt";
            }

            updateSectorTiltModePill(root, ticker);
        };

        if (skipFade) {
            doUpdate();
            return;
        }

        // Smooth fade-out → update → fade-in
        const list = root.querySelector(".sector-tilt-list");
        const summaryEl = root.querySelector(".sector-tilt-summary");
        const els = [list, summaryEl].filter(Boolean);

        els.forEach(el => {
            el.style.transition = "opacity 0.13s ease";
            el.style.opacity = "0";
        });

        setTimeout(() => {
            doUpdate();
            els.forEach(el => {
                el.style.opacity = "1";
                el.addEventListener("transitionend", () => {
                    el.style.transition = "";
                    el.style.opacity = "";
                }, { once: true });
            });
        }, 140);
    }

    function updateSectorTiltForTicker(ticker) {
        _sectorTiltSelectedTicker = ticker || null;
        applySectorTiltSelection(_sectorTiltSelectedTicker);
    }

    async function loadSectorTilt() {
        showLoading("sector-tilt-loading", true);
        showEmpty("sector-tilt-empty", false);
        try {
            const res = await fetch("/api/portfolio/sector-tilt");
            const data = await res.json();
            if (!data.has_data) {
                showEmpty("sector-tilt-empty", true);
                const root = $("sector-tilt-chart");
                if (root) root.innerHTML = "";
                return;
            }
            _sectorTiltFull = data.sectors || [];
            _sectorHoldingContribs = data.holding_contributions || {};
            renderSectorTilt(_sectorTiltFull);
        } catch (err) {
            console.warn("Sector tilt failed:", err);
            showEmpty("sector-tilt-empty", true);
            const root = $("sector-tilt-chart");
            if (root) root.innerHTML = "";
        } finally {
            showLoading("sector-tilt-loading", false);
        }
    }

    const GAP_CONFIG = {
        large_trim: {
            badge: "TRIM",
            icon: "bi-arrow-down-circle",
            colorVar: "--accent-red",
            colorFallback: "#ff453a",
            desc: g => `You hold ${g.allocation_pct}% but the signal says trim — this position may be oversized relative to current conviction.`,
        },
        small_add: {
            badge: "ADD",
            icon: "bi-arrow-up-circle",
            colorVar: "--accent-cyan",
            colorFallback: "#64d2ff",
            desc: g => `Strong buy signal but only ${g.allocation_pct}% allocated — the AI thinks this position has more room to grow.`,
        },
        heavy_hold: {
            badge: "HOLD",
            icon: "bi-dash-circle",
            colorVar: "--accent-yellow",
            colorFallback: "#ffd60a",
            desc: g => `${g.allocation_pct}% of your portfolio sits here on a hold signal — a sizeable bet without a strong case to grow or cut.`,
        },
        uncertain_hold: {
            badge: "UNSURE",
            icon: "bi-question-circle",
            colorVar: "--text-tertiary",
            colorFallback: "#8e8e93",
            desc: g => `${g.allocation_pct}% allocated but the AI has low confidence (${g.confidence}%) in this signal — the outlook here is unclear.`,
        },
    };

    function renderConvictionGaps(gaps, summary) {
        const list = $("conviction-gap-list");
        if (!list) return;

        // portfolio-wide summary pill above the list
        const summaryEl = $("conviction-gap-summary");
        if (summaryEl && summary) {
            const { flagged, total, flagged_alloc_pct } = summary;
            summaryEl.innerHTML = `
                <span class="cg-summary-stat"><strong>${flagged}</strong> of ${total} holdings flagged</span>
                <span class="cg-summary-dot">·</span>
                <span class="cg-summary-stat"><strong>${flagged_alloc_pct}%</strong> of portfolio weight</span>`;
            summaryEl.style.display = "flex";
        }
        list.innerHTML = gaps.map(g => {
            const cfg = GAP_CONFIG[g.gap_type] || {
                badge: (g.action || "?").toUpperCase(),
                icon: "bi-circle",
                colorVar: "--text-secondary",
                colorFallback: "#8e8e93",
                desc: () => "",
            };
            const col = token(cfg.colorVar, cfg.colorFallback);
            const confCol = g.confidence >= 75
                ? token("--accent-green", "#30d158")
                : g.confidence >= 60
                    ? token("--accent-yellow", "#ffd60a")
                    : token("--text-tertiary", "#636366");
            return `<div class="conviction-gap-row">
                <div class="conviction-gap-top">
                    <span class="conviction-gap-ticker">${escapeHtml(g.ticker)}</span>
                    <span class="conviction-gap-badge" style="color:${col};border-color:${col}">
                        <i class="bi ${cfg.icon}"></i>${cfg.badge}
                    </span>
                    <span class="conviction-gap-alloc">${g.allocation_pct}% of portfolio</span>
                </div>
                <div class="conviction-gap-desc">${cfg.desc(g)}</div>
                <div class="conviction-gap-footer">
                    <span class="conviction-gap-conf" style="color:${confCol}">AI confidence: ${g.confidence}%</span>
                </div>
            </div>`;
        }).join("");
    }

    async function loadConvictionGaps() {
        showLoading("conviction-gap-loading", true);
        showEmpty("conviction-gap-empty", false);
        try {
            const res = await fetch("/api/portfolio/conviction-gaps");
            const data = await res.json();
            if (!data.has_data) {
                showEmpty("conviction-gap-empty", true);
                const list = $("conviction-gap-list");
                if (list) list.innerHTML = "";
                return;
            }
            renderConvictionGaps(data.gaps || [], data.summary || null);
        } catch (err) {
            console.warn("Conviction gaps failed:", err);
            showEmpty("conviction-gap-empty", true);
        } finally {
            showLoading("conviction-gap-loading", false);
        }
    }

    const CS_BAND_META = {
        low:       { label: "Uncertain",       hint: "AI signal is weak or unclear" },
        mid:       { label: "Moderate",        hint: "Some conviction, room for doubt" },
        high:      { label: "Confident",       hint: "Clear, reliable AI signal" },
        very_high: { label: "Very confident",  hint: "Strong conviction — high-signal bet" },
    };

    function renderConfidenceSpectrum(buckets, avg, holdings) {
        const root = $("confidence-spectrum-chart");
        if (!root) return;
        const colors = {
            low:       token("--accent-red",    "#ff453a"),
            mid:       token("--accent-yellow", "#ffd60a"),
            high:      token("--accent-cyan",   "#64d2ff"),
            very_high: token("--accent-green",  "#30d158"),
        };

        // Group holdings by band key
        const grouped = { low: [], mid: [], high: [], very_high: [] };
        (holdings || []).forEach(h => {
            const k = h.confidence < 60 ? "low"
                    : h.confidence < 70 ? "mid"
                    : h.confidence < 85 ? "high"
                    : "very_high";
            grouped[k].push(h);
        });
        // Sort each group by allocation descending
        Object.keys(grouped).forEach(k => grouped[k].sort((a, b) => b.allocation_pct - a.allocation_pct));

        const avgNote = avg >= 75 ? "Signals are generally strong across your book."
                      : avg >= 60 ? "Signals are mixed — some certainty, some guesswork."
                      : "Many signals are uncertain — worth reviewing positions carefully.";

        const bandRows = buckets.map(b => {
            const meta = CS_BAND_META[b.key] || { label: b.band, hint: "" };
            const c = colors[b.key] || colors.mid;
            const tickers = grouped[b.key] || [];
            const tickerHtml = tickers.length
                ? `<div class="cs-band-tickers">${
                    tickers.slice(0, 6).map(t =>
                        `<span class="cs-ticker-pill" title="${t.ticker}: ${t.confidence}% confidence · ${t.allocation_pct}% of portfolio">${escapeHtml(t.ticker)}</span>`
                    ).join("")}${tickers.length > 6 ? `<span class="cs-ticker-more">+${tickers.length - 6}</span>` : ""}</div>`
                : "";
            return `<div class="cs-band${b.weight_pct === 0 ? " cs-band-empty" : ""}">
                <div class="cs-band-header">
                    <span class="cs-band-dot" style="background:${c};box-shadow:0 0 0 4px color-mix(in srgb, ${c} 16%, transparent)"></span>
                    <span class="cs-band-range">${escapeHtml(b.band)}</span>
                    <span class="cs-band-name">${meta.label}</span>
                    <span class="cs-band-pct">${b.weight_pct}%</span>
                </div>
                ${b.weight_pct > 0 ? `<div class="cs-band-hint">${meta.hint}</div>` : ""}
                ${tickerHtml}
            </div>`;
        }).join("");

        root.innerHTML = `
            <div class="confidence-spectrum-bar" role="img" aria-label="Confidence distribution">
                ${buckets.filter(b => b.weight_pct > 0).map(b => {
                    const w = Math.min(100, Math.max(0, b.weight_pct));
                    return `<div class="confidence-spectrum-seg" style="width:${w}%;background:${colors[b.key] || colors.mid}" title="${escapeHtml(b.band)}: ${b.weight_pct}%"></div>`;
                }).join("")}
            </div>
            <div class="cs-bands">${bandRows}</div>
            <div class="cs-avg-row">
                <span class="cs-avg-label">Avg confidence</span>
                <strong class="cs-avg-value">${avg}%</strong>
                <span class="cs-avg-note">${avgNote}</span>
            </div>`;
    }

    async function loadConfidenceSpectrum() {
        showLoading("confidence-spectrum-loading", true);
        showEmpty("confidence-spectrum-empty", false);
        try {
            const res = await fetch("/api/portfolio/confidence-spectrum");
            const data = await res.json();
            if (!data.has_data) {
                showEmpty("confidence-spectrum-empty", true);
                return;
            }
            renderConfidenceSpectrum(data.buckets || [], data.avg_confidence || 0, data.holdings || []);
        } catch (err) {
            console.warn("Confidence spectrum failed:", err);
            showEmpty("confidence-spectrum-empty", true);
        } finally {
            showLoading("confidence-spectrum-loading", false);
        }
    }

    function renderMacroAlignmentLegend(points) {
        const legend = $("macro-alignment-legend");
        const wrap = $("macro-alignment-legend-wrap");
        if (!legend) return;
        if (!points?.length) {
            legend.innerHTML = "";
            wrap?.setAttribute("hidden", "");
            return;
        }
        const esc = typeof escapeHtml === "function" ? escapeHtml : s => s;
        const sorted = [...points].sort((a, b) => b.x - a.x || b.y - a.y);
        legend.innerHTML = sorted.map(pt => {
            const name = `${pt.flag ? pt.flag + " " : ""}${esc(pt.label)}`;
            return `<div class="macro-alignment-legend-item">
                <div class="macro-alignment-legend-head">
                    <span class="macro-alignment-legend-dot" style="background:${pt.color}"></span>
                    <span class="macro-alignment-legend-name">${name}</span>
                </div>
                <span class="macro-alignment-legend-meta">${pt.x.toFixed(0)}% corr · ${pt.y.toFixed(0)}% geo</span>
            </div>`;
        }).join("");
        wrap?.removeAttribute("hidden");
    }

    function setMacroAlignmentChartVisible(visible) {
        const shell = document.querySelector("#macro-alignment-card .macro-alignment-shell");
        if (shell) shell.hidden = !visible;
    }

    async function loadMacroAlignment() {
        showLoading("macro-alignment-loading", true);
        showEmpty("macro-alignment-empty", false);
        try {
            const res = await fetch("/api/portfolio/macro-alignment");
            const data = await res.json();
            if (!data.has_data || !data.points?.length) {
                showEmpty("macro-alignment-empty", true);
                setMacroAlignmentChartVisible(false);
                macroAlignmentChart?.destroy();
                macroAlignmentChart = null;
                renderMacroAlignmentLegend([]);
                return;
            }
            showEmpty("macro-alignment-empty", false);
            setMacroAlignmentChartVisible(true);
            const theme = chartTheme();
            const scale = uiScale();
            const isLight = typeof currentTheme === "function" && currentTheme() === "light";
            const ctx = $("macro-alignment-chart")?.getContext("2d");
            if (!ctx) return;

            const allY = data.points.map(p => p.geo_weight_pct || 0);
            const maxY = Math.max(...allY, 10);
            const midX = 50;
            const midY = Math.max(maxY * 0.5, 5);

            const QUAD_COLORS = {
                tr: "#ff453a",
                br: "#ff9f0a",
                tl: "#64d2ff",
                bl: "#30d158",
            };

            const points = data.points.map(p => {
                const x = (p.correlation || 0) * 100;
                const y = p.geo_weight_pct || 0;
                const quad = (x >= midX ? "r" : "l");
                const row  = (y >= midY ? "t" : "b");
                const color = QUAD_COLORS[row + quad];
                return { x, y, label: p.name, flag: p.flag || "", color, quad: row + quad };
            });

            renderMacroAlignmentLegend(points);

            const quadrantPlugin = {
                id: "macroQuadrant",
                beforeDraw(chart) {
                    const { ctx: c, chartArea: a, scales: { x: xs, y: ys } } = chart;
                    if (!a) return;
                    c.save();

                    const qx = xs.getPixelForValue(midX);
                    const qy = ys.getPixelForValue(midY);

                    const quadDefs = [
                        { x: a.left,  y: a.top,  w: qx - a.left,  h: qy - a.top,    fill: isLight ? "rgba(100,210,255,.05)" : "rgba(100,210,255,.04)", label: "Geo exposure", sub: "not correlated", anchor: "tl" },
                        { x: qx,      y: a.top,  w: a.right - qx, h: qy - a.top,    fill: isLight ? "rgba(255,69,58,.06)"   : "rgba(255,69,58,.07)",   label: "Most exposed",  sub: "headlines hit hardest", anchor: "tr" },
                        { x: a.left,  y: qy,     w: qx - a.left,  h: a.bottom - qy, fill: isLight ? "rgba(48,209,88,.04)"   : "rgba(48,209,88,.03)",   label: "Low impact",    sub: "low corr & exposure", anchor: "bl" },
                        { x: qx,      y: qy,     w: a.right - qx, h: a.bottom - qy, fill: isLight ? "rgba(255,159,10,.04)"  : "rgba(255,159,10,.04)",  label: "Moves with you", sub: "correlated, less geo", anchor: "br" },
                    ];

                    quadDefs.forEach(q => {
                        c.fillStyle = q.fill;
                        c.fillRect(q.x, q.y, q.w, q.h);
                    });

                    c.strokeStyle = isLight ? "rgba(0,0,0,.14)" : "rgba(255,255,255,.14)";
                    c.lineWidth = 1;
                    c.setLineDash([5, 5]);
                    c.beginPath(); c.moveTo(qx, a.top);    c.lineTo(qx, a.bottom); c.stroke();
                    c.beginPath(); c.moveTo(a.left, qy);   c.lineTo(a.right, qy);  c.stroke();
                    c.setLineDash([]);

                    const lfs = Math.max(10, 11 * scale);
                    const sfs = Math.max(8, 9 * scale);
                    const pad = 14;

                    quadDefs.forEach(q => {
                        const isRight = q.anchor.endsWith("r");
                        const isBottom = q.anchor.startsWith("b");
                        const lx = isRight  ? q.x + q.w - pad : q.x + pad;
                        const baseY = isBottom
                            ? q.y + q.h - pad - sfs - 4
                            : q.y + pad + lfs;

                        c.textAlign = isRight ? "right" : "left";
                        c.font = `700 ${lfs}px -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif`;
                        c.fillStyle = isLight ? "rgba(0,0,0,.32)" : "rgba(255,255,255,.26)";
                        c.fillText(q.label, lx, baseY);

                        c.font = `400 ${sfs}px -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif`;
                        c.fillStyle = isLight ? "rgba(0,0,0,.20)" : "rgba(255,255,255,.16)";
                        c.fillText(q.sub, lx, baseY + sfs + 5);
                    });

                    c.restore();
                },
            };

            macroAlignmentChart?.destroy();
            macroAlignmentChart = new Chart(ctx, {
                type: "scatter",
                plugins: [quadrantPlugin],
                data: {
                    datasets: [{
                        label: "Indices",
                        data: points,
                        backgroundColor: points.map(p => p.color + "cc"),
                        borderColor:     points.map(p => p.color),
                        borderWidth: 1.5,
                        pointRadius:      points.map(() => 8 * scale),
                        pointHoverRadius: 11 * scale,
                        clip: false,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: {
                        padding: {
                            top: 14,
                            right: 14,
                            bottom: 16,
                            left: 8,
                        },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            ...tooltipOptions(),
                            callbacks: {
                                title(items) {
                                    const raw = items[0]?.raw;
                                    return (raw?.flag ? raw.flag + " " : "") + (raw?.label || "");
                                },
                                label(item) {
                                    const raw = item.raw;
                                    const corrLabel = raw.x >= midX ? "High" : "Low";
                                    const geoLabel  = raw.y >= midY ? "High" : "Low";
                                    return [
                                        `Correlation with your portfolio: ${raw.x.toFixed(0)}% (${corrLabel})`,
                                        `Geographic exposure: ${raw.y.toFixed(0)}% (${geoLabel})`,
                                    ];
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: "← Less correlated   ·   More correlated →",
                                color: theme.tick,
                                font: { size: 10 * scale, weight: "500" },
                                padding: { top: 6, bottom: 4 },
                            },
                            min: 0,
                            max: 100,
                            grace: "2%",
                            ticks: {
                                color: theme.tick,
                                font: { size: 9 * scale },
                                callback: v => v + "%",
                            },
                            grid: { color: theme.grid },
                        },
                        y: {
                            title: {
                                display: true,
                                text: "Geographic exposure (% of portfolio) ↑",
                                color: theme.tick,
                                font: { size: 10 * scale, weight: "500" },
                                padding: { top: 4, bottom: 6 },
                            },
                            min: 0,
                            suggestedMax: Math.max(maxY * 1.15, maxY + 8),
                            grace: "12%",
                            ticks: {
                                color: theme.tick,
                                font: { size: 9 * scale },
                                callback: v => v + "%",
                            },
                            grid: { color: theme.grid },
                        },
                    },
                },
            });
        } catch (err) {
            console.warn("Macro alignment failed:", err);
            showEmpty("macro-alignment-empty", true);
            setMacroAlignmentChartVisible(false);
            renderMacroAlignmentLegend([]);
        } finally {
            showLoading("macro-alignment-loading", false);
        }
    }

    async function loadSectorTreemap() {
        showLoading("treemap-loading", true);
        showEmpty("treemap-empty", false);
        try {
            const data = await fetchPortfolioExposure();
            const sectors = (data.sector_exposure || []).filter(s => s.weight_pct > 0);

            if (!sectors.length) {
                showEmpty("treemap-empty", true);
                treemapChart?.destroy();
                treemapChart = null;
                clearTreemapOverlay();
                return;
            }

            ensureTreemapLabelPlugin();

            const ctx = $("sector-treemap-chart")?.getContext("2d");
            if (!ctx) return;

            if (!window.ChartTreemap && !window["chartjs-chart-treemap"]) {
                drawTreemapFallback(sectors);
                return;
            }

            const treeData = sectors.map(s => ({
                sector: s.name,
                value: s.weight_pct,
            }));

            treemapChart?.destroy();
            treemapChart = new Chart(ctx, {
                type: "treemap",
                data: {
                    datasets: [{
                        label: "Sectors",
                        tree: treeData,
                        key: "value",
                        groups: ["sector"],
                        spacing: 3,
                        borderWidth: 0,
                        borderRadius: 8,
                        borderColor: "transparent",
                        backgroundColor(ctx) {
                            return treemapTileBg(ctx);
                        },
                        labels: {
                            display: false,
                        },
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            ...tooltipOptions(),
                            callbacks: {
                                title(items) {
                                    const raw = items[0]?.raw;
                                    return raw?.g ?? raw?._data?.sector ?? "Sector";
                                },
                                label(item) {
                                    const v = item.raw?.v;
                                    return v != null ? `${v}% of portfolio` : "";
                                },
                            },
                        },
                    },
                },
            });
            treemapChart.$sectors = sectors;
            renderTreemapLabelOverlay(treemapChart);
        } catch (err) {
            console.warn("Treemap failed:", err);
            showEmpty("treemap-empty", true);
        } finally {
            showLoading("treemap-loading", false);
        }
    }

    function drawTreemapFallback(sectors) {
        const canvas = $("sector-treemap-chart");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        const w = canvas.parentElement?.clientWidth || 400;
        const h = 280;
        canvas.width = w;
        canvas.height = h;
        ctx.clearRect(0, 0, w, h);
        let x = 4;
        let y = 4;
        const total = sectors.reduce((s, r) => s + r.weight_pct, 0) || 1;
        sectors.forEach((s) => {
            const bw = Math.max(40, (s.weight_pct / total) * (w - 8));
            const bh = 40 + (s.weight_pct / total) * 120;
            const tileBg = sectorTileFill(s.name);
            ctx.fillStyle = tileBg;
            ctx.fillRect(x, y, bw - 4, bh);
            const [textColor] = contrastTextOn(tileBg);
            ctx.fillStyle = textColor;
            ctx.font = "600 11px -apple-system,sans-serif";
            ctx.fillText(s.name, x + 8, y + 18);
            ctx.font = "500 10px -apple-system,sans-serif";
            ctx.globalAlpha = 0.82;
            ctx.fillText(`${s.weight_pct}%`, x + 8, y + 32);
            ctx.globalAlpha = 1;
            x += bw;
            if (x > w - 60) { x = 4; y += bh + 4; }
        });
    }

    async function loadGeoExposure() {
        showLoading("geo-loading", true);
        showEmpty("geo-empty", false);
        try {
            const data = await fetchPortfolioExposure();
            const countries = (data.country_exposure || []).slice(0, 12);

            if (!countries.length) {
                showEmpty("geo-empty", true);
                return;
            }
            drawGeoList(countries);
        } catch (err) {
            console.warn("Geo exposure failed:", err);
            showEmpty("geo-empty", true);
        } finally {
            showLoading("geo-loading", false);
        }
    }

    const GEO_COUNTRY_FLAGS = {
        "united states": "🇺🇸",
        "usa": "🇺🇸",
        "us": "🇺🇸",
        "china": "🇨🇳",
        "india": "🇮🇳",
        "taiwan": "🇹🇼",
        "japan": "🇯🇵",
        "united kingdom": "🇬🇧",
        "uk": "🇬🇧",
        "canada": "🇨🇦",
        "south korea": "🇰🇷",
        "korea": "🇰🇷",
        "brazil": "🇧🇷",
        "netherlands": "🇳🇱",
        "australia": "🇦🇺",
        "chile": "🇨🇱",
        "south africa": "🇿🇦",
        "france": "🇫🇷",
        "germany": "🇩🇪",
        "switzerland": "🇨🇭",
        "sweden": "🇸🇪",
        "spain": "🇪🇸",
        "italy": "🇮🇹",
        "mexico": "🇲🇽",
        "hong kong": "🇭🇰",
        "singapore": "🇸🇬",
        "israel": "🇮🇱",
        "saudi arabia": "🇸🇦",
        "indonesia": "🇮🇩",
        "malaysia": "🇲🇾",
        "thailand": "🇹🇭",
        "philippines": "🇵🇭",
        "vietnam": "🇻🇳",
        "poland": "🇵🇱",
        "turkey": "🇹🇷",
        "russia": "🇷🇺",
        "ireland": "🇮🇪",
        "belgium": "🇧🇪",
        "denmark": "🇩🇰",
        "norway": "🇳🇴",
        "finland": "🇫🇮",
        "new zealand": "🇳🇿",
        "argentina": "🇦🇷",
        "colombia": "🇨🇴",
        "peru": "🇵🇪",
        "europe": "🇪🇺",
        "emea": "🌍",
        "americas": "🌎",
        "asia-pacific": "🌏",
        "asia pacific": "🌏",
        "apac": "🌏",
        "other": "🌐",
    };

    function geoCountryFlag(name) {
        const key = String(name || "").trim().toLowerCase();
        if (!key) return "🌐";
        if (GEO_COUNTRY_FLAGS[key]) return GEO_COUNTRY_FLAGS[key];
        const partial = Object.entries(GEO_COUNTRY_FLAGS).find(([k]) => key.includes(k) || k.includes(key));
        return partial ? partial[1] : "🌐";
    }

    function drawGeoList(countries) {
        const list = $("geo-exposure-list");
        if (!list) return;
        const max = Math.max(...countries.map(c => c.weight_pct), 1);

        list.innerHTML = countries.map(c => {
            const pct = Number(c.weight_pct) || 0;
            const width = Math.max(2, (pct / max) * 100);
            const label = escapeHtml(c.name);
            const flag = geoCountryFlag(c.name);
            const pctLabel = Number.isInteger(pct) ? `${pct}%` : `${pct}%`;
            return `<div class="geo-bar-row">
                <span class="geo-bar-label" title="${label}">
                    <span class="geo-bar-flag" aria-hidden="true">${flag}</span>
                    <span class="geo-bar-name">${label}</span>
                </span>
                <div class="geo-bar-track" aria-hidden="true">
                    <div class="geo-bar-fill" style="width:${width.toFixed(1)}%"></div>
                </div>
                <span class="geo-bar-pct">${pctLabel}</span>
            </div>`;
        }).join("");
    }

    async function loadContributionChart() {
        showLoading("contribution-loading", true);
        showEmpty("contribution-empty", false);
        try {
            const res = await fetch(`/api/portfolio/contribution?period=${contributionPeriod}`);
            const data = await res.json();

            if (!data.has_data) {
                showEmpty("contribution-empty", true);
                return;
            }
            renderContributionChart(data);
        } catch (err) {
            console.warn("Contribution chart failed:", err);
            showEmpty("contribution-empty", true);
        } finally {
            showLoading("contribution-loading", false);
        }
    }

    function renderContributionChart(data) {
        const root = $("contribution-chart");
        if (!root) return;

        const periodLabels = { day: "today", week: "past week", month: "past month" };
        const periodLabel = periodLabels[data.period] || "period";

        const totalContrib = Number(data.total_contribution) || 0;
        const portPct = Number(data.portfolio_change_pct);
        const totalUp = totalContrib >= 0;
        const totalCls = totalUp ? "positive" : "negative";
        const totalSign = totalUp ? "+" : "";
        const totalDollar = typeof formatCompact === "function"
            ? formatCompact(totalContrib)
            : `$${totalContrib.toFixed(2)}`;
        const totalPctStr = typeof formatPct === "function" && Number.isFinite(portPct)
            ? formatPct(portPct)
            : `${portPct >= 0 ? "+" : ""}${portPct.toFixed(2)}%`;
        const holdingsCount = data.holdings_count || (data.holdings || []).length;

        const gainers = data.top_gainers || [];
        const losers = data.top_losers || [];
        const others = data.others || null;

        if (!gainers.length && !losers.length && !others) return;

        const maxAbs = Math.max(
            ...[...gainers, ...losers, others].filter(Boolean).map(h => Math.abs(h.contribution)),
            1,
        );

        const renderRow = (h, idx) => {
            const up = h.contribution >= 0;
            const tone = up ? "positive" : "negative";
            const barPct = Math.round(Math.abs(h.contribution) / maxAbs * 100);
            const dollarStr = typeof formatCompact === "function"
                ? formatCompact(h.contribution)
                : `$${Number(h.contribution).toFixed(2)}`;
            const chgStr = h.change_pct == null
                ? "—"
                : (typeof formatPct === "function" ? formatPct(h.change_pct) : `${h.change_pct}%`);
            const shareStr = h.contribution_pct != null
                ? `${Math.min(100, Math.abs(h.contribution_pct)).toFixed(0)}% of move`
                : "";
            const weightStr = h.allocation_pct != null
                ? `${Number(h.allocation_pct).toFixed(1)}% wt`
                : "";
            const name = h.name && h.name !== h.ticker ? h.name : "";
            const title = [h.ticker, name, weightStr, shareStr].filter(Boolean).join(" · ");

            return `<div class="portfolio-contrib-row ${tone}" style="--contrib-delay:${idx * 0.05}s">
                <div class="portfolio-contrib-meta">
                    <span class="portfolio-contrib-ticker" title="${escapeHtml(title)}">${escapeHtml(h.ticker)}</span>
                    ${name ? `<span class="portfolio-contrib-name">${escapeHtml(name)}</span>` : ""}
                    <span class="portfolio-contrib-weight">${escapeHtml(weightStr)}</span>
                </div>
                <span class="portfolio-contrib-chg ${tone}">${escapeHtml(chgStr)}</span>
                <div class="portfolio-contrib-bar-track" aria-hidden="true">
                    <div class="portfolio-contrib-bar-fill ${tone}" style="width:${barPct}%"></div>
                </div>
                <div class="portfolio-contrib-impact ${tone}">
                    <span class="portfolio-contrib-dollar">${escapeHtml(dollarStr)}</span>
                    ${shareStr ? `<span class="portfolio-contrib-share">${escapeHtml(shareStr)}</span>` : ""}
                </div>
            </div>`;
        };

        const renderGroup = (title, tone, items, baseIdx) => {
            if (!items.length) {
                return `<div class="portfolio-contrib-group ${tone}">
                    <div class="portfolio-contrib-group-title">${escapeHtml(title)}</div>
                    <div class="portfolio-contrib-empty">No ${tone === "positive" ? "gainers" : "losers"}</div>
                </div>`;
            }
            return `<div class="portfolio-contrib-group ${tone}">
                <div class="portfolio-contrib-group-title">${escapeHtml(title)}</div>
                ${items.map((h, i) => renderRow(h, baseIdx + i)).join("")}
            </div>`;
        };

        let rowIdx = 0;
        const gainersHtml = renderGroup("Top gainers", "positive", gainers, rowIdx);
        rowIdx += gainers.length;
        const losersHtml = renderGroup("Top drag", "negative", losers, rowIdx);
        rowIdx += losers.length;
        const othersHtml = others
            ? `<div class="portfolio-contrib-group neutral">
                <div class="portfolio-contrib-group-title">Rest of portfolio</div>
                ${renderRow(others, rowIdx)}
               </div>`
            : "";

        root.innerHTML = `
            <div class="portfolio-contrib-summary">
                <div class="portfolio-contrib-summary-main">
                    <span class="portfolio-contrib-summary-label">Portfolio ${escapeHtml(periodLabel)}</span>
                    <span class="portfolio-contrib-summary-total ${totalCls}">${totalSign}${escapeHtml(totalDollar)}</span>
                    <span class="portfolio-contrib-summary-pct ${totalCls}">${escapeHtml(totalPctStr)}</span>
                </div>
                <span class="portfolio-contrib-summary-meta">${holdingsCount} holding${holdingsCount === 1 ? "" : "s"} · dollar impact by weight</span>
            </div>
            <div class="portfolio-contrib-grid">
                ${gainersHtml}
                ${losersHtml}
            </div>
            ${othersHtml}`;
    }

    function renderSignalBoard(data) {
        const grid = $("signal-board-grid");
        if (!grid) return;

        const signals = data?.signals || {};
        // O(1) watchlist lookup — avoids Array.find inside the filter callback.
        const watchlistTickers = new Set(
            (latestHoldings || []).filter(h => h.is_watchlist).map(h => h.ticker)
        );
        const tickers = Object.keys(signals).filter(t => !watchlistTickers.has(t));

        if (!tickers.length) {
            showEmpty("signal-board-empty", true);
            grid.innerHTML = "";
            return;
        }

        grid.innerHTML = tickers.map(ticker => {
            const s = signals[ticker];
            const action = (s.action || "hold").toLowerCase();
            const conf = Math.max(0, Math.min(100, s.confidence ?? 50));
            const bg = actionColor(action);
            const alpha = 0.25 + (conf / 100) * 0.55;
            return `<div class="signal-board-tile" role="listitem" title="${escapeHtml(ticker)} · ${escapeHtml(action)} · ${conf}% confidence" style="--sig-color:${bg};background: color-mix(in srgb, ${bg} ${Math.round(alpha * 100)}%, var(--surface))">
                <span class="signal-board-ticker">${escapeHtml(ticker)}</span>
                <span class="signal-board-action">${escapeHtml(action)}</span>
                <span class="signal-board-conf" style="--sig-conf:${conf}%" aria-hidden="true"></span>
            </div>`;
        }).join("");
    }

    async function loadSignalBoard() {
        await loadSignalsBundle();
    }

    function renderPortfolioOutlook(data) {
        const root = $("portfolio-outlook");
        const bar = $("verdict-mix-bar");
        const legend = $("verdict-mix-legend");
        const stats = $("verdict-mix-stats");
        const quipEl = $("portfolio-outlook-quip");
        if (!root || !bar || !legend || !stats) return;

        const signals = data?.signals || {};
        const health = data?.portfolio_health || {};
        const buckets = { add: 0, hold: 0, trim: 0, unknown: 0 };
        let confWeighted = 0;
        let weightTotal = 0;

        // Pre-build allocation Map for O(1) lookups inside the forEach below.
        const allocByTicker = new Map();
        (latestHoldings || []).forEach(h => {
            if (!h.is_watchlist) allocByTicker.set(h.ticker, Number(h.allocation_pct) || 0);
        });

        Object.entries(signals).forEach(([ticker, sig]) => {
            const w = allocByTicker.get(ticker) || 0;
            if (w <= 0) return;
            const bucket = normSignalBucket(sig.action);
            buckets[bucket] += w;
            confWeighted += (sig.confidence ?? 50) * w;
            weightTotal += w;
        });

        if (weightTotal <= 0) {
            root.hidden = true;
            showEmpty("portfolio-outlook-empty", true);
            return;
        }

        root.hidden = false;
        showEmpty("portfolio-outlook-empty", false);

        const segments = [
            { key: "add", color: token("--accent-green", "#30d158") },
            { key: "hold", color: token("--accent-cyan", "#64d2ff") },
            { key: "trim", color: token("--accent-red", "#ff453a") },
            { key: "unknown", color: token("--text-tertiary", "#8e8e93") },
        ].filter(s => buckets[s.key] > 0.05);

        bar.innerHTML = segments.map(s => {
            const pct = buckets[s.key];
            return `<div class="verdict-mix-seg" style="width:${pct.toFixed(1)}%;background:${s.color}"
                         title="${verdictBucketLabel(s.key)}: ${pct.toFixed(1)}%"></div>`;
        }).join("");

        legend.innerHTML = segments.map(s => {
            const pct = buckets[s.key];
            return `<span class="verdict-mix-legend-item">
                <i class="verdict-mix-swatch" style="background:${s.color}"></i>
                ${verdictBucketLabel(s.key)} <strong>${pct.toFixed(1)}%</strong>
            </span>`;
        }).join("");

        const avgConf = Math.round(confWeighted / weightTotal);
        const dominant = (health.dominant_action || "hold").toUpperCase();
        const dominantColor = actionColor(health.dominant_action || "hold");
        const conc = concentrationPlain(health.concentration_band || "medium");

        stats.innerHTML = `
            <div class="verdict-mix-stat verdict-mix-stat--accent" style="--vm-accent:${dominantColor}">
                <span class="verdict-mix-stat-label">Overall tone</span>
                <span class="verdict-mix-stat-value verdict-mix-stat-value--accent">
                    <i class="verdict-mix-stat-dot" aria-hidden="true"></i>${escapeHtml(dominant)}
                </span>
            </div>
            <div class="verdict-mix-stat">
                <span class="verdict-mix-stat-label">Avg confidence</span>
                <span class="verdict-mix-stat-value">${avgConf}%</span>
            </div>
            <div class="verdict-mix-stat">
                <span class="verdict-mix-stat-label">Concentration</span>
                <span class="verdict-mix-stat-value">${escapeHtml(conc)}</span>
            </div>`;

        if (quipEl) {
            const quip = health.quip?.trim();
            quipEl.textContent = quip || "";
            quipEl.hidden = !quip;
        }
    }

    function tapeItemHtml(m) {
        const up = (m.day_change_pct ?? 0) >= 0;
        const cls = up ? "tape-chg-up" : "tape-chg-down";
        const sign = up ? "+" : "";
        const price = typeof _marketPrice === "function" ? _marketPrice(m.price) : m.price;
        return `<span class="markets-tape-item">
            <span class="tape-flag">${m.flag || ""}</span>
            <span class="tape-name">${escapeHtml(m.name)}</span>
            <span class="tape-price">${price}</span>
            <span class="${cls}">${sign}${(m.day_change_pct ?? 0).toFixed(2)}%</span>
        </span>`;
    }

    let _tapeListenersBound = false;

    function refreshMarketsTape(markets) {
        _cachedMarkets = markets || [];
        const track = $("markets-tape-track");
        if (!track) return;

        if (!_cachedMarkets.length) {
            track.innerHTML = `<span class="markets-tape-item" style="color:var(--text-tertiary)">Market data unavailable</span>`;
            return;
        }

        const items = _cachedMarkets.map(tapeItemHtml).join("");
        track.innerHTML = items + items;
        track.classList.toggle("is-animating", !prefersReducedMotion() && !_tapePaused && _tapeInView);

        const wrap = $("markets-tape-wrap");
        if (wrap && !_tapeListenersBound) {
            _tapeListenersBound = true;
            wrap.addEventListener("mouseenter", () => {
                _tapePaused = true;
                track.classList.add("is-paused");
                track.classList.remove("is-animating");
            });
            wrap.addEventListener("mouseleave", () => {
                _tapePaused = false;
                if (!prefersReducedMotion() && _tapeInView) {
                    track.classList.remove("is-paused");
                    track.classList.add("is-animating");
                }
            });
            wrap.addEventListener("focusin", () => { _tapePaused = true; track.classList.add("is-paused"); });
            wrap.addEventListener("focusout", () => { _tapePaused = false; });
        }
    }

    function corrBarColor(correlation) {
        const c = Number(correlation) || 0;
        if (c >= 0.4) return token("--accent-red", "#ff453a");
        if (c < 0) return token("--accent-blue", "#0a84ff");
        return token("--text-tertiary", "#8e8e93");
    }

    function renderMarketsPortfolioGrid(markets) {
        const grid = $("markets-portfolio-grid");
        if (!grid) return;

        if (!markets?.length) {
            grid.innerHTML = `<p class="markets-portfolio-empty">Portfolio market context unavailable</p>`;
            return;
        }

        grid.innerHTML = markets.map(m => {
            const up = (m.day_change_pct ?? 0) >= 0;
            const chgCls = up ? "text-success" : "text-danger";
            const sign = up ? "+" : "";
            const price = typeof _marketPrice === "function" ? _marketPrice(m.price) : m.price;
            const corr = Number(m.correlation) || 0;
            const corrPct = Math.round(Math.abs(corr) * 100);
            const barW = Math.max(4, corrPct);
            const barColor = corrBarColor(corr);
            const geo = Number(m.geo_weight_pct) || 0;
            const geoLine = geo >= 5
                ? `<span class="markets-portfolio-geo">~${geo}% look-through exposure</span>`
                : "";

            return `<article class="markets-portfolio-tile">
                <div class="markets-portfolio-tile-head">
                    <span class="markets-portfolio-flag">${m.flag || ""}</span>
                    <span class="markets-portfolio-name">${escapeHtml(m.name)}</span>
                    <span class="markets-portfolio-chg ${chgCls}">${sign}${(m.day_change_pct ?? 0).toFixed(2)}%</span>
                </div>
                <div class="markets-portfolio-price">${price}</div>
                <div class="markets-portfolio-corr-row">
                    <span class="markets-portfolio-corr-label">Moves with you</span>
                    <div class="markets-portfolio-corr-track" aria-hidden="true">
                        <div class="markets-portfolio-corr-fill" style="width:${barW}%;background:${barColor}"></div>
                    </div>
                    <span class="markets-portfolio-corr-val">${corr >= 0 ? "" : "−"}${corrPct}%</span>
                </div>
                ${geoLine}
                <p class="markets-portfolio-insight">${escapeHtml(m.insight || "")}</p>
            </article>`;
        }).join("");
    }

    function renderMarketsContext(data) {
        const summary = $("markets-portfolio-summary");
        const markets = data?.markets || [];

        if (summary) {
            if (data?.summary) {
                summary.textContent = data.summary;
                summary.hidden = false;
            } else {
                summary.hidden = true;
            }
        }

        refreshMarketsTape(markets);
        renderMarketsPortfolioGrid(markets);
    }

    async function refreshMarketsFromApi() {
        try {
            const res = await fetch("/api/portfolio/market-context");
            if (!res.ok) return;
            const data = await res.json();
            renderMarketsContext(data);
        } catch (err) {
            console.warn("Markets context failed:", err);
        }
    }

    function setupTapeObserver() {
        const wrap = $("markets-tape-wrap");
        if (!wrap || typeof IntersectionObserver === "undefined") return;
        const obs = new IntersectionObserver(entries => {
            _tapeInView = entries.some(e => e.isIntersecting);
            const track = $("markets-tape-track");
            if (!track) return;
            if (_tapeInView && !prefersReducedMotion() && !_tapePaused) {
                track.classList.add("is-animating");
            } else {
                track.classList.remove("is-animating");
            }
        }, { threshold: 0.1 });
        obs.observe(wrap);
    }

    function resizeCharts() {
        [riskRewardChart, drawdownChart, treemapChart, benchmarkChart, rollingVolChart, macroAlignmentChart].forEach(c => {
            c?.resize?.();
            c?.update?.("none");
        });
        if (_correlationData) drawCorrelationHeatmap();
        if (_gaugeReady) drawConcentrationGauge(_lastHhi);
        if (_betaGaugeReady) drawBetaGauge(_lastBeta);
        if (_benchmarkData) renderBenchmarkChart(_benchmarkData);
    }

    function onThemeChange() {
        updateChartChrome(riskRewardChart);
        if (_correlationData) drawCorrelationHeatmap();
        updateChartChrome(drawdownChart);
        updateChartChrome(treemapChart);
        updateChartChrome(benchmarkChart);
        updateChartChrome(rollingVolChart);
        updateChartChrome(macroAlignmentChart);
        if (rendered.has("risk")) {
            loadConcentrationGauge();
            loadBetaGauge();
        }
        if (rendered.has("exposure")) {
            loadGeoExposure();
            loadSectorTilt();
            if (treemapChart) treemapChart.update("none");
        }
        if (rendered.has("signals")) {
            loadContributionChart();
            loadConfidenceSpectrum();
        }
        if (rendered.has("performance")) {
            loadBenchmarkChart();
        }
        if (rendered.has("markets")) {
            loadMacroAlignment();
        }
    }

    function onIntelligenceModeChanged() {
        if (widgetInsightMode() === "ai") {
            _moduleInsightsCache.ai = null;
            applyWidgetInsights();
            void loadWidgetInsights(false);
            void loadAiWidgetInsights(false);
            return;
        }
        _moduleInsightsCache.ai = null;
        applyWidgetInsights();
        void loadWidgetInsights(true);
    }

    function onRefresh() {
        _portfolioExposureCache = null;
        loadWidgetInsights(true);
        if (activePane === "performance" && rendered.has("performance")) loadPerformancePane();
        if (activePane === "risk" && rendered.has("risk")) loadRiskPane();
        if (activePane === "exposure" && rendered.has("exposure")) loadExposurePane();
        if (activePane === "signals" && rendered.has("signals")) loadSignalsPane();
        if (activePane === "markets" || rendered.has("markets")) loadMarketsPane();
    }

    function onAnalyticsZoneEnter() {
        loadWidgetInsights();
        requestAnimationFrame(resizeCharts);
        if (!rendered.has(activePane)) {
            rendered.add(activePane);
            loadPane(activePane);
        } else if (activePane === "performance") {
            requestAnimationFrame(() => {
                benchmarkChart?.resize();
                benchmarkChart?.update("none");
            });
        } else if (activePane === "markets") {
            refreshMarketsTape(_cachedMarkets);
        }
    }

    function init() {
        registerPlugins();
        initSubTabs();
        setupTapeObserver();
        window.addEventListener("resize", () => {
            clearTimeout(init._resizeTimer);
            init._resizeTimer = setTimeout(resizeCharts, 150);
        }, { passive: true });
    }

    return {
        init,
        setSubPane,
        onRefresh,
        onThemeChange,
        onAnalyticsZoneEnter,
        onIntelligenceModeChanged,
        loadWidgetInsights,
        loadAiWidgetInsights,
        refreshMarketsTape,
        renderMarketsContext,
        updateSectorTiltForTicker,
    };
})();

window.AnalyticsCharts = AnalyticsCharts;
