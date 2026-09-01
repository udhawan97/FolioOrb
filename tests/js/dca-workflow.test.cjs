const test = require("node:test");
const assert = require("node:assert/strict");

const { createDcaWorkflow } = require("../../static/js/dca-workflow.js");

function element(overrides = {}) {
    return {
        hidden: false,
        dataset: {},
        innerHTML: "",
        textContent: "",
        setAttribute() {},
        addEventListener() {},
        ...overrides,
    };
}

function fakeDocument() {
    const elements = new Map([
        ["dca-panel", element({ hidden: true })],
        ["dca-btn", element()],
        ["dca-plans-section", element()],
        ["dca-plans-list", element()],
        ["dca-pending-section", element()],
        ["dca-pending-list", element()],
        ["dca-badge", element()],
        ["dca-history-list", element({ hidden: true })],
    ]);
    return {
        elements,
        activeElement: null,
        getElementById: id => elements.get(id) || null,
        addEventListener() {},
        querySelector() { return null; },
    };
}

function actionEvent(dataset) {
    return { target: { closest: () => ({ dataset }) } };
}

function emptyWorkspace(overrides = {}) {
    return {
        json: async url => url.includes("plans")
            ? { plans: [] }
            : { contributions: [] },
        response: async () => new Response("{}", { status: 200 }),
        ...overrides,
    };
}

test("open is the navigation seam and loads the panel through the workspace", async () => {
    const document = fakeDocument();
    const requests = [];
    let managerOpens = 0;
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            json: async url => {
                requests.push(url);
                return url.includes("plans") ? { plans: [] } : { contributions: [] };
            },
        }),
        document,
        openManager: () => { managerOpens += 1; },
    });

    assert.equal(workflow.open(), true);
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(managerOpens, 1);
    assert.equal(document.elements.get("dca-panel").hidden, false);
    assert.deepEqual(requests.slice(0, 2), [
        "/api/dca/plans",
        "/api/dca/contributions?status=pending",
    ]);
});

test("one mutation in flight blocks a double apply", async () => {
    const document = fakeDocument();
    let resolveMutation;
    let mutationCalls = 0;
    const pending = new Promise(resolve => { resolveMutation = resolve; });
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => {
                mutationCalls += 1;
                return pending;
            },
        }),
        document,
    });
    const event = actionEvent({ dcaAction: "apply", cid: "3" });

    const first = workflow.handleAction(event);
    const second = await workflow.handleAction(event);
    assert.equal(second, null);
    assert.equal(mutationCalls, 1);

    resolveMutation(new Response(JSON.stringify({ message: "Applied" }), { status: 200 }));
    await first;
});

test("cancelling a bulk action sends no mutation", async () => {
    let mutations = 0;
    let prompt = null;
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => {
                mutations += 1;
                return new Response("{}", { status: 200 });
            },
        }),
        document: fakeDocument(),
        confirmAction: async value => { prompt = value; return null; },
    });

    const result = await workflow.handleAction(actionEvent({
        dcaAction: "apply-all",
        planId: "7",
        count: "2",
        total: "50",
        ticker: "AAPL",
    }));

    assert.equal(result, null);
    assert.equal(mutations, 0);
    assert.match(prompt.warning, /later sales or edits can block reversal/);
});

test("failed action reports the error without refreshing holdings", async () => {
    const messages = [];
    let refreshes = 0;
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => new Response(
                JSON.stringify({ detail: "Already applied" }),
                { status: 400 },
            ),
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
        holdingsChanged: async () => { refreshes += 1; },
    });

    await workflow.handleAction(actionEvent({ dcaAction: "apply", cid: "3" }));

    assert.equal(refreshes, 0);
    assert.deepEqual(messages[0], ["Already applied", "danger"]);
});

test("legacy plan is visibly blocked and has no financial action controls", async () => {
    const document = fakeDocument();
    const legacy = {
        id: 9,
        ticker: "LEGACY",
        amount: 50,
        frequency: "weekly",
        is_active: true,
        next_date: null,
        applied_count: 0,
        applied_amount: 0,
        applied_shares: 0,
        applied_avg_cost: null,
        currency_status: "needs_currency",
        currency_message: "Undo applied buys if needed, then delete this plan. Create a replacement only after FolioOrb verifies an explicit USD quote.",
    };
    const pending = {
        id: 17,
        plan_id: 9,
        ticker: "LEGACY",
        exec_date: "2026-06-12",
        shares: 0.5,
        price: 100,
        amount: 50,
    };
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            json: async url => url.includes("plans")
                ? { plans: [legacy] }
                : { contributions: [pending] },
        }),
        document,
    });

    workflow.open();
    await new Promise(resolve => setImmediate(resolve));

    const planHtml = document.elements.get("dca-plans-list").innerHTML;
    const pendingHtml = document.elements.get("dca-pending-list").innerHTML;
    assert.match(planHtml, /Needs currency verification/);
    assert.match(planHtml, /Undo applied buys if needed, then delete this plan/);
    assert.match(planHtml, /Create a replacement only after FolioOrb verifies/);
    assert.doesNotMatch(planHtml, /Next buy/);
    assert.doesNotMatch(planHtml, /data-dca-action="edit-plan"/);
    assert.match(planHtml, /data-dca-action="delete-plan"/);
    assert.doesNotMatch(pendingHtml, /data-dca-action="apply"/);
    assert.doesNotMatch(pendingHtml, /data-dca-action="apply-all"/);
    assert.match(pendingHtml, /Currency verification required/);
    assert.match(pendingHtml, /data-dca-action="skip"/);
});

test("catch-up HTTP failure is reported instead of silently swallowed", async () => {
    const messages = [];
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => new Response(
                JSON.stringify({ detail: "Catch-up unavailable" }),
                { status: 409 },
            ),
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
    });

    workflow.init();
    await new Promise(resolve => setImmediate(resolve));

    assert.deepEqual(messages[0], ["Catch-up unavailable", "danger"]);
});

test("catch-up response loss refreshes state and reports an unknown outcome", async () => {
    const messages = [];
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => { throw new Error("offline"); },
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
    });

    workflow.init();
    await new Promise(resolve => setImmediate(resolve));

    assert.deepEqual(messages[0], [
        "DCA result is still unknown — review the refreshed state before retrying",
        "warning",
    ]);
});

test("lost apply response reconciles a committed contribution and holdings", async () => {
    const messages = [];
    let holdingsRefreshes = 0;
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => { throw new Error("response lost"); },
            json: async url => {
                if (url.includes("plans")) return { plans: [] };
                if (url.includes("status=all")) {
                    return { contributions: [{ id: 3, status: "applied" }] };
                }
                return { contributions: [] };
            },
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
        holdingsChanged: async () => { holdingsRefreshes += 1; },
    });

    const result = await workflow.handleAction(
        actionEvent({ dcaAction: "apply", cid: "3" })
    );

    assert.equal(result, null);
    assert.equal(holdingsRefreshes, 1);
    assert.deepEqual(messages.at(-1), [
        "DCA action completed — refreshed from saved state",
        "success",
    ]);
});

test("lost apply response reports a proven unchanged contribution", async () => {
    const messages = [];
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => { throw new Error("response lost"); },
            json: async url => {
                if (url.includes("plans")) return { plans: [] };
                if (url.includes("status=all")) {
                    return { contributions: [{ id: 3, status: "pending" }] };
                }
                return { contributions: [] };
            },
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
    });

    await workflow.handleAction(actionEvent({ dcaAction: "apply", cid: "3" }));

    assert.deepEqual(messages.at(-1), [
        "DCA action did not complete — saved state is unchanged",
        "warning",
    ]);
});

test("lost bulk-apply response reconciles the plan counters and holdings", async () => {
    const messages = [];
    let holdingsRefreshes = 0;
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => { throw new Error("response lost"); },
            json: async url => url.includes("plans")
                ? { plans: [{ id: 7, pending_count: 0, applied_count: 2 }] }
                : { contributions: [] },
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
        holdingsChanged: async () => { holdingsRefreshes += 1; },
        confirmAction: async () => ({ confirmed: true }),
    });

    await workflow.handleAction(actionEvent({
        dcaAction: "apply-all",
        planId: "7",
        count: "2",
        total: "100",
        ticker: "VOO",
    }));

    assert.equal(holdingsRefreshes, 1);
    assert.deepEqual(messages.at(-1), [
        "DCA action completed — refreshed from saved state",
        "success",
    ]);
});

test("lost patch response reconciles the saved plan state", async () => {
    const messages = [];
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => { throw new Error("response lost"); },
            json: async url => url.includes("plans")
                ? { plans: [{ id: 7, is_active: false }] }
                : { contributions: [] },
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
    });

    await workflow.handleAction(actionEvent({
        dcaAction: "toggle-plan",
        planId: "7",
        active: "true",
    }));

    assert.deepEqual(messages.at(-1), [
        "DCA action completed — refreshed from saved state",
        "success",
    ]);
});

test("lost delete response reconciles an absent plan as committed", async () => {
    const messages = [];
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => { throw new Error("response lost"); },
            json: async url => url.includes("plans")
                ? { plans: [] }
                : { contributions: [] },
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
        confirmAction: async () => ({ confirmed: true }),
    });

    await workflow.handleAction(actionEvent({
        dcaAction: "delete-plan",
        planId: "7",
        ticker: "VOO",
    }));

    assert.deepEqual(messages.at(-1), [
        "DCA action completed — refreshed from saved state",
        "success",
    ]);
});

test("failed reconciliation keeps a lost mutation outcome unknown", async () => {
    const messages = [];
    const workflow = createDcaWorkflow({
        workspace: emptyWorkspace({
            response: async () => { throw new Error("response lost"); },
            json: async () => { throw new Error("still offline"); },
        }),
        document: fakeDocument(),
        notify: (...args) => messages.push(args),
    });

    await workflow.handleAction(actionEvent({ dcaAction: "apply", cid: "3" }));

    assert.deepEqual(messages.at(-1), [
        "DCA result is unknown — reconnect and refresh before retrying",
        "warning",
    ]);
});
