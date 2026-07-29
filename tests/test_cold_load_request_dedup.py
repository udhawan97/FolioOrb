"""Guards against the cold load re-requesting the same endpoint twice.

A browser trace of a warm cold-load measured 29 requests across 26 endpoints:
`history/batch`, `benchmark-comparison` and `analytics-insights?mode=local` each
went out twice. Three different causes, so three different guards — these tests
pin each one to the mechanism that fixed it, not just to the symptom.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
ANALYTICS = (ROOT / "static/js/analytics-charts.js").read_text(encoding="utf-8")
CORE = (ROOT / "static/js/core.js").read_text(encoding="utf-8")


def _fn(source: str, signature: str) -> str:
    """Return one function body, brace-matched.

    analytics-charts.js lives inside an IIFE, so its functions are indented and a
    naive search for a column-0 `}` runs past the end of the file.
    """
    start = source.index(signature)
    # Walk the parameter list to its closing paren first: refreshDashboardData
    # takes a destructured object, so the first `{` after the name belongs to the
    # parameters, not the body.
    paren = source.index("(", start)
    depth = 0
    for i in range(paren, len(source)):
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
            if depth == 0:
                paren = i
                break
    open_brace = source.index("{", paren)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


# ── The shared primitive these fixes lean on ─────────────────────────────────


def test_the_endpoint_cache_still_coalesces_in_flight_callers():
    # Every fix below assumes concurrent callers share one request. If this
    # helper ever stops memoising, the duplicates come back silently.
    body = _fn(CORE, "function apiGetCached(url)")
    assert "_CORE_ENDPOINT_CACHE.get(url)" in body
    assert "if (hit) return hit" in body
    assert "_CORE_ENDPOINT_CACHE.set(url, pending)" in body


# ── 1. Sparkline history: two renders, one request ───────────────────────────
#
# renderPortfolioValueData runs for the cached payload and again for the live
# one, and each pass asks for trend history.


def test_trend_history_goes_through_the_shared_cache():
    body = _fn(DASHBOARD, "async function loadTrendData(tickers)")
    assert "apiGetCached(" in body, "loadTrendData must share the in-flight promise"
    assert "await apiGet(" not in body, "a private apiGet re-requests per render pass"


def test_a_refresh_drops_the_trend_entry_first():
    # Without this the sparklines would pin the first payload for the session.
    assert 'TREND_HISTORY_URL_PREFIX = "/api/stocks/history/batch"' in DASHBOARD
    body = _fn(DASHBOARD, "function refreshDashboardData({")
    assert "apiGetCached.invalidate(TREND_HISTORY_URL_PREFIX)" in body


def test_both_render_paths_still_share_one_loader():
    # The duplicate is only collapsed because both paths call the same function.
    assert DASHBOARD.count("renderPortfolioValueData(") >= 3  # def + 2 call sites
    body = _fn(DASHBOARD, "function renderPortfolioValueData(data)")
    assert "loadTrendData(tickers)" in body


# ── 2. Benchmark comparison: off raw fetch, onto the cache ───────────────────


def test_benchmark_chart_uses_the_shared_cache_not_raw_fetch():
    body = _fn(ANALYTICS, "async function loadBenchmarkChart()")
    assert "apiGetCached(BENCHMARK_COMPARISON_URL)" in body
    assert 'fetch("/api/portfolio/benchmark-comparison")' not in body


def test_a_refresh_drops_the_benchmark_entry():
    body = _fn(ANALYTICS, "function onRefresh()")
    assert "apiGetCached.invalidate(BENCHMARK_COMPARISON_URL)" in body


# ── 3. Analytics insights: a "changed" handler that fired when nothing did ───
#
# The dashboard re-applies the intelligence mode when the Claude heartbeat
# resolves, ~6s after startup applied the same mode. Too far apart to coalesce,
# so the guard has to be on the handler itself.


def test_the_mode_handler_ignores_a_repeat_of_the_same_mode():
    body = _fn(ANALYTICS, "function onIntelligenceModeChanged()")
    assert "_lastAppliedInsightMode" in body
    assert "if (mode === _lastAppliedInsightMode) return;" in body
    assert "_lastAppliedInsightMode = mode;" in body


def test_a_real_mode_change_still_does_the_work():
    body = _fn(ANALYTICS, "function onIntelligenceModeChanged()")
    # the early return must come before the cache-clearing, not after it
    guard = body.index("_lastAppliedInsightMode) return;")
    assert guard < body.index("_moduleInsightsCache.ai = null")
    assert "loadWidgetInsights(true)" in body, "a genuine switch still force-refetches"


def test_local_insights_go_through_the_shared_cache():
    body = _fn(ANALYTICS, "async function loadWidgetInsights(forceRefresh = false)")
    assert "apiGetCached(ANALYTICS_INSIGHTS_LOCAL_URL)" in body
    assert "if (forceRefresh) apiGetCached.invalidate(ANALYTICS_INSIGHTS_LOCAL_URL)" in body


# ── 4. The paid path deserved the same guard ─────────────────────────────────
#
# loadAiWidgetInsights has two callers that can fire together on a switch into
# AI mode. Its local sibling had an in-flight guard; this one did not, so one
# payload cost two billed Claude calls.


def test_the_claude_insights_loader_has_an_in_flight_guard():
    body = _fn(ANALYTICS, "async function loadAiWidgetInsights(forceRefresh = false)")
    assert "if (_aiModuleInsightsLoading && !forceRefresh) return;" in body
    assert "_aiModuleInsightsLoading = true;" in body
    assert "_aiModuleInsightsLoading = false;" in body, "must clear in finally"
    assert "} finally {" in body, "clearing outside finally strands the flag on error"


def test_both_insight_loaders_declare_their_flags():
    assert "let _moduleInsightsLoading = false;" in ANALYTICS
    assert "let _aiModuleInsightsLoading = false;" in ANALYTICS


# ── Cache-busting ────────────────────────────────────────────────────────────


def test_the_analytics_bundle_was_cache_busted():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    assert "analytics-charts.js?v=19" in html
