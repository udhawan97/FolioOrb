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
    assert "/static/js/review-orbit.js?v=3" in markup
    assert "/static/css/review-orbit.css?v=1" in markup
    assert "setBackgroundInert(true)" in script
    assert 'event.key === "Escape"' in script
    assert "prefers-reduced-motion: reduce" in styles
    assert "@media (max-width: 575.98px)" in styles


def test_review_orbit_covers_all_six_feature_contracts():
    markup = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "review-orbit.js").read_text(encoding="utf-8")

    for phrase in (
        "Data Trust Center",
        "Local Backup Vault",
        "Review inbox",
        "Monthly review pack",
        "Review cadence",
        "Watchlist compare",
    ):
        assert phrase in markup
    assert "/api/review/trust" in script
    assert "/api/review/backups" in script
    assert "/api/review/report" in script
    assert "/api/review/compare" in script
    assert "/api/review/thesis/" in script
