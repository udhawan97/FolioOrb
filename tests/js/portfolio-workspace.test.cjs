const test = require("node:test");
const assert = require("node:assert/strict");

const { createPortfolioWorkspace } = require("../../static/js/portfolio-workspace.js");

function storageWith(value = null) {
    const values = new Map();
    if (value !== null) values.set("folioorb-active-portfolio", String(value));
    return {
        getItem: key => values.get(key) ?? null,
        setItem: (key, next) => values.set(key, String(next)),
    };
}

test("hydrates identity and replaces stale literal portfolio ids", async () => {
    const calls = [];
    const workspace = createPortfolioWorkspace({
        fetchFn: async (url, init) => {
            calls.push([url, init]);
            return new Response(JSON.stringify({ ok: true }), { status: 200 });
        },
        storage: storageWith(7),
        reload: () => {},
        origin: "http://folio.test",
    });

    assert.equal(workspace.id, 7);
    await workspace.json("/api/dca/plans?portfolio_id=1");
    assert.equal(calls[0][0], "/api/dca/plans?portfolio_id=7");
});

test("scopes a local CSV import without corrupting its existing query", async () => {
    const calls = [];
    const workspace = createPortfolioWorkspace({
        fetchFn: async url => {
            calls.push(url);
            return new Response("{}", { status: 200 });
        },
        storage: storageWith(7),
        reload: () => {},
        origin: "http://folio.test",
    });

    await workspace.response(
        "/api/portfolio/holdings/import?force_local=true",
        { method: "POST" },
    );

    assert.equal(
        calls[0],
        "/api/portfolio/holdings/import?force_local=true&portfolio_id=7",
    );
});

test("passes global endpoints without portfolio identity", async () => {
    const calls = [];
    const workspace = createPortfolioWorkspace({
        fetchFn: async url => {
            calls.push(url);
            return new Response("{}", { status: 200 });
        },
        storage: storageWith(3),
        reload: () => {},
        origin: "http://folio.test",
    });

    await workspace.response("/api/updates/status");
    await workspace.response("https://other.test/api/portfolio/value");
    assert.deepEqual(calls, [
        "/api/updates/status",
        "https://other.test/api/portfolio/value",
    ]);
});

test("cache keys isolate endpoint and query variants within one portfolio", async () => {
    let calls = 0;
    const workspace = createPortfolioWorkspace({
        fetchFn: async url => {
            calls += 1;
            return new Response(JSON.stringify({ url }), { status: 200 });
        },
        storage: storageWith(2),
        reload: () => {},
        origin: "http://folio.test",
    });

    const [first, duplicate, second, variant] = await Promise.all([
        workspace.cached("/api/portfolio/value"),
        workspace.cached("/api/portfolio/value"),
        workspace.cached("/api/portfolio/holdings"),
        workspace.cached("/api/portfolio/value?period=month"),
    ]);
    assert.equal(calls, 3);
    assert.deepEqual(first, duplicate);
    assert.notEqual(first.url, second.url);
    assert.notEqual(first.url, variant.url);
});

test("cache normalizes equivalent query parameter order", async () => {
    let calls = 0;
    const workspace = createPortfolioWorkspace({
        fetchFn: async url => {
            calls += 1;
            return new Response(JSON.stringify({ url }), { status: 200 });
        },
        storage: storageWith(2),
        reload: () => {},
        origin: "http://folio.test",
    });

    const [first, second] = await Promise.all([
        workspace.cached("/api/portfolio/value?range=month&mode=local"),
        workspace.cached("/api/portfolio/value?mode=local&range=month"),
    ]);

    assert.equal(calls, 1);
    assert.deepEqual(first, second);
});

test("successful mutation invalidates cache while failed mutation does not", async () => {
    let valueCalls = 0;
    let mutationStatus = 500;
    const workspace = createPortfolioWorkspace({
        fetchFn: async (url, init = {}) => {
            if (url.startsWith("/api/portfolio/value")) {
                valueCalls += 1;
                return new Response(JSON.stringify({ valueCalls }), { status: 200 });
            }
            return new Response("{}", { status: mutationStatus });
        },
        storage: storageWith(4),
        reload: () => {},
        origin: "http://folio.test",
    });

    await workspace.cached("/api/portfolio/value");
    await workspace.response("/api/portfolio/holdings/1", { method: "PUT" });
    await workspace.cached("/api/portfolio/value");
    assert.equal(valueCalls, 1);

    mutationStatus = 200;
    await workspace.response("/api/portfolio/holdings/1", { method: "PUT" });
    await workspace.cached("/api/portfolio/value");
    assert.equal(valueCalls, 2);
});

test("a rejected cached read is evicted so the next read can recover", async () => {
    let calls = 0;
    const workspace = createPortfolioWorkspace({
        fetchFn: async () => {
            calls += 1;
            if (calls === 1) throw new Error("offline");
            return new Response(JSON.stringify({ recovered: true }), { status: 200 });
        },
        storage: storageWith(4),
        reload: () => {},
        origin: "http://folio.test",
    });

    await assert.rejects(workspace.cached("/api/portfolio/value"), /offline/);
    assert.deepEqual(
        await workspace.cached("/api/portfolio/value"),
        { recovered: true },
    );
    assert.equal(calls, 2);
});

test("selection clears cached state, persists, and reloads", async () => {
    const storage = storageWith(1);
    let reloads = 0;
    const workspace = createPortfolioWorkspace({
        fetchFn: async url => new Response(JSON.stringify({ url }), { status: 200 }),
        storage,
        reload: () => { reloads += 1; },
        origin: "http://folio.test",
    });
    await workspace.cached("/api/portfolio/value");

    assert.equal(workspace.select(9), true);
    assert.equal(workspace.id, 9);
    assert.equal(storage.getItem("folioorb-active-portfolio"), "9");
    assert.equal(reloads, 1);
});

test("json rejects non-success responses with FastAPI detail", async () => {
    const workspace = createPortfolioWorkspace({
        fetchFn: async () => new Response(
            JSON.stringify({ detail: "Portfolio not found" }),
            { status: 404 },
        ),
        storage: storageWith(1),
        reload: () => {},
        origin: "http://folio.test",
    });

    await assert.rejects(
        workspace.json("/api/portfolio/value"),
        /Portfolio not found/,
    );
});
