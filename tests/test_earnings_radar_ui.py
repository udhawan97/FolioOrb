"""Wiring checks: the earnings radar is connected across API, JS, HTML, and CSS."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_earnings_radar_wired_end_to_end():
    router = (ROOT / "app/routers/portfolio.py").read_text(encoding="utf-8")
    js = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

    # Backend endpoint + service
    assert '@router.get("/earnings")' in router
    assert "get_earnings_events" in router

    # Frontend: fetch, load/render/badge functions, and both wire-in points
    assert "/api/portfolio/earnings" in js
    assert "loadEarningsRadar" in js
    assert "earningsBadgeHtml" in js
    assert "renderEarningsStrip" in js

    # HTML container + CSS hooks
    assert 'id="earnings-radar-strip"' in html
    assert ".earnings-radar-strip" in css
    assert ".earnings-badge" in css
