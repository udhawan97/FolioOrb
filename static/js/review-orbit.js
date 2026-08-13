/**
 * Review Orbit
 * One accessible workspace for review attention, provenance, reports,
 * research comparison, thesis cadence, and verified local backups.
 */
window.ReviewOrbit = (() => {
    const state = {
        open: false,
        tab: "inbox",
        previousFocus: null,
        background: new Map(),
        loaded: new Set(),
        inbox: null,
        trust: null,
        report: null,
        reportPeriod: "month",
        watchlist: null,
        plan: null,
        overview: null,
        backups: null,
        thesisId: null,
        thesisReturnFocus: null,
        restoreName: null,
        restoreReturnFocus: null,
    };

    const $ = id => document.getElementById(id);
    const orbit = () => $("review-orbit");
    const live = message => {
        const region = $("review-orbit-live");
        if (region) region.textContent = message;
    };
    const money = value => value === null || value === undefined
        ? "Unavailable"
        : new Intl.NumberFormat("en-US", {
            style: "currency", currency: "USD", maximumFractionDigits: 0,
        }).format(Number(value));
    const number = value => value === null || value === undefined
        ? "Unavailable"
        : new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(Number(value));
    const pct = value => value === null || value === undefined
        ? "Unavailable"
        : `${number(value)}%`;
    const bpsPct = value => value === null || value === undefined
        ? "Not set"
        : `${number(Number(value) / 100)}%`;
    const preciseMoney = (value, digits = 2) => value === null || value === undefined
        ? "Unavailable"
        : new Intl.NumberFormat("en-US", {
            style: "currency", currency: "USD",
            minimumFractionDigits: digits, maximumFractionDigits: digits,
        }).format(Number(value));
    const dateTime = value => {
        if (!value) return "Unknown time";
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime())
            ? String(value)
            : parsed.toLocaleString(undefined, {
                year: "numeric", month: "short", day: "numeric",
                hour: "numeric", minute: "2-digit", timeZoneName: "short",
            });
    };
    const bytes = value => {
        const amount = Number(value || 0);
        if (amount < 1024) return `${amount} B`;
        if (amount < 1024 ** 2) return `${(amount / 1024).toFixed(1)} KB`;
        return `${(amount / 1024 ** 2).toFixed(1)} MB`;
    };

    function setLoading(id, label = "Loading local review data…") {
        const target = $(id);
        if (target) target.innerHTML = html`<div class="review-loading">${label}</div>`;
    }

    function setError(id, error) {
        const target = $(id);
        if (!target) return;
        target.innerHTML = html`
            <div class="review-empty">
                ${apiErrorMessage(error, "This review surface is temporarily unavailable.")}
            </div>`;
    }

    function focusable() {
        const root = orbit();
        if (!root) return [];
        return Array.from(root.querySelectorAll(
            "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), " +
            "textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
        )).filter(element => !element.hidden && element.getClientRects().length > 0);
    }

    function onKeydown(event) {
        if (!state.open) return;
        if (event.key === "Escape") {
            event.preventDefault();
            close();
            return;
        }
        if (event.key !== "Tab") return;
        const items = focusable();
        if (!items.length) {
            event.preventDefault();
            orbit()?.focus();
            return;
        }
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        } else if (!orbit()?.contains(document.activeElement)) {
            event.preventDefault();
            first.focus();
        }
    }

    function setBackgroundInert(inert) {
        if (inert) {
            document.querySelectorAll("body > *").forEach(element => {
                if (element === orbit() || element.tagName === "SCRIPT") return;
                state.background.set(element, element.inert);
                element.inert = true;
            });
            return;
        }
        state.background.forEach((wasInert, element) => { element.inert = wasInert; });
        state.background.clear();
    }

    async function open(tab = state.tab) {
        const root = orbit();
        if (!root) return;
        if (!state.open) {
            state.open = true;
            state.previousFocus = document.activeElement;
            root.hidden = false;
            root.setAttribute("aria-hidden", "false");
            document.body.classList.add("review-orbit-open");
            $("review-orbit-trigger")?.setAttribute("aria-expanded", "true");
            setBackgroundInert(true);
            document.addEventListener("keydown", onKeydown, true);
            requestAnimationFrame(() => root.querySelector("[data-review-close]")?.focus());
        }
        activateTab(tab);
        if (!state.loaded.has("inbox")) loadInbox();
        if (!state.loaded.has("trust")) loadTrust();
    }

    function close() {
        const root = orbit();
        if (!root || !state.open) return false;
        state.open = false;
        root.hidden = true;
        root.setAttribute("aria-hidden", "true");
        document.body.classList.remove("review-orbit-open");
        $("review-orbit-trigger")?.setAttribute("aria-expanded", "false");
        document.removeEventListener("keydown", onKeydown, true);
        setBackgroundInert(false);
        const previous = state.previousFocus;
        state.previousFocus = null;
        if (previous?.focus) requestAnimationFrame(() => previous.focus());
        return true;
    }

    function activateTab(tab) {
        const button = document.querySelector(`[data-review-tab="${CSS.escape(tab)}"]`);
        const pane = document.querySelector(`[data-review-pane="${CSS.escape(tab)}"]`);
        if (!button || !pane) return;
        state.tab = tab;
        document.querySelectorAll("[data-review-tab]").forEach(item => {
            const selected = item === button;
            item.setAttribute("aria-selected", String(selected));
            item.tabIndex = selected ? 0 : -1;
        });
        document.querySelectorAll("[data-review-pane]").forEach(item => {
            item.hidden = item !== pane;
        });
        loadTab(tab);
    }

    function loadTab(tab) {
        if (state.loaded.has(tab)) return;
        if (tab === "inbox") loadInbox();
        if (tab === "trust") loadTrust();
        if (tab === "report") loadReport();
        if (tab === "compare") loadWatchlist();
        if (tab === "plan") loadPlan();
        if (tab === "records") loadRecords();
        if (tab === "backups") loadBackups();
    }

    function renderInbox() {
        const data = state.inbox;
        if (!data) return;
        const badge = $("review-inbox-badge");
        if (badge) {
            badge.hidden = data.count === 0;
            badge.textContent = data.count > 99 ? "99+" : String(data.count);
            badge.setAttribute("aria-label", `${data.count} review items`);
        }
        const tabCount = $("review-tab-count");
        if (tabCount) tabCount.textContent = data.count ? `· ${data.count}` : "";
        const count = $("review-orbit-count");
        if (count) count.textContent = data.count ? `${data.count} items` : "Clear";
        const asof = $("review-orbit-asof");
        if (asof) asof.textContent = `Review as of ${dateTime(data.generated_at)}`;

        $("review-inbox-summary").innerHTML = ["urgent", "attention", "quiet"].map(tone => html`
            <div class="review-summary-cell" data-tone="${tone}">
                <strong>${data.counts[tone] || 0}</strong>
                <span>${tone === "urgent" ? "Data gaps" : tone === "attention" ? "Needs review" : "On the radar"}</span>
            </div>`).join("");

        const target = $("review-inbox-list");
        if (!data.items.length) {
            target.innerHTML = html`<div class="review-empty">Nothing needs attention right now. Your review orbit is clear.</div>`;
            return;
        }
        target.innerHTML = data.items.map(item => html`
            <article class="review-inbox-item" data-tone="${item.tone}">
                <span class="review-inbox-dot" aria-hidden="true"></span>
                <div class="review-inbox-copy">
                    <strong>${item.title}</strong>
                    <span>${item.detail}</span>
                </div>
                <button class="review-inbox-action" type="button"
                        data-review-action="${item.action.kind}"
                        data-review-ticker="${item.ticker || ""}"
                        data-review-holding="${item.action.holding_id || ""}">
                    ${item.action.label}
                </button>
            </article>`).join("");
    }

    async function loadInbox(force = false) {
        if (!force && state.loaded.has("inbox")) return;
        setLoading("review-inbox-list");
        try {
            state.inbox = await PortfolioWorkspace.json("/api/review/inbox");
            state.loaded.add("inbox");
            renderInbox();
        } catch (error) {
            setError("review-inbox-list", error);
        }
    }

    function renderTrust() {
        const data = state.trust;
        if (!data) return;
        $("review-orbit-mark")?.setAttribute("data-quality", data.overall_quality);
        $("review-trust-principle").textContent = data.principle;
        $("review-trust-grid").innerHTML = data.areas.map(area => {
            const coverage = area.expected === null || area.expected === undefined
                ? `${area.covered} local records`
                : `${area.covered} of ${area.expected} covered`;
            const missing = area.missing?.length ? ` Missing: ${area.missing.join(", ")}.` : "";
            return html`
                <article class="review-trust-card">
                    <div class="review-trust-card-head">
                        <h4>${area.label}</h4>
                        <span class="review-quality" data-quality="${area.quality}">${area.quality.replace("_", " ")}</span>
                    </div>
                    <p>${coverage}.${missing}</p>
                    <p class="review-trust-source">${area.source}${area.latest ? ` · Latest ${area.latest}` : ""}</p>
                    ${area.caveat ? html`<p class="review-trust-source">${area.caveat}</p>` : ""}
                </article>`;
        }).join("");
    }

    async function loadTrust(force = false) {
        if (!force && state.loaded.has("trust")) return;
        setLoading("review-trust-grid", "Checking coverage and source freshness…");
        try {
            state.trust = await PortfolioWorkspace.json("/api/review/trust");
            state.loaded.add("trust");
            renderTrust();
        } catch (error) {
            setError("review-trust-grid", error);
        }
    }

    function renderReport() {
        const data = state.report;
        if (!data) return;
        const current = data.current;
        const activity = data.period_activity;
        $("review-report-summary").innerHTML = html`
            <article class="review-report-card"><span>Current value</span><strong>${money(current.total_value)}</strong></article>
            <article class="review-report-card"><span>Total return</span><strong>${money(current.total_return)} · ${pct(current.total_return_pct)}</strong></article>
            <article class="review-report-card"><span>Value change since ${data.observed_start || "no stored start"}</span><strong>${money(activity.value_change)}</strong></article>
            <article class="review-report-card"><span>Realized this period</span><strong>${money(activity.realized_gain)}</strong></article>
            <article class="review-report-card"><span>Stored snapshots</span><strong>${data.snapshot_count}</strong></article>
            <article class="review-report-card"><span>History coverage</span><strong>${data.data_quality.history}</strong></article>
            <article class="review-report-card"><span>Theses needing attention</span><strong>${data.thesis_attention.length}</strong></article>
            <article class="review-report-card"><span>Price coverage</span><strong>${data.data_quality.valuation}</strong></article>`;
    }

    async function loadReport(force = false) {
        if (!force && state.loaded.has("report")) return;
        setLoading("review-report-summary", "Building the review pack from stored history…");
        try {
            state.report = await PortfolioWorkspace.json(`/api/review/report?period=${encodeURIComponent(state.reportPeriod)}`);
            state.loaded.add("report");
            renderReport();
        } catch (error) {
            setError("review-report-summary", error);
        }
    }

    function browserSaveBinary(filename, content, mediaType) {
        const blob = new Blob([content], { type: mediaType });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
    }

    async function exportReport(format) {
        const endpoint = `/api/review/report/export?period=${encodeURIComponent(state.reportPeriod)}&format=${encodeURIComponent(format)}`;
        try {
            const response = await PortfolioWorkspace.response(endpoint);
            const result = await LocalTextExport.saveResponse(response, {
                fallbackFilename: `folioorb-${state.reportPeriod}-review.${format}`,
                mediaType: format === "csv"
                    ? "text/csv;charset=utf-8"
                    : "text/html;charset=utf-8",
            });
            if (result.status === "saved" && result.path) {
                showToast(`Saved ${result.filename}`, "success");
            }
        } catch (error) {
            showToast(apiErrorMessage(error, "Review export failed"), "danger");
        }
    }

    function selectedWatchlist() {
        return Array.from(document.querySelectorAll(".review-watchlist-pick input:checked"));
    }

    function syncCompareButton() {
        const selected = selectedWatchlist();
        const button = $("review-compare-run");
        if (button) button.disabled = selected.length < 2 || selected.length > 3;
    }

    function renderWatchlist() {
        const items = state.watchlist?.items || [];
        const target = $("review-watchlist-picks");
        if (!items.length) {
            target.innerHTML = html`<div class="review-empty">Add at least two research-mode holdings in Manage to compare them here.</div>`;
            return;
        }
        target.innerHTML = items.map(item => html`
            <label class="review-watchlist-pick">
                <input type="checkbox" value="${item.ticker}" data-kind="${item.security_type}">
                <strong>${item.ticker}</strong>
                <span>${item.name}</span>
                <span class="review-watchlist-type">${item.security_type}</span>
            </label>`).join("");
        syncCompareButton();
    }

    async function loadWatchlist(force = false) {
        if (!force && state.loaded.has("compare")) return;
        setLoading("review-watchlist-picks", "Loading research-mode holdings…");
        try {
            state.watchlist = await PortfolioWorkspace.json("/api/review/watchlist");
            state.loaded.add("compare");
            renderWatchlist();
        } catch (error) {
            setError("review-watchlist-picks", error);
        }
    }

    function displayMetric(key, value) {
        if (value === null || value === undefined || value === "") return "Unavailable";
        if (key === "market_cap" || key === "aum") {
            return new Intl.NumberFormat("en-US", {
                notation: "compact", maximumFractionDigits: 1,
            }).format(Number(value));
        }
        if (["revenue_growth", "gross_margin", "operating_margin", "dividend_yield", "expense_ratio"].includes(key)) {
            return pct(Number(value) * 100);
        }
        if (key === "top_holdings") {
            return value.length ? value.map(item => item.ticker).join(", ") : "Unavailable";
        }
        return number(value);
    }

    function metricLabel(key) {
        return key.replaceAll("_", " ").replace(/\b\w/g, char => char.toUpperCase());
    }

    function renderComparison(data) {
        const target = $("review-compare-results");
        target.innerHTML = data.items.map(item => html`
            <article class="review-compare-card">
                <header class="review-compare-card-head">
                    <h4>${item.ticker}</h4>
                    <span>${item.name} · ${money(item.current_price)} · ${pct(item.day_change_pct)} today</span>
                </header>
                <dl class="review-compare-metrics">
                    ${Object.entries(item.metrics).map(([key, value]) => html`
                        <div><dt>${metricLabel(key)}</dt><dd>${displayMetric(key, value)}</dd></div>
                    `)}
                    <div><dt>Thesis</dt><dd>${item.thesis.status.replace("_", " ")}</dd></div>
                </dl>
            </article>`).join("");
        if (data.overlap) {
            target.insertAdjacentHTML("beforeend", String(html`
                <p class="review-overlap-note">
                    Published-holdings overlap: <strong>${pct(data.overlap.overlap_pct)}</strong>
                    across ${data.overlap.shared_count} shared names. ${data.overlap.caveat}
                </p>`));
        }
    }

    async function runCompare() {
        const selected = selectedWatchlist();
        if (selected.length < 2 || selected.length > 3) return;
        const kinds = new Set(selected.map(input => input.dataset.kind));
        if (kinds.size !== 1 || !["STOCK", "ETF"].includes(selected[0].dataset.kind)) {
            showToast("Compare stocks with stocks or ETFs with ETFs.", "warning");
            return;
        }
        setLoading("review-compare-results", "Building a type-aware comparison…");
        try {
            const tickers = selected.map(input => input.value).join(",");
            const data = await PortfolioWorkspace.json(`/api/review/compare?tickers=${encodeURIComponent(tickers)}`);
            renderComparison(data);
        } catch (error) {
            setError("review-compare-results", error);
        }
    }

    function qualityText(value) {
        return String(value || "unavailable").replaceAll("_", " ");
    }

    function renderBookPulse() {
        const data = state.overview;
        if (!data) return;
        const target = $("review-book-pulse");
        const rows = data.items.map(item => html`
            <tr>
                <th scope="row">${item.name}</th>
                <td>${item.known_value_usd === null ? "Unavailable" : money(item.known_value_usd)}</td>
                <td><span class="review-quality" data-quality="${item.data_quality}">${qualityText(item.data_quality)}</span></td>
                <td>${item.error
                    ? "This book could not be valued; other books remain visible."
                    : item.missing_tickers.length || item.foreign_currency_tickers.length
                        ? `Missing ${item.missing_tickers.join(", ") || "none"}; foreign-priced ${item.foreign_currency_tickers.join(", ") || "none"}`
                        : item.data_quality === "empty" ? "No owned positions" : "Available USD coverage"}</td>
            </tr>`);
        target.innerHTML = html`
            <div class="review-book-pulse-head">
                <div><span>All portfolios · known USD only</span><strong>${money(data.known_value_usd)}</strong></div>
                <span class="review-quality" data-quality="${data.data_quality}">${qualityText(data.data_quality)}</span>
            </div>
            <div class="review-table-scroll">
                <table class="review-plan-table">
                    <caption>Known USD value and quote coverage for every saved portfolio</caption>
                    <thead><tr><th>Portfolio</th><th>Known value</th><th>Coverage</th><th>What is excluded</th></tr></thead>
                    <tbody>${rows.length ? rows : html`<tr><td colspan="4">No saved portfolios.</td></tr>`}</tbody>
                </table>
            </div>
            <p class="review-table-note">Foreign prices are not converted. No combined performance percentage is shown.</p>`;
    }

    function renderTargetPlan() {
        const data = state.plan;
        if (!data) return;
        const select = $("review-rehearsal-holding");
        const previousSelection = select?.value;
        const save = $("review-target-save");
        const run = $("review-rehearsal-run");
        if (!data.items.length) {
            $("review-course-summary").innerHTML = html`
                <div class="review-empty">Add an owned position before setting a target course. Research-only and zero-share rows stay outside the plan.</div>`;
            $("review-target-table").innerHTML = "";
            if (select) select.innerHTML = '<option value="">No eligible positions</option>';
            if (save) save.disabled = true;
            if (run) run.disabled = true;
            return;
        }
        if (save) save.disabled = false;
        if (run) run.disabled = false;

        const driftItems = data.items.filter(item => item.drift_bps !== null);
        const focal = driftItems.sort((a, b) => Math.abs(b.drift_bps) - Math.abs(a.drift_bps))[0]
            || data.items[0];
        const ringAvailable = data.drift_available && focal.actual_weight_bps !== null
            && focal.target_weight_bps !== null;
        const ringLabel = ringAvailable
            ? `${focal.ticker}: actual ${bpsPct(focal.actual_weight_bps)}, target ${bpsPct(focal.target_weight_bps)}, ${Math.abs(focal.drift_bps)} basis points ${focal.drift_direction}`
            : data.complete
                ? `Drift unavailable because valuation coverage is ${qualityText(data.valuation_quality)}`
                : `Target course incomplete; ${Math.max(data.remaining_bps, 0)} basis points remain`;
        $("review-course-summary").innerHTML = html`
            <div class="review-course-summary">
                <div class="review-course-ring ${ringAvailable ? "" : "is-partial"}"
                     role="img" aria-label="${ringLabel}"
                     style="--target-angle:${Number(focal.target_weight_bps || 0) / 10000 * 360}deg;--actual-angle:${Number(focal.actual_weight_bps || 0) / 10000 * 360}deg">
                    <span><strong>${ringAvailable ? focal.ticker : data.complete ? "Partial" : "Draft"}</strong><small>${ringAvailable ? `${focal.drift_bps > 0 ? "+" : ""}${focal.drift_bps} bps` : `${number(data.target_total_bps)} / 10,000`}</small></span>
                </div>
                <div>
                    <p class="review-eyebrow">Target course</p>
                    <h4>${data.complete ? "Course saved" : "Finish the target mix"}</h4>
                    <p>${ringLabel}.</p>
                    <div class="review-course-legend"><span data-kind="actual">Actual</span><span data-kind="target">Target</span></div>
                </div>
            </div>`;
        const tableRows = data.items.map(item => html`
            <tr>
                <th scope="row">${item.ticker}</th>
                <td>${bpsPct(item.actual_weight_bps)}</td>
                <td><label><span class="visually-hidden">${item.ticker} target basis points</span><input class="review-target-input" type="number" min="0" max="10000" step="1" inputmode="numeric" data-holding-id="${item.holding_id}" value="${item.target_weight_bps ?? ""}" placeholder="bps"></label></td>
                <td>${item.drift_bps === null ? "Unavailable" : `${item.drift_bps > 0 ? "+" : ""}${item.drift_bps} bps · ${qualityText(item.drift_direction)}`}</td>
            </tr>`);
        $("review-target-table").innerHTML = html`
            <div class="review-table-scroll">
                <table class="review-plan-table">
                    <caption>Saved target, current allocation, and descriptive drift by held position</caption>
                    <thead><tr><th>Position</th><th>Actual</th><th>Target (bps)</th><th>Drift</th></tr></thead>
                    <tbody>${tableRows}</tbody>
                    <tfoot><tr><th scope="row">Target total</th><td></td><td>${number(data.target_total_bps)} / 10,000</td><td>${data.complete ? "Complete" : `${number(data.remaining_bps)} bps remaining`}</td></tr></tfoot>
                </table>
            </div>`;
        if (select) {
            select.innerHTML = data.items.map(item => html`
                <option value="${item.holding_id}">${item.ticker}</option>`).join("");
            if (data.items.some(item => String(item.holding_id) === previousSelection)) {
                select.value = previousSelection;
            }
        }
    }

    async function loadPlan(force = false) {
        if (!force && state.loaded.has("plan")) return;
        setLoading("review-book-pulse", "Valuing each saved portfolio independently…");
        setLoading("review-course-summary", "Loading target course and available USD quotes…");
        $("review-target-table").innerHTML = "";
        const [planResult, overviewResult] = await Promise.allSettled([
            PortfolioWorkspace.json("/api/review/plan"),
            PortfolioWorkspace.json("/api/review/overview"),
        ]);
        if (planResult.status === "fulfilled") {
            state.plan = planResult.value;
            renderTargetPlan();
        } else {
            setError("review-course-summary", planResult.reason);
        }
        if (overviewResult.status === "fulfilled") {
            state.overview = overviewResult.value;
            renderBookPulse();
        } else {
            setError("review-book-pulse", overviewResult.reason);
        }
        state.loaded.add("plan");
    }

    async function saveTargets(event) {
        event.preventDefault();
        const status = $("review-target-status");
        const items = Array.from(document.querySelectorAll(".review-target-input")).map(input => ({
            holding_id: Number(input.dataset.holdingId),
            target_weight_bps: input.value === "" ? null : Number(input.value),
        }));
        status.textContent = "Saving target course locally…";
        try {
            await PortfolioWorkspace.json("/api/review/plan/targets", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ items }),
            });
            state.loaded.delete("plan");
            await loadPlan(true);
            status.textContent = "Target course saved. No trade was placed.";
            live("Target course saved locally; no trade was placed.");
        } catch (error) {
            status.textContent = apiErrorMessage(error, "Could not save target weights.");
        }
    }

    function renderRehearsal(data) {
        const allocation = data.allocation_available
            ? html`<div><span>Projected allocation</span><strong>${pct(data.projected_selected_allocation_pct)}</strong></div><div><span>Largest position</span><strong>${pct(data.projected_largest_position_pct)}</strong></div>`
            : html`<p class="review-rehearsal-partial">Projected allocation is unavailable because one or more required USD quotes are missing or foreign-priced.</p>`;
        $("review-rehearsal-result").innerHTML = html`
            <div class="review-rehearsal-ticket">
                <header><span>${data.ticker} · available USD quote</span><strong>${preciseMoney(data.available_quote_usd)}</strong></header>
                <div class="review-rehearsal-metrics">
                    <div><span>Fractional shares added</span><strong>${number(data.buy_shares)}</strong></div>
                    <div><span>Projected shares</span><strong>${number(data.projected_shares)}</strong></div>
                    <div><span>Projected average cost</span><strong>${preciseMoney(data.projected_avg_cost_usd, 4)}</strong></div>
                    ${allocation}
                </div>
                <p>Fully spends ${preciseMoney(data.cash_usd)}. Quote freshness is unknown. Fees and taxes are excluded. Nothing was written or ordered.</p>
            </div>`;
    }

    async function runRehearsal(event) {
        event.preventDefault();
        setLoading("review-rehearsal-result", "Rehearsing in memory — no portfolio writes…");
        try {
            const data = await PortfolioWorkspace.json("/api/review/plan/rehearsal", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    holding_id: Number($("review-rehearsal-holding").value),
                    cash_usd: $("review-rehearsal-cash").value,
                }),
            });
            renderRehearsal(data);
            live(`Buy rehearsal complete for ${data.ticker}; nothing was written or ordered.`);
        } catch (error) {
            setError("review-rehearsal-result", error);
        }
    }

    function loadRecords() {
        if (state.loaded.has("records")) return;
        const year = $("review-recap-year");
        if (year && !year.value) {
            year.max = String(new Date().getUTCFullYear());
            year.value = year.max;
        }
        state.loaded.add("records");
    }

    async function saveRecap(event) {
        event.preventDefault();
        const status = $("review-records-status");
        const year = $("review-recap-year").value;
        status.textContent = "Building the average-cost recap from stored sale facts…";
        try {
            const response = await PortfolioWorkspace.response(`/api/review/records/realized.csv?year=${encodeURIComponent(year)}`);
            const result = await LocalTextExport.saveResponse(response, {
                fallbackFilename: `folioorb-average-cost-recap-${year}.csv`,
                mediaType: "text/csv;charset=utf-8",
            });
            status.textContent = result.status === "saved"
                ? `Saved ${result.filename}.`
                : "Save cancelled; no file was written.";
            live(status.textContent);
        } catch (error) {
            status.textContent = apiErrorMessage(
                error,
                "Average-cost recap export failed; no complete file was written.",
            );
        }
    }

    async function savePortableRecords() {
        const button = $("review-portable-export");
        const status = $("review-records-status");
        button.disabled = true;
        status.textContent = "Building one consistent, human-readable records ZIP…";
        try {
            const api = window.pywebview && window.pywebview.api;
            if (api && typeof api.export_portable_records === "function") {
                const result = await api.export_portable_records();
                status.textContent = result?.saved
                    ? "Portable records ZIP saved. Keep it somewhere private."
                    : result?.error
                        ? "Portable records export failed; no complete ZIP was written."
                        : "Save cancelled; no file was written.";
                live(status.textContent);
                return;
            }
            const response = await PortfolioWorkspace.response("/api/review/records/archive");
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            browserSaveBinary(
                "folioorb-portable-export.zip",
                await response.arrayBuffer(),
                "application/zip",
            );
            status.textContent = "Portable records ZIP saved. Keep it somewhere private.";
        } catch (error) {
            status.textContent = apiErrorMessage(error, "Portable records export failed.");
        } finally {
            button.disabled = false;
        }
    }

    function renderProtection() {
        const protection = state.backups?.protection;
        const target = $("review-protection-status");
        if (!protection || !target) return;
        const manual = protection.manual_freshness;
        const automatic = protection.automatic;
        const manualCopy = manual.status === "none"
            ? "No verified manual backup yet"
            : `${qualityText(manual.status)} · ${manual.age_days} day${manual.age_days === 1 ? "" : "s"} old`;
        const manualTime = manual.latest
            ? `Last verified ${dateTime(manual.latest.created_at)}`
            : "Create one before a major portfolio change";
        const auto = automatic.last_auto_backup;
        const autoCopy = !automatic.auto_backup_enabled
            ? "Off by default"
            : auto
                ? `${qualityText(auto.status)} · ${dateTime(auto.attempted_at_utc)}`
                : "On · first launch check pending";
        target.innerHTML = html`
            <article class="review-protection-card" data-status="${manual.status}">
                <div><p class="review-eyebrow">Manual-backup freshness</p><strong>${manualCopy}</strong><span>${manualTime}. Newer corrupt manual files are ignored.</span></div>
                <span class="review-quality" data-quality="${manual.status === "current" ? "complete" : manual.status === "none" || manual.status === "stale" ? "unavailable" : "partial"}">${manual.status}</span>
            </article>
            <article class="review-protection-card">
                <div><p class="review-eyebrow">Automatic local protection</p><strong>${autoCopy}</strong><span>Checked at launch, at most once per local day. Keeps seven verified auto snapshots only.</span></div>
                <button class="review-auto-switch" id="review-auto-switch" type="button" role="switch"
                        aria-checked="${automatic.auto_backup_enabled}"
                        aria-label="Automatic daily local backups">
                    <span aria-hidden="true"></span>
                </button>
            </article>
            <p class="review-protection-limit">Same-device protection only — copy an exported backup elsewhere for off-device recovery. Automatic snapshots never count as manual-backup freshness.</p>`;
    }

    function renderBackups() {
        const data = state.backups;
        renderProtection();
        const status = $("review-restore-status");
        const restore = data?.last_restore;
        if (status && restore) {
            status.hidden = false;
            status.textContent = restore.status === "restored"
                ? `Restored ${restore.name} successfully. A safety copy of the previous database was kept.`
                : `The restore of ${restore.name} failed before replacing the live database.`;
        } else if (status) {
            status.hidden = true;
        }
        const items = data?.items || [];
        const target = $("review-backup-list");
        if (!items.length) {
            target.innerHTML = html`<div class="review-empty">No vault snapshots yet. Create one before a major portfolio change.</div>`;
            return;
        }
        target.innerHTML = items.map(item => html`
            <article class="review-backup-row">
                <div>
                    <strong>${item.name}</strong>
                    <span>${dateTime(item.created_at)} · ${bytes(item.size_bytes)} · ${item.holding_count} holding rows · ${item.verified ? "verified" : "failed verification"}</span>
                </div>
                <div class="review-backup-actions">
                    <button type="button" class="review-secondary-btn" data-backup-export="${item.name}" ${item.verified ? "" : "disabled"}>Export</button>
                    <button type="button" class="review-danger-btn" data-backup-restore="${item.name}" ${item.verified ? "" : "disabled"}>Restore…</button>
                </div>
            </article>`).join("");
    }

    async function loadBackups(force = false) {
        if (!force && state.loaded.has("backups")) return;
        setLoading("review-backup-list", "Verifying the local vault…");
        try {
            state.backups = await PortfolioWorkspace.json("/api/review/backups");
            state.loaded.add("backups");
            renderBackups();
        } catch (error) {
            setError("review-backup-list", error);
        }
    }

    async function createBackup() {
        const button = $("review-backup-create");
        if (button) button.disabled = true;
        try {
            const item = await PortfolioWorkspace.json("/api/review/backups", { method: "POST" });
            showToast(`Verified backup ${item.name}`, "success");
            state.loaded.delete("backups");
            await loadBackups(true);
        } catch (error) {
            showToast(apiErrorMessage(error, "Backup failed; nothing was changed"), "danger");
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function toggleAutoBackup() {
        const current = Boolean(state.backups?.protection?.automatic?.auto_backup_enabled);
        const button = $("review-auto-switch");
        if (button) button.disabled = true;
        try {
            const protection = await PortfolioWorkspace.json("/api/review/backups/policy", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled: !current }),
            });
            state.backups.protection = protection;
            renderProtection();
            requestAnimationFrame(() => $("review-auto-switch")?.focus());
            live(`Automatic local backups ${!current ? "enabled" : "disabled"}.`);
        } catch (error) {
            showToast(apiErrorMessage(error, "Could not change automatic backup policy"), "danger");
            if (button) button.disabled = false;
        }
    }

    async function exportBackup(name) {
        try {
            const api = window.pywebview && window.pywebview.api;
            if (api && typeof api.export_backup === "function") {
                const result = await api.export_backup(name);
                if (result?.saved) showToast(`Saved ${name}`, "success");
                else if (result?.error) showToast("Backup export failed; no complete file was written.", "danger");
                return;
            }
            const anchor = document.createElement("a");
            anchor.href = `/api/review/backups/${encodeURIComponent(name)}/download`;
            anchor.download = name;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
        } catch (error) {
            showToast(apiErrorMessage(error, "Backup export failed"), "danger");
        }
    }

    function askRestore(name) {
        state.restoreName = name;
        state.restoreReturnFocus = document.activeElement;
        $("review-restore-title").textContent = `Restore ${name}?`;
        $("review-restore-confirm").hidden = false;
        requestAnimationFrame(() => $("review-restore-cancel")?.focus());
    }

    function cancelRestore() {
        const previous = state.restoreReturnFocus;
        state.restoreName = null;
        state.restoreReturnFocus = null;
        $("review-restore-confirm").hidden = true;
        requestAnimationFrame(() => {
            if (previous?.isConnected) previous.focus();
            else document.querySelector("[data-review-tab='backups']")?.focus();
        });
    }

    async function acceptRestore() {
        if (!state.restoreName) return;
        const name = state.restoreName;
        $("review-restore-accept").disabled = true;
        try {
            const result = await PortfolioWorkspace.json("/api/review/backups/restore", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
            });
            cancelRestore();
            live(result.message);
            showToast(result.message, "warning");
            state.loaded.delete("backups");
            if (!result.will_quit) await loadBackups(true);
        } catch (error) {
            showToast(apiErrorMessage(error, "Restore was not queued"), "danger");
        } finally {
            $("review-restore-accept").disabled = false;
        }
    }

    function openThesisEditor(holdingId) {
        const thesis = state.inbox?.theses?.find(item => item.holding_id === holdingId);
        if (!thesis) return;
        state.thesisId = holdingId;
        state.thesisReturnFocus = document.activeElement;
        $("review-thesis-title").textContent = `${thesis.ticker} thesis`;
        $("review-thesis-notes").value = thesis.notes || "";
        $("review-thesis-cadence").value = thesis.review_interval_days
            ? String(thesis.review_interval_days)
            : "";
        $("review-thesis-status").textContent = "";
        $("review-thesis-editor").hidden = false;
        requestAnimationFrame(() => $("review-thesis-notes")?.focus());
    }

    function closeThesisEditor() {
        const previous = state.thesisReturnFocus;
        state.thesisId = null;
        state.thesisReturnFocus = null;
        $("review-thesis-editor").hidden = true;
        requestAnimationFrame(() => {
            if (previous?.isConnected) previous.focus();
            else document.querySelector("[data-review-tab='inbox']")?.focus();
        });
    }

    async function saveThesis(event) {
        event.preventDefault();
        if (!state.thesisId) return;
        const status = $("review-thesis-status");
        status.textContent = "Saving locally…";
        const cadence = $("review-thesis-cadence").value;
        try {
            await PortfolioWorkspace.json(`/api/review/thesis/${state.thesisId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    notes: $("review-thesis-notes").value,
                    review_interval_days: cadence ? Number(cadence) : null,
                }),
            });
            status.textContent = "Saved and marked reviewed.";
            showToast("Thesis reviewed", "success");
            state.loaded.delete("inbox");
            await loadInbox(true);
            closeThesisEditor();
        } catch (error) {
            status.textContent = apiErrorMessage(error, "Could not save the thesis.");
        }
    }

    async function handleInboxAction(button) {
        const action = button.dataset.reviewAction;
        if (action === "trust") return activateTab("trust");
        if (action === "report") return activateTab("report");
        if (action === "thesis") return openThesisEditor(Number(button.dataset.reviewHolding));
        if (action === "manage-dca") {
            close();
            window.DcaWorkflow?.open?.();
            return;
        }
        if (action === "holding" && button.dataset.reviewTicker) {
            const ticker = button.dataset.reviewTicker;
            close();
            if (typeof setDashboardZone === "function") setDashboardZone("holdings");
            requestAnimationFrame(() => {
                if (typeof highlightHolding === "function") highlightHolding(ticker);
            });
        }
    }

    async function refresh() {
        state.loaded.clear();
        const jobs = [loadInbox(true), loadTrust(true)];
        if (state.tab === "report") jobs.push(loadReport(true));
        if (state.tab === "compare") jobs.push(loadWatchlist(true));
        if (state.tab === "plan") jobs.push(loadPlan(true));
        if (state.tab === "backups") jobs.push(loadBackups(true));
        await Promise.allSettled(jobs);
        live("Review Orbit refreshed.");
    }

    function bind() {
        document.querySelectorAll("[data-review-close]").forEach(button => {
            button.addEventListener("click", close);
        });
        document.querySelectorAll("[data-review-tab]").forEach(button => {
            button.addEventListener("click", () => activateTab(button.dataset.reviewTab));
            button.addEventListener("keydown", event => {
                if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
                event.preventDefault();
                const tabs = Array.from(document.querySelectorAll("[data-review-tab]"));
                const direction = event.key === "ArrowRight" ? 1 : -1;
                const next = tabs[(tabs.indexOf(button) + direction + tabs.length) % tabs.length];
                activateTab(next.dataset.reviewTab);
                next.focus();
            });
        });
        $("review-orbit-refresh")?.addEventListener("click", refresh);
        $("review-inbox-list")?.addEventListener("click", event => {
            const button = event.target.closest("[data-review-action]");
            if (button) handleInboxAction(button);
        });
        $("review-thesis-editor")?.addEventListener("submit", saveThesis);
        $("review-thesis-cancel")?.addEventListener("click", closeThesisEditor);
        document.querySelectorAll("[data-report-period]").forEach(button => {
            button.addEventListener("click", () => {
                state.reportPeriod = button.dataset.reportPeriod;
                document.querySelectorAll("[data-report-period]").forEach(item => {
                    item.setAttribute("aria-pressed", String(item === button));
                });
                state.loaded.delete("report");
                loadReport(true);
            });
        });
        document.querySelectorAll("[data-report-export]").forEach(button => {
            button.addEventListener("click", () => exportReport(button.dataset.reportExport));
        });
        $("review-watchlist-picks")?.addEventListener("change", event => {
            if (!event.target.matches("input[type='checkbox']")) return;
            const selected = selectedWatchlist();
            if (selected.length > 3) {
                event.target.checked = false;
                showToast("Choose no more than three research tickers.", "warning");
            }
            syncCompareButton();
        });
        $("review-compare-run")?.addEventListener("click", runCompare);
        $("review-target-form")?.addEventListener("submit", saveTargets);
        $("review-rehearsal-form")?.addEventListener("submit", runRehearsal);
        $("review-recap-form")?.addEventListener("submit", saveRecap);
        $("review-portable-export")?.addEventListener("click", savePortableRecords);
        $("review-backup-create")?.addEventListener("click", createBackup);
        $("review-protection-status")?.addEventListener("click", event => {
            if (event.target.closest("#review-auto-switch")) toggleAutoBackup();
        });
        $("review-backup-list")?.addEventListener("click", event => {
            const exportButton = event.target.closest("[data-backup-export]");
            const restoreButton = event.target.closest("[data-backup-restore]");
            if (exportButton) exportBackup(exportButton.dataset.backupExport);
            if (restoreButton) askRestore(restoreButton.dataset.backupRestore);
        });
        $("review-restore-cancel")?.addEventListener("click", cancelRestore);
        $("review-restore-accept")?.addEventListener("click", acceptRestore);
    }

    document.addEventListener("DOMContentLoaded", bind);
    return { open, close, refresh, activateTab };
})();
