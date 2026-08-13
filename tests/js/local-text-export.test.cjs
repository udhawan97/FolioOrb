const test = require("node:test");
const assert = require("node:assert/strict");

const { createLocalTextExport } = require("../../static/js/local-text-export.js");

test("native save preserves one existing CSV BOM", async () => {
    let saved;
    const exporter = createLocalTextExport({
        getNativeSaver: () => async (filename, text) => {
            saved = { filename, text };
            return { saved: true, path: `/tmp/${filename}` };
        },
        browserSaver: () => { throw new Error("browser fallback used"); },
    });
    const bytes = new TextEncoder().encode("\uFEFFticker,name\nAAPL,Apple\n");
    const response = new Response(bytes, {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="facts.csv"' },
    });

    const result = await exporter.saveResponse(response, {
        fallbackFilename: "fallback.csv",
        mediaType: "text/csv;charset=utf-8",
    });

    assert.equal(result.status, "saved");
    assert.equal(saved.filename, "facts.csv");
    assert.equal(saved.text.charCodeAt(0), 0xFEFF);
    assert.notEqual(saved.text.charCodeAt(1), 0xFEFF);
});

test("native cancellation is terminal and never falls back", async () => {
    let browserCalls = 0;
    const exporter = createLocalTextExport({
        getNativeSaver: () => async () => ({ saved: false, path: null }),
        browserSaver: () => { browserCalls += 1; },
    });

    const result = await exporter.saveText(
        "facts.csv", "ticker\nAAPL\n", "text/csv;charset=utf-8"
    );
    assert.equal(result.status, "cancelled");
    assert.equal(browserCalls, 0);
});

test("native failure throws and never falls back", async () => {
    let browserCalls = 0;
    const exporter = createLocalTextExport({
        getNativeSaver: () => async () => ({ saved: false, error: "OSError" }),
        browserSaver: () => { browserCalls += 1; },
    });

    await assert.rejects(
        exporter.saveText("facts.csv", "x", "text/csv"),
        /OSError/,
    );
    assert.equal(browserCalls, 0);
});

test("browser response save preserves exact bytes and sanitizes filename", async () => {
    let saved;
    const exporter = createLocalTextExport({
        getNativeSaver: () => null,
        browserSaver: payload => { saved = payload; },
    });
    const bytes = Uint8Array.from([0xEF, 0xBB, 0xBF, 0xCE, 0xB1, 0x0A]);
    const response = new Response(bytes, {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="../unsafe.csv"' },
    });

    const result = await exporter.saveResponse(response, {
        fallbackFilename: "fallback.csv",
        mediaType: "text/csv;charset=utf-8",
    });

    assert.equal(result.status, "saved");
    assert.equal(saved.filename, "unsafe.csv");
    assert.deepEqual(Array.from(saved.content), Array.from(bytes));
});

test("non-success response is rejected before any save", async () => {
    let saves = 0;
    const exporter = createLocalTextExport({
        getNativeSaver: () => null,
        browserSaver: () => { saves += 1; },
    });

    await assert.rejects(
        exporter.saveResponse(new Response("no", { status: 500 }), {
            fallbackFilename: "facts.csv",
            mediaType: "text/csv",
        }),
        /HTTP 500/,
    );
    assert.equal(saves, 0);
});
