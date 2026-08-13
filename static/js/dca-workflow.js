/**
 * DCA workflow: one private owner for plan UI, pending actions, dialogs, and
 * refresh ordering. The browser-facing interface is deliberately only open().
 */
(function installDcaWorkflow(root, factory) {
    if (typeof module === "object" && module.exports) {
        module.exports = { createDcaWorkflow: factory };
        return;
    }
    const runtime = factory({
        workspace: root.PortfolioWorkspace,
        document: root.document,
        notify: root.showToast,
        // dashboard.js declares this as a top-level const, which is a shared
        // classic-script binding but intentionally not a window property.
        formatMoney: formatCurrency,
        escape: root.escapeHtml,
        openManager: root.openPortfolioManager,
        holdingsChanged: async () => {
            await root.loadManageHoldings({ preserveExisting: true });
            root.refreshDashboardData({ includeManageHoldings: false });
        },
        scheduleFrame: root.requestAnimationFrame.bind(root),
        scheduleIdle: root.scheduleWhenIdle,
        log: root.console,
    });
    root.DcaWorkflow = { open: runtime.open };
    root.document.addEventListener("DOMContentLoaded", runtime.init, { once: true });
})(typeof window !== "undefined" ? window : globalThis, function createDcaWorkflow({
    workspace,
    document,
    notify = () => {},
    formatMoney = value => String(value),
    escape = value => String(value),
    openManager = () => {},
    holdingsChanged = async () => {},
    scheduleFrame = callback => callback(),
    scheduleIdle = callback => callback(),
    log = { warn: () => {} },
    confirmAction = null,
}) {
    let initialized = false;
    let mutationInFlight = false;
    let dialogState = null;

    const byId = id => document.getElementById(id);

    function setPanel(open) {
        const panel = byId("dca-panel");
        const button = byId("dca-btn");
        if (!panel) return false;
        panel.hidden = !open;
        button?.setAttribute("aria-expanded", String(open));
        if (open) loadPanel();
        return true;
    }

    function open() {
        openManager();
        return setPanel(true);
    }

    function togglePanel() {
        const panel = byId("dca-panel");
        if (!panel) return;
        setPanel(panel.hidden);
    }

    function formDefaults() {
        const start = byId("dca-start-date");
        if (!start) return;
        const today = new Date().toISOString().slice(0, 10);
        start.max = today;
        start.value = today;
        const frequency = byId("dca-frequency");
        if (frequency) frequency.value = "weekly";
    }

    async function runCatchup() {
        try {
            const response = await workspace.response("/api/dca/run", { method: "POST" });
            if (!response.ok) return;
            const data = await response.json();
            const unpriced = (data.plans || []).filter(plan => !plan.price_data);
            if (unpriced.length) {
                notify(
                    `Couldn't fetch prices for ${unpriced.map(plan => plan.ticker).join(", ")} — DCA buys not booked yet`,
                    "warning",
                );
            }
            if (data.buys_added > 0) {
                notify(
                    `${data.buys_added} DCA buy${data.buys_added === 1 ? "" : "s"} ready to review in Manage → DCA`,
                    "info",
                );
            }
            updateBadge();
        } catch (error) {
            log.warn("DCA catch-up failed:", error);
        }
    }

    async function updateBadge() {
        const badge = byId("dca-badge");
        if (!badge) return;
        try {
            const data = await workspace.json("/api/dca/contributions?status=pending");
            const count = (data.contributions || []).length;
            badge.textContent = count > 99 ? "99+" : String(count);
            badge.hidden = count === 0;
        } catch (_) { /* cosmetic while offline */ }
    }

    async function loadPanel() {
        try {
            const [plans, pending] = await Promise.all([
                workspace.json("/api/dca/plans"),
                workspace.json("/api/dca/contributions?status=pending"),
            ]);
            renderPlans(plans.plans || []);
            renderPending(pending.contributions || [], plans.plans || []);
            updateBadge();
            const history = byId("dca-history-list");
            if (history && !history.hidden) loadHistory();
        } catch (error) {
            log.warn("DCA panel load failed:", error);
        }
    }

    function renderPlans(plans) {
        const section = byId("dca-plans-section");
        const list = byId("dca-plans-list");
        if (!section || !list) return;
        section.hidden = plans.length === 0;
        list.innerHTML = plans.map(plan => {
            const applied = plan.applied_count
                ? `${formatMoney(plan.applied_amount)} → ${plan.applied_shares.toFixed(4)} sh @ ${formatMoney(plan.applied_avg_cost)}`
                : "nothing applied yet";
            const status = plan.is_active
                ? (plan.next_date
                    ? `<span class="dca-plan-next">Next buy ${escape(plan.next_date)}</span>`
                    : "")
                : '<span class="dca-plan-flag">Paused</span>';
            return `
            <div class="dca-plan-card${plan.is_active ? "" : " dca-plan-card--paused"}" data-plan-id="${plan.id}">
                <div class="dca-plan-head">
                    <div class="dca-plan-id">
                        <span class="dca-plan-ticker">${escape(plan.ticker)}</span>
                        <span class="dca-plan-terms">${formatMoney(plan.amount)} · ${escape(plan.frequency)}</span>
                    </div>${status}
                </div>
                <div class="dca-plan-sub">Applied so far: ${applied}</div>
                <div class="dca-plan-actions">
                    <button type="button" class="btn btn-sm dca-chip-btn" data-dca-action="toggle-plan" data-plan-id="${plan.id}" data-active="${plan.is_active}">${plan.is_active ? "Pause" : "Resume"}</button>
                    <button type="button" class="btn btn-sm dca-chip-btn" data-dca-action="edit-plan" data-plan-id="${plan.id}" data-amount="${plan.amount}">Edit amount</button>
                    ${plan.applied_count ? `<button type="button" class="btn btn-sm dca-chip-btn" data-dca-action="undo-all" data-plan-id="${plan.id}" data-count="${plan.applied_count}" data-ticker="${escape(plan.ticker)}">Undo applied</button>` : ""}
                    <button type="button" class="btn btn-sm dca-chip-btn dca-chip-btn--danger" data-dca-action="delete-plan" data-plan-id="${plan.id}" data-ticker="${escape(plan.ticker)}">Delete</button>
                </div>
            </div>`;
        }).join("");
    }

    function buyRow(contribution, actions) {
        return `
        <div class="dca-buy-row" data-cid="${contribution.id}">
            <span class="dca-buy-date">${escape(contribution.exec_date)}</span>
            <span class="dca-buy-detail">
                <span class="dca-buy-shares">${contribution.shares.toFixed(4)} sh</span>
                <span class="dca-buy-meta">@ ${formatMoney(contribution.price)} · ${formatMoney(contribution.amount)}</span>
            </span>
            <span class="dca-buy-end">${actions}</span>
        </div>`;
    }

    function renderPending(pending, plans) {
        const section = byId("dca-pending-section");
        const list = byId("dca-pending-list");
        if (!section || !list) return;
        section.hidden = pending.length === 0;
        if (!pending.length) {
            list.innerHTML = "";
            return;
        }
        const plansById = Object.fromEntries(plans.map(plan => [plan.id, plan]));
        const groups = new Map();
        pending.forEach(contribution => {
            if (!groups.has(contribution.plan_id)) groups.set(contribution.plan_id, []);
            groups.get(contribution.plan_id).push(contribution);
        });
        list.innerHTML = [...groups.entries()].map(([planId, buys]) => {
            const plan = plansById[planId];
            const ticker = plan?.ticker || buys[0].ticker || "?";
            const terms = plan ? `${formatMoney(plan.amount)} ${escape(plan.frequency)}` : "";
            const total = buys.reduce((sum, contribution) => sum + contribution.amount, 0);
            const cap = 15;
            const rows = buys.slice(0, cap).map(contribution => buyRow(
                contribution,
                `<button type="button" class="btn btn-sm btn-success dca-act-btn" data-dca-action="apply" data-cid="${contribution.id}">Apply</button>
                 <button type="button" class="btn btn-sm dca-chip-btn" data-dca-action="skip" data-cid="${contribution.id}">Skip</button>`,
            )).join("") + (buys.length > cap
                ? `<div class="dca-more-note">…and ${buys.length - cap} more — use “Apply all ${buys.length}” or “Skip all” above.</div>`
                : "");
            const bulk = buys.length > 1 ? `
                <span class="dca-bulk-actions">
                    <button type="button" class="btn btn-sm btn-link dca-bulk-link" data-dca-action="apply-all" data-plan-id="${planId}" data-count="${buys.length}" data-total="${total}" data-ticker="${escape(ticker)}">Apply all ${buys.length}</button>
                    <button type="button" class="btn btn-sm btn-link dca-bulk-link dca-bulk-skip" data-dca-action="skip-all" data-plan-id="${planId}" data-count="${buys.length}" data-ticker="${escape(ticker)}">Skip all</button>
                </span>` : "";
            return `
            <div class="dca-pending-group">
                <div class="dca-pending-group-head">
                    <span class="dca-group-ticker">${escape(ticker)}</span>
                    ${terms ? `<span class="dca-group-terms">${terms}</span>` : ""}
                    <span class="dca-group-count">${buys.length} buy${buys.length === 1 ? "" : "s"} awaiting</span>${bulk}
                </div>${rows}
            </div>`;
        }).join("");
    }

    async function toggleHistory() {
        const list = byId("dca-history-list");
        const button = byId("dca-history-toggle");
        if (!list || !button) return;
        const show = list.hidden;
        list.hidden = !show;
        button.textContent = show ? "Hide history" : "Show history";
        button.setAttribute("aria-expanded", String(show));
        if (show) loadHistory();
    }

    async function loadHistory() {
        const list = byId("dca-history-list");
        if (!list) return;
        try {
            const payload = await workspace.json("/api/dca/contributions?status=all");
            const rows = (payload.contributions || []).filter(item => item.status !== "pending");
            if (!rows.length) {
                list.innerHTML = '<div class="dca-history-empty">No applied or skipped buys yet.</div>';
                return;
            }
            const cap = 80;
            list.innerHTML = rows.slice(0, cap).map(contribution => {
                const action = contribution.status === "applied"
                    ? `<button type="button" class="btn btn-sm dca-chip-btn" data-dca-action="undo" data-cid="${contribution.id}">Undo</button>`
                    : `<button type="button" class="btn btn-sm dca-chip-btn" data-dca-action="restore" data-cid="${contribution.id}">Restore</button>`;
                const ticker = contribution.ticker
                    ? `<span class="dca-buy-ticker">${escape(contribution.ticker)}</span>`
                    : "";
                return `
                <div class="dca-buy-row dca-buy-row--${contribution.status}" data-cid="${contribution.id}">
                    <span class="dca-buy-date">${ticker}${escape(contribution.exec_date)}</span>
                    <span class="dca-buy-detail"><span class="dca-buy-shares">${contribution.shares.toFixed(4)} sh</span><span class="dca-buy-meta">@ ${formatMoney(contribution.price)} · ${formatMoney(contribution.amount)}</span></span>
                    <span class="dca-buy-end"><span class="dca-buy-status dca-buy-status--${contribution.status}">${escape(contribution.status)}</span>${action}</span>
                </div>`;
            }).join("") + (rows.length > cap
                ? `<div class="dca-history-empty">Showing the latest ${cap} of ${rows.length}.</div>`
                : "");
        } catch (error) {
            log.warn("DCA history load failed:", error);
        }
    }

    function dialogFocusable() {
        const dialog = byId("dca-action-dialog");
        if (!dialog || dialog.hidden) return [];
        return Array.from(dialog.querySelectorAll(
            "button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])",
        )).filter(element => !element.closest("[hidden]") && element.getClientRects().length > 0);
    }

    function closeDialog(result = null) {
        const dialog = byId("dca-action-dialog");
        const state = dialogState;
        if (!dialog || !state) return;
        dialogState = null;
        dialog.hidden = true;
        dialog.setAttribute("aria-hidden", "true");
        document.querySelector("#portfolioModal > .portfolio-manager-panel")?.removeAttribute("inert");
        state.resolve(result);
        if (state.previousFocus?.focus) scheduleFrame(() => state.previousFocus.focus());
    }

    function openDialog({ title, copy, confirmLabel, warning = "", value = null, danger = false }) {
        if (confirmAction) {
            return confirmAction({ title, copy, confirmLabel, warning, value, danger });
        }
        const dialog = byId("dca-action-dialog");
        const field = byId("dca-action-field");
        const input = byId("dca-action-input");
        if (!dialog || !field || !input || dialogState) return Promise.resolve(null);
        byId("dca-action-title").textContent = title;
        byId("dca-action-copy").textContent = copy;
        const warningElement = byId("dca-action-warning");
        warningElement.textContent = warning;
        warningElement.hidden = !warning;
        const hasValue = value !== null;
        field.hidden = !hasValue;
        input.value = hasValue ? String(value) : "";
        input.classList.remove("is-invalid");
        input.removeAttribute("aria-invalid");
        byId("dca-action-error").hidden = true;
        const submit = byId("dca-action-submit");
        submit.textContent = confirmLabel;
        submit.classList.toggle("btn-primary", !danger);
        submit.classList.toggle("btn-danger", danger);
        const previousFocus = document.activeElement;
        document.querySelector("#portfolioModal > .portfolio-manager-panel")?.setAttribute("inert", "");
        dialog.hidden = false;
        dialog.setAttribute("aria-hidden", "false");
        return new Promise(resolve => {
            dialogState = { resolve, previousFocus, hasValue };
            scheduleFrame(() => {
                const target = hasValue ? input : byId("dca-action-cancel");
                target?.focus();
                if (hasValue) input.select();
            });
        });
    }

    function handleDialogKeydown(event) {
        if (!dialogState) return;
        if (event.key === "Escape") {
            event.preventDefault();
            event.stopImmediatePropagation();
            closeDialog();
            return;
        }
        if (event.key !== "Tab") return;
        const focusable = dialogFocusable();
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        } else if (!byId("dca-action-dialog")?.contains(document.activeElement)) {
            event.preventDefault();
            first.focus();
        }
    }

    function initDialog() {
        const dialog = byId("dca-action-dialog");
        const form = byId("dca-action-form");
        if (!dialog || !form || form.dataset.bound) return;
        form.dataset.bound = "true";
        form.addEventListener("submit", event => {
            event.preventDefault();
            if (!dialogState) return;
            if (!dialogState.hasValue) {
                closeDialog({ confirmed: true });
                return;
            }
            const input = byId("dca-action-input");
            const amount = Number.parseFloat(input.value);
            if (!Number.isFinite(amount) || amount <= 0) {
                input.classList.add("is-invalid");
                input.setAttribute("aria-invalid", "true");
                byId("dca-action-error").hidden = false;
                input.focus();
                return;
            }
            closeDialog({ confirmed: true, value: amount });
        });
        byId("dca-action-cancel")?.addEventListener("click", () => closeDialog());
        dialog.addEventListener("mousedown", event => {
            if (event.target === dialog) closeDialog();
        });
        document.addEventListener("keydown", handleDialogKeydown, true);
    }

    async function post(path, successMessage) {
        if (mutationInFlight) return null;
        mutationInFlight = true;
        try {
            const response = await workspace.response(path, { method: "POST" });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                notify(typeof data.detail === "string" ? data.detail : "DCA action failed", "danger");
                return null;
            }
            if (successMessage) notify(successMessage, "success");
            return data;
        } catch (_) {
            notify("DCA action failed — is the app online?", "danger");
            return null;
        } finally {
            mutationInFlight = false;
        }
    }

    async function afterHoldingsChange() {
        await loadPanel();
        await holdingsChanged();
    }

    async function patchPlan(id, payload, successMessage) {
        try {
            const response = await workspace.response(`/api/dca/plans/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (response.ok) {
                notify(successMessage, "success");
                loadPanel();
            }
        } catch (_) {
            notify("Could not update plan", "danger");
        }
    }

    async function handleAction(event) {
        const button = event.target?.closest?.("[data-dca-action]");
        if (!button) return null;
        const action = button.dataset.dcaAction;
        if (action === "toggle-panel") return togglePanel();
        if (action === "toggle-history") return toggleHistory();
        const id = Number(button.dataset.cid);
        const planId = Number(button.dataset.planId);
        const ticker = button.dataset.ticker || "";
        const count = Number(button.dataset.count);

        if (action === "apply") {
            const data = await post(`/api/dca/contributions/${id}/apply`);
            if (data) {
                notify(data.message || "Buy applied", "success");
                await afterHoldingsChange();
            }
            return data;
        }
        if (action === "skip") {
            const data = await post(
                `/api/dca/contributions/${id}/skip`,
                "Buy skipped — plan still active (pause it in Plans if needed)",
            );
            if (data) loadPanel();
            return data;
        }
        if (action === "undo") {
            const data = await post(`/api/dca/contributions/${id}/undo`);
            if (data) {
                notify(data.message || "Buy undone", "success");
                await afterHoldingsChange();
                loadHistory();
            }
            return data;
        }
        if (action === "restore") {
            const data = await post(
                `/api/dca/contributions/${id}/restore`, "Buy restored to pending"
            );
            if (data) {
                loadPanel();
                loadHistory();
            }
            return data;
        }
        if (action === "apply-all") {
            const choice = await openDialog({
                title: `Apply ${count} ${ticker} buys?`,
                copy: `${formatMoney(Number(button.dataset.total))} will be added to your holding using the recorded closes.`,
                warning: "You can reverse these later with “Undo applied”.",
                confirmLabel: "Apply all buys",
            });
            if (!choice?.confirmed) return null;
            const data = await post(`/api/dca/plans/${planId}/apply-pending`);
            if (data) {
                notify(`Applied ${data.applied} buys to ${data.ticker}`, "success");
                await afterHoldingsChange();
            }
            return data;
        }
        if (action === "skip-all") {
            const choice = await openDialog({
                title: `Skip ${count} pending ${ticker} buys?`,
                copy: "These buys won’t be applied and won’t reappear.",
                warning: "The plan stays active. Pause it separately to stop future buys.",
                confirmLabel: "Skip pending buys",
                danger: true,
            });
            if (!choice?.confirmed) return null;
            const data = await post(`/api/dca/plans/${planId}/skip-pending`);
            if (data) {
                notify(`Skipped ${data.skipped} buys for ${data.ticker}`, "success");
                loadPanel();
            }
            return data;
        }
        if (action === "undo-all") {
            const choice = await openDialog({
                title: `Undo ${count} applied ${ticker} buys?`,
                copy: "Your holding’s shares and average cost will roll back exactly.",
                warning: "The buys return to the pending bucket and can be reviewed again.",
                confirmLabel: "Undo applied buys",
            });
            if (!choice?.confirmed) return null;
            const data = await post(`/api/dca/plans/${planId}/undo-applied`);
            if (data) {
                notify(`Reversed ${data.undone} buys for ${data.ticker}`, "success");
                await afterHoldingsChange();
                loadHistory();
            }
            return data;
        }
        if (action === "toggle-plan") {
            return patchPlan(
                planId,
                { is_active: button.dataset.active !== "true" },
                button.dataset.active === "true"
                    ? "Plan paused — no new buys will book"
                    : "Plan resumed",
            );
        }
        if (action === "edit-plan") {
            const choice = await openDialog({
                title: "Change DCA amount",
                copy: "This amount applies to future intervals; recorded buys keep their original values.",
                confirmLabel: "Save amount",
                value: Number(button.dataset.amount),
            });
            if (choice?.confirmed) {
                return patchPlan(planId, { amount: choice.value }, "Plan amount updated");
            }
            return null;
        }
        if (action === "delete-plan") {
            const choice = await openDialog({
                title: `Delete the ${ticker} DCA plan?`,
                copy: "Undo every applied buy before deleting this plan so its holding changes stay traceable.",
                warning: "After applied buys are undone, deleting removes pending and skipped buys. This cannot be undone.",
                confirmLabel: "Delete plan",
                danger: true,
            });
            if (!choice?.confirmed) return null;
            try {
                const response = await workspace.response(`/api/dca/plans/${planId}`, {
                    method: "DELETE",
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    notify(typeof data.detail === "string" ? data.detail : "Could not delete plan", "danger");
                    return null;
                }
                notify(`${ticker} plan deleted`, "success");
                loadPanel();
                return data;
            } catch (_) {
                notify("Could not delete plan — is the app online?", "danger");
            }
        }
        return null;
    }

    function hideBackfillConfirm() {
        const confirmation = byId("dca-backfill-confirm");
        if (confirmation) confirmation.hidden = true;
    }

    async function createPlan() {
        const ticker = byId("dca-ticker").value.trim().toUpperCase();
        const amount = Number.parseFloat(byId("dca-amount").value);
        const frequency = byId("dca-frequency").value;
        const startDate = byId("dca-start-date").value;
        if (!ticker || !Number.isFinite(amount) || amount <= 0 || !startDate) {
            notify("Fill in ticker, amount, and start date", "warning");
            return;
        }
        const today = new Date().toISOString().slice(0, 10);
        if (startDate < today) {
            let held = null;
            try {
                const owned = await workspace.json("/api/portfolio/holdings");
                held = (owned.holdings || []).find(row => row.ticker === ticker && row.shares > 0);
            } catch (_) { /* offline: backend still validates the plan */ }
            if (held) {
                const confirmation = byId("dca-backfill-confirm");
                const text = byId("dca-confirm-text");
                const heldShares = Number(held.shares.toFixed(4));
                text.textContent = `You already hold ${heldShares} ${ticker}. If that count already includes your past auto-invest buys, applying a backfill would double-count them. Track from today, or backfill anyway and review each buy before applying.`;
                confirmation.hidden = false;
                byId("dca-confirm-today").onclick = () => {
                    hideBackfillConfirm();
                    submitPlan({ ticker, amount, frequency, start_date: today });
                };
                byId("dca-confirm-backfill").onclick = () => {
                    hideBackfillConfirm();
                    submitPlan({ ticker, amount, frequency, start_date: startDate });
                };
                return;
            }
        }
        submitPlan({ ticker, amount, frequency, start_date: startDate });
    }

    async function submitPlan(payload) {
        const button = byId("dca-create-btn");
        button.disabled = true;
        try {
            const response = await workspace.response("/api/dca/plans", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const detail = data.detail;
                notify(
                    typeof detail === "string"
                        ? detail
                        : detail?.message || detail?.[0]?.msg || "Could not create plan",
                    "danger",
                );
                return;
            }
            byId("dca-create-form").reset();
            formDefaults();
            notify(
                data.buys_added > 0
                    ? `${payload.ticker} plan created — ${data.buys_added} buy${data.buys_added === 1 ? "" : "s"} ready to review`
                    : `${payload.ticker} plan created — first buy books on the next interval`,
                "success",
            );
            loadPanel();
        } catch (_) {
            notify("Could not create plan — is the app online?", "danger");
        } finally {
            button.disabled = false;
        }
    }

    function init() {
        if (initialized) return;
        initialized = true;
        const form = byId("dca-create-form");
        if (form) {
            form.addEventListener("submit", event => {
                event.preventDefault();
                createPlan();
            });
        }
        document.addEventListener("click", handleAction);
        byId("dca-confirm-cancel")?.addEventListener("click", hideBackfillConfirm);
        formDefaults();
        initDialog();
        scheduleIdle(runCatchup);
    }

    // The browser exposes only open(); the factory returns its lifecycle/action
    // seams so runtime tests can exercise behavior without a browser framework.
    return { open, init, handleAction };
});
