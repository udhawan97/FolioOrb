"""The dashboard must not reach a CDN to render.

This ships as a PyInstaller desktop app. Two render-blocking stylesheets and a
parser-blocking script were being pulled from cdn.jsdelivr.net, so a cold start
paid DNS, TLS and six cross-origin round-trips before first paint — and offline
the app blocked on stylesheets that could never arrive, while the icon font
those stylesheets pull backs the glyphs inside the portfolio switcher itself.

The spec bundles the whole `static/` tree, so vendored files ship with the
frozen app without a packaging change.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "static/vendor"


def _html() -> str:
    return (ROOT / "templates/index.html").read_text(encoding="utf-8")


VENDORED = [
    "bootstrap-5.3.2.min.css",
    "bootstrap-5.3.2.bundle.min.js",
    "bootstrap-icons-1.11.1.css",
    "chart-4.4.0.umd.min.js",
    "chartjs-chart-matrix-2.0.1.min.js",
    "chartjs-chart-treemap-3.0.0.min.js",
]


def test_the_dashboard_requests_nothing_from_a_cdn():
    assert "cdn.jsdelivr.net" not in _html()


def test_every_vendored_asset_is_present_and_not_a_stub():
    for name in VENDORED:
        path = VENDOR / name
        assert path.is_file(), f"missing {name}"
        # A failed download that still exits 0 leaves an error page behind.
        assert path.stat().st_size > 2_000, f"{name} looks truncated"


def test_the_page_references_every_vendored_asset():
    html = _html()
    for name in VENDORED:
        assert f"/static/vendor/{name}" in html, f"{name} is vendored but unused"


def test_the_icon_font_files_resolve_from_the_stylesheet():
    """The classic vendoring mistake: the CSS ships, the fonts it names don't.

    bootstrap-icons.css names its faces relative to itself, so they have to sit
    under static/vendor/fonts/. Miss this and every `bi bi-*` glyph in the app
    renders as a blank box — including the check marks in the portfolio switcher.
    """
    css = (VENDOR / "bootstrap-icons-1.11.1.css").read_text(encoding="utf-8")
    referenced = set(re.findall(r'url\("([^"?]+)', css))
    assert referenced, "no font references found — wrong file?"
    for ref in referenced:
        resolved = (VENDOR / ref).resolve()
        assert resolved.is_file(), f"{ref} referenced by the CSS but not vendored"


def test_bootstrap_no_longer_blocks_the_parser():
    # It is used only declaratively here, and the bundle wires data-bs-* on
    # DOMContentLoaded, so there is nothing to gain from blocking.
    html = _html()
    match = re.search(r"<script([^>]*)bootstrap-5\.3\.2\.bundle\.min\.js", html)
    assert match, "bootstrap bundle script tag not found"
    assert "defer" in match.group(1)


def test_chart_js_still_loads_before_its_consumers():
    # Deferred scripts run in document order, so the plugins and
    # analytics-charts.js must appear after Chart.js itself.
    # Match on src paths, not bare names: the surrounding comments mention these
    # files too, and a comment is not a load order.
    html = _html()
    chart = html.index("/static/vendor/chart-4.4.0.umd.min.js")
    later_srcs = (
        "/static/vendor/chartjs-chart-matrix-2.0.1.min.js",
        "/static/vendor/chartjs-chart-treemap-3.0.0.min.js",
        "/static/js/analytics-charts.js",
    )
    for src in later_srcs:
        assert chart < html.index(src), f"{src} is ordered before Chart.js"


def test_the_preconnect_hint_is_gone():
    # Nothing is fetched from that origin any more, so the hint would just be a
    # DNS lookup for an unused host.
    assert "preconnect" not in _html()
