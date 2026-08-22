"""Regression contracts for the v5.8 workspace-continuity fixes."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _sources() -> tuple[str, str, str]:
    return (
        (ROOT / "templates/index.html").read_text(encoding="utf-8"),
        (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8"),
        (ROOT / "static/css/style.css").read_text(encoding="utf-8"),
    )


def test_theme_and_dashboard_zone_restore_from_storage():
    html, js, _css = _sources()

    assert 'localStorage.getItem("folioorb-theme")' in html
    assert 'applyTheme(currentTheme(), false)' in js
    zone_init = js.split("function initDashboardZones()", maxsplit=1)[1][:650]
    assert "localStorage.getItem(DASHBOARD_ZONE_KEY)" in zone_init
    assert "DASHBOARD_ZONES.includes(saved)" in zone_init


def test_portfolio_manager_is_modal_and_owns_keyboard_focus():
    html, js, css = _sources()
    manager = html.split('id="portfolioModal"', maxsplit=1)[1][:180]

    assert 'aria-modal="true"' in manager
    assert "FolioModalSurface.open(popover" in js
    assert "portfolioManagerFallbackFocus" in js
    assert "_portfolioManagerModal" in js
    assert 'document.body.classList.add("portfolio-manager-open")' in js
    assert "body.portfolio-manager-open" in css


def test_research_ideas_do_not_fill_invested_overview_or_projection_ui():
    html, js, _css = _sources()

    assert "const investedHoldings = data.holdings.filter" in js
    assert "!h.is_watchlist && toNumber(h.shares) > 0" in js
    assert "summary.hidden = !latestProjectionData.has_holdings" in js
    assert "S&P 500 index: ${spyIdx[idx].toFixed(1)}" in js
    assert "S&amp;P 500 as an index (100 = start), not a dollar portfolio" in html


def test_narrow_layout_contains_nav_and_zone_controls():
    html, js, css = _sources()

    mobile = css.rsplit("@media (max-width: 575.98px)", maxsplit=1)[1]
    assert 'id="nav-live-feed"' in html
    assert "mobileTrigger?.addEventListener" in js
    assert ".navbar .container-fluid" in mobile
    assert "min-width: 0" in mobile
    assert ".hud-status-pill" in mobile
    assert ".portfolio-switcher-menu" in mobile
    assert ".dashboard-zone-tabs-wrap { overflow: hidden; }" in mobile
