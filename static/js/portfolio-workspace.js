/** One active portfolio identity, scoped transport, and identity-aware cache. */
(function installPortfolioWorkspace(root, factory) {
    if (typeof module === "object" && module.exports) {
        module.exports = { createPortfolioWorkspace: factory };
        return;
    }
    root.createPortfolioWorkspace = factory;
    root.PortfolioWorkspace = factory({
        fetchFn: root.fetch.bind(root),
        storage: root.localStorage,
        reload: () => root.location.reload(),
        origin: root.location.origin,
    });
})(typeof window !== "undefined" ? window : globalThis, function createPortfolioWorkspace({
    fetchFn,
    storage,
    reload,
    origin,
    defaultPortfolioId = 1,
}) {
    const ACTIVE_KEY = "folioorb-active-portfolio";
    const SCOPED_PATH = /^\/api\/(portfolio|ai|news|dca|review)\//;
    const cache = new Map();

    function readActiveId() {
        try {
            const saved = Number.parseInt(storage?.getItem(ACTIVE_KEY), 10);
            if (Number.isFinite(saved) && saved > 0) return saved;
        } catch (_) { /* storage is optional; use the stable default */ }
        return defaultPortfolioId;
    }

    let activeId = readActiveId();

    function scopedUrl(input) {
        if (typeof input !== "string") return input;
        try {
            const parsed = new URL(input, origin);
            if (parsed.origin !== origin || !SCOPED_PATH.test(parsed.pathname)) return input;
            parsed.searchParams.set("portfolio_id", String(activeId));
            parsed.searchParams.sort();
            return input.startsWith("/")
                ? `${parsed.pathname}${parsed.search}${parsed.hash}`
                : parsed.href;
        } catch (_) {
            return input;
        }
    }

    function errorMessage(value, fallback) {
        const detail = value?.detail ?? value?.message ?? value;
        if (Array.isArray(detail)) {
            return detail.map(item => item?.msg || item?.message || String(item)).join("; ")
                || fallback;
        }
        if (detail && typeof detail === "object") {
            return detail.msg || detail.message || JSON.stringify(detail);
        }
        return detail ? String(detail) : fallback;
    }

    async function response(input, init = {}) {
        const method = String(init.method || "GET").toUpperCase();
        const result = await fetchFn(scopedUrl(input), init);
        if (result.ok && method !== "GET" && method !== "HEAD") cache.clear();
        return result;
    }

    async function json(url, init) {
        const result = await response(url, init);
        if (!result.ok) {
            const body = await result.text().catch(() => "");
            let detail = null;
            try { detail = body ? JSON.parse(body) : null; } catch (_) { /* status is enough */ }
            const fallback = `HTTP ${result.status}`;
            const error = new Error(detail === null ? fallback : errorMessage(detail, fallback));
            error.status = result.status;
            error.body = body;
            throw error;
        }
        return result.json();
    }

    function cached(url) {
        const normalized = scopedUrl(url);
        const key = `${activeId}\n${normalized}`;
        const hit = cache.get(key);
        if (hit) return hit.promise;
        const entry = {
            original: String(url),
            promise: json(url).catch(error => {
                cache.delete(key);
                throw error;
            }),
        };
        cache.set(key, entry);
        return entry.promise;
    }

    function invalidate(prefix) {
        if (prefix === undefined || prefix === null) {
            cache.clear();
            return;
        }
        const wanted = String(prefix);
        Array.from(cache.entries())
            .filter(([, entry]) => entry.original.startsWith(wanted))
            .forEach(([key]) => cache.delete(key));
    }

    function select(portfolioId) {
        const next = Number(portfolioId);
        if (!Number.isFinite(next) || next <= 0) {
            throw new TypeError("Portfolio id must be a positive number");
        }
        if (next === activeId) return false;
        activeId = next;
        try { storage?.setItem(ACTIVE_KEY, String(next)); } catch (_) { /* best effort */ }
        cache.clear();
        reload();
        return true;
    }

    function reconcile(portfolios) {
        if (!Array.isArray(portfolios) || portfolios.length === 0) return false;
        if (portfolios.some(portfolio => Number(portfolio.id) === activeId)) return false;
        return select(Number(portfolios[0].id));
    }

    return {
        get id() { return activeId; },
        response,
        json,
        cached,
        invalidate,
        select,
        reconcile,
    };
});
