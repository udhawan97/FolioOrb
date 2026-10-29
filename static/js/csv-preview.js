/** Reviewed CSV imports. Uncertain writes require comparison, never an automatic replay. */
(function installCsvPreview(root, factory) {
    if (typeof module === "object" && module.exports) module.exports = { createCsvPreview: factory };
    else root.createCsvPreview = factory;
})(typeof window !== "undefined" ? window : globalThis, function createCsvPreview({
    document, workspace, storage = null,
    refresh = async () => { throw new Error("Holdings refresh is unavailable."); },
}) {
    const el = id => document.getElementById("csv-preview-" + id);
    const choose = el("choose"), input = el("input"), result = el("result"), heading = el("heading");
    const status = el("status"), tableBox = el("table"), paging = el("paging"), range = el("range");
    const previous = el("previous"), next = el("next"), confirmButton = el("confirm");
    const recoveryBox = el("recovery"), acknowledge = el("acknowledge"), fresh = el("fresh");
    const reconcileButton = el("reconcile"), immediate = document.getElementById("import-choose-btn");
    const KEY = "folioorb-csv-confirmation-v1";
    const fields = ["ticker", "shares", "avg_cost", "is_watchlist", "hold_class", "notes",
        "thesis_review_interval_days"];
    const labels = ["Ticker", "Shares", "Avg cost", "Research", "Class", "Notes", "Thesis cadence (days)"];
    let generation = 0, controller = null, report = null, comparison = null, page = 0, file = null;
    let working = false, confirming = false, invalidMarker = false, recovery = null;

    const canonical = value => JSON.stringify(value, function sorted(_key, item) {
        return item && typeof item === "object" && !Array.isArray(item)
            ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item;
    });
    const equal = (left, right) => canonical(left) === canonical(right);
    const validRows = rows => Array.isArray(rows) && rows.length > 0 && rows.length <= 200
        && rows.every((row, i) => Number.isInteger(row) && row >= 2 && row <= 201
            && (!i || row > rows[i - 1]));
    const digest = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
    const meta = data => Object.fromEntries(["portfolio_id", "input_digest", "normalized_digest",
        "reviewed_rows"].map(key => [key, data[key]]));
    const message = data => typeof data?.detail === "string" ? data.detail
        : data?.detail?.message || "The response could not be verified.";
    const display = value => value === null || value === undefined || value === "" ? "—" : String(value);

    function readMarker() {
        try {
            const raw = storage?.getItem(KEY);
            if (!raw) return;
            const item = JSON.parse(raw);
            if (raw.length > 4096 || item.version !== 1 || !["uncertain", "saved"].includes(item.state)
                || !Number.isInteger(item.portfolio_id) || item.portfolio_id <= 0
                || !digest(item.input_digest) || !digest(item.normalized_digest)
                || !validRows(item.reviewed_rows)
                || Object.keys(item).some(key => !["version", "state", ...Object.keys(meta(item))].includes(key))) {
                throw new Error("Invalid recovery metadata");
            }
            recovery = item;
        } catch (_) { invalidMarker = true; }
    }
    function remember(item) {
        if (!storage) throw new Error("Recovery storage is unavailable; preview remains read-only.");
        const raw = JSON.stringify(item);
        storage.setItem(KEY, raw);
        if (storage.getItem(KEY) !== raw) throw new Error("Recovery metadata could not be retained.");
        recovery = item;
    }
    function forget() {
        storage.removeItem(KEY);
        if (storage.getItem(KEY) !== null) throw new Error("Recovery metadata could not be cleared.");
        recovery = null;
    }
    function comparisonIsKnown() {
        return comparison && comparison.unknown === 0
            && comparison.rows.every(row => ["matching", "mismatching"].includes(row.status));
    }
    function syncControls() {
        choose.disabled = working || confirming || invalidMarker;
        choose.textContent = recovery ? "Choose reviewed CSV…" : "Preview CSV…";
        if (immediate) immediate.disabled = working || confirming || !!recovery || invalidMarker;
        if (confirmButton) {
            confirmButton.hidden = !report || report.saved || !!recovery || invalidMarker;
            confirmButton.disabled = working || confirming || !report?.would_add
                || !report?.confirmation || !storage;
            confirmButton.textContent = `Confirm ${report?.would_add || 0} ${report?.would_add === 1 ? "addition" : "additions"}`;
        }
        if (recoveryBox) recoveryBox.hidden = !recovery && !invalidMarker;
        if (reconcileButton) reconcileButton.disabled = working || confirming || !file
            || recovery?.portfolio_id !== workspace.id || invalidMarker;
        if (acknowledge) acknowledge.disabled = !comparisonIsKnown() || confirming;
        if (fresh) fresh.disabled = working || confirming || !comparisonIsKnown()
            || !acknowledge?.checked;
    }
    function announce(text, title) {
        result.hidden = false;
        heading.textContent = title;
        status.textContent = text;
        heading.focus();
    }
    function recoveryMessage(text = "Outcome needs reconciliation. No retry was sent.") {
        report = null;
        comparison = null;
        tableBox.replaceChildren();
        paging.hidden = true;
        if (acknowledge) acknowledge.checked = false;
        announce(invalidMarker ? "Recovery metadata is unavailable. Inspect the portfolio before resolving this import."
            : recovery?.portfolio_id !== workspace.id ? `Reconcile portfolio ${recovery.portfolio_id} before confirming another CSV.`
                : `${text} Refresh and compare the original reviewed CSV. Matching records do not prove this request created them.`,
        "CSV confirmation — reconciliation required");
        syncControls();
    }
    function cancel(returnFocus = true) {
        generation += 1;
        controller?.abort();
        controller = null;
        working = false;
        report = null;
        comparison = null;
        page = 0;
        if (!recovery && !confirming) file = null;
        input.value = "";
        result.hidden = true;
        result.setAttribute("aria-busy", "false");
        status.textContent = "";
        tableBox.replaceChildren();
        paging.hidden = true;
        if (acknowledge) acknowledge.checked = false;
        syncControls();
        if (returnFocus) {
            const target = confirming ? document.getElementById("import-csv-btn") : choose;
            target?.focus();
        }
    }
    function renderPage() {
        const rows = comparison?.rows || report.rows;
        const table = document.createElement("table"), caption = document.createElement("caption");
        caption.textContent = comparison
            ? "Reviewed → current persisted values. Matching records do not prove this request created them."
            : "Values are normalized unless Result says supplied text. Proposed additions show stored defaults: "
                + "cost 0 means unknown; unset thesis cadence is —. Snapshot " + report.snapshot_at;
        table.append(caption);
        const header = document.createElement("tr");
        for (const label of ["Row", "Result", ...labels, "Reason"]) {
            const cell = document.createElement("th"); cell.setAttribute("scope", "col");
            cell.textContent = label; header.append(cell);
        }
        const head = document.createElement("thead"); head.append(header); table.append(head);
        const body = document.createElement("tbody");
        for (const row of rows.slice(page * 25, (page + 1) * 25)) {
            const tr = document.createElement("tr");
            let values;
            if (comparison) {
                const absent = row.status === "unknown" ? "Unknown" : "No active holding";
                values = [row.row, row.status, ...fields.map(field => display(row.expected[field])
                    + " → " + (row.current ? display(row.current[field]) : absent)), row.reason];
            } else {
                const shown = row.proposed_values || row.values || {};
                const label = row.status === "would_add" ? "Would add" : row.status === "added" ? "Saved" : row.status;
                values = [row.row, label + (row.normalized ? "" : " (supplied text)"),
                    ...fields.map(field => field === "ticker" && row.normalized ? row.ticker : shown[field]), row.reason];
            }
            for (const value of values) {
                const td = document.createElement("td"); td.textContent = display(value); tr.append(td);
            }
            body.append(tr);
        }
        table.append(body); tableBox.replaceChildren(table);
        paging.hidden = rows.length === 0;
        previous.disabled = page === 0;
        next.disabled = (page + 1) * 25 >= rows.length;
        range.textContent = `Rows ${rows.length ? page * 25 + 1 : 0}–${Math.min((page + 1) * 25, rows.length)} of ${rows.length}`;
    }
    function verifiedPreview(data, portfolioId) {
        if (data.portfolio_id !== portfolioId || data.saved !== false || !Array.isArray(data.rows)
            || data.rows.length > 200 || ![data.would_add, data.skipped, data.errors].every(n => Number.isInteger(n) && n >= 0)
            || data.would_add + data.skipped + data.errors !== data.rows.length
            || data.rows.some(row => !["would_add", "skipped", "error"].includes(row.status))) return false;
        if (!data.confirmation) return true; // older inspect-only callers remain readable
        return data.would_add > 0 && /^[A-Za-z0-9_-]{43}$/.test(data.confirmation.token)
            && Number.isFinite(Date.parse(data.confirmation.expires_at))
            && digest(data.input_digest) && digest(data.normalized_digest) && validRows(data.reviewed_rows)
            && equal(data.reviewed_rows, data.rows.filter(row => row.status === "would_add").map(row => row.row))
            && data.rows.filter(row => row.status === "would_add").every(row => row.proposed_values
                && fields.every(field => Object.hasOwn(row.proposed_values, field)));
    }
    async function verifyProposals(data) {
        if (!data.confirmation) return;
        if (!globalThis.crypto?.subtle) {
            data.confirmation = null; // safe read-only fallback; never send an unchecked write
            return;
        }
        const proposals = JSON.parse(data.proposal_json);
        const shown = data.rows.filter(row => row.status === "would_add")
            .map(row => ({ row: row.row, values: row.proposed_values }));
        const bytes = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(data.proposal_json));
        const hex = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, "0")).join("");
        if (proposals.mode !== "local" || !equal(proposals.rows, shown) || hex !== data.normalized_digest) {
            throw new Error("Reviewed values could not be verified. No confirmation is available.");
        }
    }
    async function start(chosen) {
        if (!chosen || working || confirming) return;
        if (recovery || invalidMarker) {
            if (recovery?.portfolio_id !== workspace.id || invalidMarker) { recoveryMessage(); return; }
            file = chosen;
            await reconcile();
            return;
        }
        cancel(false);
        file = chosen;
        const request = generation, portfolioId = workspace.id;
        working = true; controller = new AbortController(); syncControls();
        result.hidden = false; result.setAttribute("aria-busy", "true");
        heading.textContent = "CSV preview — nothing saved";
        status.textContent = "Checking CSV… Nothing saved. You can close this preview at any time.";
        try {
            const form = new FormData(); form.append("file", chosen);
            const response = await workspace.response("/api/portfolio/holdings/preview", {
                method: "POST", body: form, signal: controller.signal,
            });
            const data = await response.json();
            if (request !== generation || workspace.id !== portfolioId) return;
            if (!response.ok) throw new Error(message(data));
            if (!verifiedPreview(data, portfolioId)) throw new Error("The preview response could not be verified. Please try again.");
            await verifyProposals(data);
            if (request !== generation || workspace.id !== portfolioId) return;
            report = data;
            status.textContent = `Preview for ${data.portfolio.name} (portfolio ${portfolioId}): `
                + `${data.would_add} would add, ${data.skipped} skipped, ${data.errors} errors. Nothing saved. `
                + (!data.would_add ? "No additions to confirm." : data.confirmation
                    ? `Confirmation expires ${data.confirmation.expires_at}. Holdings may change after this snapshot.`
                    : "Read-only preview; confirmation is unavailable.");
            if (!storage) status.textContent += " Recovery storage unavailable; preview remains read-only.";
            renderPage(); heading.focus();
        } catch (error) {
            if (request === generation && workspace.id === portfolioId) {
                status.textContent = `Nothing saved. ${error.message || "Preview failed."}`; heading.focus();
            }
        } finally {
            if (request === generation) {
                working = false; controller = null; result.setAttribute("aria-busy", "false");
                if (workspace.id !== portfolioId) cancel(false); else syncControls();
            }
        }
    }
    function verifiedReceipt(expected, data) {
        const rows = expected.rows.map(row => ({ ...row, status: row.status === "would_add" ? "added" : row.status }));
        return data.saved === true && data.portfolio_id === expected.portfolio_id
            && data.portfolio?.id === expected.portfolio_id && data.mode === "local"
            && data.input_digest === expected.input_digest && data.normalized_digest === expected.normalized_digest
            && data.proposal_json === expected.proposal_json
            && equal(data.reviewed_rows, expected.reviewed_rows) && data.added === expected.would_add
            && data.skipped === expected.skipped && data.errors === expected.errors && equal(data.rows, rows)
            && Array.isArray(data.inserted_ids) && data.inserted_ids.length === data.added
            && new Set(data.inserted_ids).size === data.added && data.inserted_ids.every(id => Number.isInteger(id) && id > 0);
    }
    function knownPrewrite(expected, data) {
        const detail = data?.detail;
        return detail?.saved === false && detail.not_executed === true
            && detail.portfolio_id === expected.portfolio_id
            && detail.normalized_digest === expected.normalized_digest
            && equal(detail.reviewed_rows, expected.reviewed_rows)
            && ["busy", "stale", "expired"].includes(detail.code);
    }
    async function comparisonRead(metadata, signal) {
        if (!file) throw new Error("Choose the original reviewed CSV to compare.");
        const form = new FormData(); form.append("file", file); form.append("manifest", JSON.stringify(meta(metadata)));
        const response = await workspace.response("/api/portfolio/holdings/reconcile", { method: "POST", body: form, signal });
        const data = await response.json();
        if (!response.ok) throw new Error(message(data));
        if (data.saved !== false || data.portfolio_id !== metadata.portfolio_id
            || data.input_digest !== metadata.input_digest || data.normalized_digest !== metadata.normalized_digest
            || !Array.isArray(data.rows)
            || !equal(data.rows.map(row => row.row), metadata.reviewed_rows)
            || ![data.matching, data.mismatching, data.unknown].every(n => Number.isInteger(n) && n >= 0)
            || ["matching", "mismatching", "unknown"].some(statusName =>
                data[statusName] !== data.rows.filter(row => row.status === statusName).length)
            || data.rows.some(row => !["matching", "mismatching", "unknown"].includes(row.status)
                || !row.expected || !fields.every(field => Object.hasOwn(row.expected, field))
                || (row.current !== null && (!row.current || !fields.every(field => Object.hasOwn(row.current, field))))
                || (row.status === "matching" && !equal(row.expected, row.current))
                || (row.status === "mismatching" && equal(row.expected, row.current)))) {
            throw new Error("Comparison response could not be verified; outcome remains unknown.");
        }
        return data;
    }
    async function confirmReviewed() {
        if (working || confirming || recovery || invalidMarker || !report?.confirmation || !report.would_add) return;
        const expected = report, portfolioId = workspace.id, request = generation;
        try { remember({ version: 1, state: "uncertain", ...meta(expected) }); }
        catch (error) { status.textContent = error.message + " No confirmation sent."; syncControls(); return; }
        confirming = true; syncControls(); result.setAttribute("aria-busy", "true");
        status.textContent = "Confirming reviewed additions. Closing does not undo a committed request.";
        let saved = false;
        try {
            const response = await workspace.response("/api/portfolio/holdings/confirm", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token: expected.confirmation.token, normalized_digest: expected.normalized_digest }),
            });
            const data = await response.json();
            if (!response.ok && knownPrewrite(expected, data)) {
                forget();
                if (request === generation && workspace.id === portfolioId) {
                    report = data.detail.code === "busy" ? expected : null;
                    status.textContent = data.detail.message;
                    heading.focus();
                }
                return;
            }
            if (!response.ok || !verifiedReceipt(expected, data)) throw new Error("Outcome needs reconciliation. No retry was sent.");
            saved = true;
            try { remember({ ...recovery, state: "saved" }); } catch (_) { /* earlier uncertain marker remains */ }
            if (request !== generation || workspace.id !== portfolioId) return;
            const checked = await comparisonRead(recovery);
            if (request !== generation || workspace.id !== portfolioId) return;
            if (checked.unknown || checked.mismatching) {
                comparison = checked; report = null; page = 0;
                announce("Saved, but current fields need review. Matching records do not prove who created them.",
                    "CSV confirmation — review current records"); renderPage(); return;
            }
            await refresh(portfolioId);
            if (request !== generation || workspace.id !== portfolioId) return;
            forget(); report = data; comparison = null;
            announce(`Saved ${data.added} reviewed additions. Readback verified. Closing does not undo them.`, "CSV confirmation — saved");
            renderPage();
        } catch (_) {
            if (request === generation && workspace.id === portfolioId) {
                recoveryMessage(saved ? "Saved, but refresh failed. Do not confirm again." : undefined);
            }
        } finally {
            confirming = false;
            if (request === generation) {
                if (workspace.id !== portfolioId) cancel(false);
                else result.setAttribute("aria-busy", "false");
            }
            syncControls();
        }
    }
    async function reconcile() {
        if (working || confirming || !recovery || invalidMarker || recovery.portfolio_id !== workspace.id) return;
        if (!file) { recoveryMessage(); return; }
        const request = generation, portfolioId = workspace.id;
        working = true; controller = new AbortController(); syncControls();
        result.hidden = false; result.setAttribute("aria-busy", "true");
        try {
            const checked = await comparisonRead(recovery, controller.signal);
            if (request !== generation || workspace.id !== portfolioId) return;
            comparison = checked; report = null; page = 0;
            if (acknowledge) acknowledge.checked = false;
            announce(`Current records: ${checked.matching} matching, ${checked.mismatching} mismatching, ${checked.unknown} unknown. `
                + "No new import sent. Matching records do not prove this request created them. Inspect every field before starting a fresh preview.",
            "CSV confirmation — compare reviewed records");
            renderPage();
        } catch (error) {
            if (request === generation && workspace.id === portfolioId) recoveryMessage(`Outcome remains unknown. ${error.message}`);
        } finally {
            if (request === generation) {
                working = false; controller = null; result.setAttribute("aria-busy", "false"); syncControls();
            }
        }
    }
    function startFresh() {
        if (!comparisonIsKnown() || !acknowledge?.checked || working || confirming) return;
        try { forget(); } catch (_) { recoveryMessage("Recovery metadata could not be cleared."); return; }
        file = null; cancel();
    }
    function open() {
        if (recovery || invalidMarker) recoveryMessage();
    }
    choose.addEventListener("click", () => input.click());
    input.addEventListener("change", () => { const chosen = input.files?.[0]; input.value = ""; start(chosen); });
    el("close").addEventListener("click", () => cancel());
    previous.addEventListener("click", () => { if (page > 0) { page -= 1; renderPage(); } });
    next.addEventListener("click", () => {
        const rows = comparison?.rows || report?.rows;
        if (rows && (page + 1) * 25 < rows.length) { page += 1; renderPage(); }
    });
    confirmButton?.addEventListener("click", confirmReviewed);
    reconcileButton?.addEventListener("click", reconcile);
    acknowledge?.addEventListener("change", syncControls);
    fresh?.addEventListener("click", startFresh);
    readMarker(); syncControls(); open();
    return { start, cancel, open, confirm: confirmReviewed, reconcile, startFresh };
});
