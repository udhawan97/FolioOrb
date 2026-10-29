/** Inspect-only CSV UI. A cancelled or stale request never paints a new workspace. */
(function installCsvPreview(root, factory) {
    if (typeof module === "object" && module.exports) {
        module.exports = { createCsvPreview: factory };
    } else {
        root.createCsvPreview = factory;
    }
})(typeof window !== "undefined" ? window : globalThis, function createCsvPreview({
    document, workspace,
}) {
    const choose = document.getElementById("csv-preview-choose");
    const input = document.getElementById("csv-preview-input");
    const result = document.getElementById("csv-preview-result");
    const heading = document.getElementById("csv-preview-heading");
    const status = document.getElementById("csv-preview-status");
    const tableBox = document.getElementById("csv-preview-table");
    const paging = document.getElementById("csv-preview-paging");
    const previous = document.getElementById("csv-preview-previous");
    const next = document.getElementById("csv-preview-next");
    const range = document.getElementById("csv-preview-range");
    let generation = 0;
    let controller = null;
    let report = null;
    let page = 0;

    function cancel(returnFocus = true) {
        generation += 1;
        controller?.abort();
        controller = null;
        report = null;
        page = 0;
        input.value = "";
        choose.disabled = false;
        result.hidden = true;
        result.setAttribute("aria-busy", "false");
        status.textContent = "";
        tableBox.replaceChildren();
        paging.hidden = true;
        if (returnFocus) choose.focus();
    }

    function renderPage() {
        const table = document.createElement("table");
        const caption = document.createElement("caption");
        caption.textContent = "Values are normalized unless Result says supplied text. "
            + "Snapshot " + report.snapshot_at;
        table.append(caption);
        const header = document.createElement("tr");
        for (const label of ["Row", "Result", "Ticker", "Shares", "Avg cost", "Research", "Class", "Notes", "Reason"]) {
            const cell = document.createElement("th");
            cell.setAttribute("scope", "col");
            cell.textContent = label;
            header.append(cell);
        }
        const head = document.createElement("thead");
        head.append(header);
        table.append(head);
        const body = document.createElement("tbody");
        for (const row of report.rows.slice(page * 25, (page + 1) * 25)) {
            const tr = document.createElement("tr");
            const values = row.values || {};
            const resultLabel = (row.status === "would_add" ? "Would add" : row.status)
                + (row.normalized ? "" : " (supplied text)");
            for (const value of [row.row, resultLabel,
                row.ticker, values.shares, values.avg_cost, values.is_watchlist,
                values.hold_class, values.notes, row.reason]) {
                const td = document.createElement("td");
                td.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
                tr.append(td);
            }
            body.append(tr);
        }
        table.append(body);
        tableBox.replaceChildren(table);
        paging.hidden = report.rows.length === 0;
        previous.disabled = page === 0;
        next.disabled = (page + 1) * 25 >= report.rows.length;
        range.textContent = `Rows ${report.rows.length ? page * 25 + 1 : 0}–${Math.min((page + 1) * 25, report.rows.length)} of ${report.rows.length}`;
    }

    async function start(file) {
        if (!file || choose.disabled) return;
        cancel(false);
        const request = generation;
        const portfolioId = workspace.id;
        controller = new AbortController();
        choose.disabled = true;
        result.hidden = false;
        result.setAttribute("aria-busy", "true");
        status.textContent = "Checking CSV… Nothing saved. You can close this preview at any time.";
        try {
            const form = new FormData();
            form.append("file", file);
            const response = await workspace.response("/api/portfolio/holdings/preview", {
                method: "POST", body: form, signal: controller.signal,
            });
            const data = await response.json();
            if (request !== generation || workspace.id !== portfolioId) return;
            if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Preview failed.");
            if (data.portfolio_id !== portfolioId || data.saved !== false || !Array.isArray(data.rows)
                || data.rows.length > 200 || data.would_add + data.skipped + data.errors !== data.rows.length
                || data.rows.some(row => !["would_add", "skipped", "error"].includes(row.status))) {
                throw new Error("The preview response could not be verified. Please try again.");
            }
            report = data;
            status.textContent = `Preview for ${data.portfolio.name} (portfolio ${portfolioId}): `
                + `${data.would_add} would add, ${data.skipped} skipped, ${data.errors} errors. `
                + "Nothing saved. Holdings may change after this snapshot.";
            renderPage();
            heading.focus();
        } catch (error) {
            if (request === generation && workspace.id === portfolioId) {
                status.textContent = `Nothing saved. ${error.message || "Preview failed. Please try again."}`;
                heading.focus();
            }
        } finally {
            if (request === generation) {
                controller = null;
                choose.disabled = false;
                result.setAttribute("aria-busy", "false");
                if (workspace.id !== portfolioId) cancel(false);
            }
        }
    }

    choose.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
        const file = input.files?.[0];
        input.value = "";
        start(file);
    });
    document.getElementById("csv-preview-close").addEventListener("click", () => cancel());
    previous.addEventListener("click", () => { if (page > 0) { page -= 1; renderPage(); } });
    next.addEventListener("click", () => {
        if (report && (page + 1) * 25 < report.rows.length) { page += 1; renderPage(); }
    });
    return { start, cancel };
});
