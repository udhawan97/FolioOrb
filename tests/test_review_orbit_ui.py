"""Static wiring and accessibility contract for the Review Orbit."""
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_review_orbit_is_wired_as_one_accessible_workspace():
    markup = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "review-orbit.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "css" / "review-orbit.css").read_text(encoding="utf-8")

    assert 'id="review-orbit"' in markup
    assert 'aria-modal="true"' in markup
    assert 'role="tablist"' in markup
    assert "/static/js/review-orbit.js?v=" in markup
    assert "/static/css/review-orbit.css?v=" in markup
    # Containment now comes from the shared modal seam rather than a private
    # copy, so the assertion follows it there.
    assert "FolioModalSurface.open(root" in script
    assert "onEscape" in script
    assert "function onEscape()" in script
    assert "prefers-reduced-motion: reduce" in styles
    assert "@media (max-width: 575.98px)" in styles


def test_review_orbit_covers_review_and_plan_protect_contracts():
    markup = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "review-orbit.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "css" / "review-orbit.css").read_text(encoding="utf-8")

    for phrase in (
        "Data Trust Center",
        "Local Backup Vault",
        "Review inbox",
        "Monthly review pack",
        "Review cadence",
        "Watchlist compare",
        "Plan &amp; protect",
        "Portfolio plan",
        "Annual average-cost recap",
        "Portable records ZIP",
        "Manual-backup freshness",
    ):
        assert phrase in markup
    assert "/api/review/trust" in script
    assert "/api/review/backups" in script
    assert "/api/review/report" in script
    assert "/api/review/compare" in script
    assert "/api/review/thesis/" in script
    assert "/api/review/plan" in script
    assert "/api/review/overview" in script
    assert "/api/review/records/realized.csv" in script
    assert "/api/review/records/archive" in script
    assert "/api/review/backups/policy" in script
    assert "review-course-ring" in styles
    assert "not a tax form" in markup
    assert "not a FolioOrb restore file" in markup
    assert "Average-cost recap export failed; no complete file was written." in script
    assert "Portable records export failed; no complete ZIP was written." in script
    assert 'requestAnimationFrame(() => $("review-auto-switch")?.focus())' in script
    assert 'timeZoneName: "short"' in script


def test_review_orbit_root_wins_the_global_body_child_stacking_rule():
    styles = (ROOT / "static" / "css" / "review-orbit.css").read_text(encoding="utf-8")

    root_rule = styles.split("body > .review-orbit", 1)[1].split("}", 1)[0]
    assert "position: fixed" in root_rule
    assert "z-index: 11500" in root_rule

    # Fixed dashboard utilities must not leak above the modal workspace even if
    # their own stacking values change later.
    assert "body.review-orbit-open > .holding-expand-fab" in styles
    assert "body.review-orbit-open > .dashboard-senpai" in styles
    assert "visibility: hidden" in styles
