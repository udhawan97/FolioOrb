"""Guards for the userflow-audit fixes.

Three of these lock in behaviour that a browser exercised and found wrong; the
fourth pins the shape of the ticker `pattern` so the invalid-regex regression
cannot come back the moment someone "tidies" the escape away.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates/index.html").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static/css/style.css").read_text(encoding="utf-8")


# ── Ticker pattern ────────────────────────────────────────────────────────────
#
# `pattern` is compiled with the RegExp `v` flag, where a literal `-` inside a
# character class must be escaped. The unescaped form parsed fine for years under
# `u`, so the breakage is silent: the browser logs a console error and then drops
# the attribute entirely, taking the whole client-side format check with it.


def test_ticker_pattern_escapes_the_literal_dash():
    match = re.search(r'id="new-ticker"[^>]*?pattern="([^"]+)"', INDEX, re.S)
    assert match, "ticker input lost its pattern attribute"
    assert match.group(1) == r"[A-Za-z0-9.^\-]{1,10}"


def test_ticker_pattern_compiles_under_v_mode_semantics():
    # Python has no `v` flag, but the rule that trips it is specific and testable:
    # a bare `-` that is not forming a range and is not escaped.
    match = re.search(r'id="new-ticker"[^>]*?pattern="([^"]+)"', INDEX, re.S)
    body = match.group(1)
    inner = body[body.index("[") + 1:body.index("]")]
    unescaped_trailing_dash = inner.endswith("-") and not inner.endswith(r"\-")
    assert not unescaped_trailing_dash, (
        "a literal '-' must be escaped for the v-flag parser: " + inner
    )


# ── Add-holding error announcement ────────────────────────────────────────────


def test_add_message_is_a_live_region():
    match = re.search(r'<span id="add-msg"[^>]*>', INDEX)
    assert match, "#add-msg missing"
    tag = match.group(0)
    assert 'role="status"' in tag
    assert 'aria-live="polite"' in tag


def test_ticker_input_points_at_its_error_message():
    match = re.search(r'id="new-ticker"[^>]*?>', INDEX, re.S)
    assert 'aria-describedby="add-msg"' in match.group(0)


# ── Welcome guide is a real modal ─────────────────────────────────────────────
#
# It paints a full-viewport pointer-blocking layer. Without a focus trap the
# first screen a new user sees is reachable only after tabbing through every
# control on the dashboard behind it.


def test_welcome_guide_marks_the_background_inert_on_open():
    show = DASHBOARD[DASHBOARD.index("function maybeShowSenpaiWelcomeGuide"):]
    show = show[:show.index("\n}\n")]
    assert "element.inert = true" in show
    assert '_senpaiWelcomePreviousFocus = document.activeElement' in show
    assert 'guide.setAttribute("aria-modal", "true")' in show
    assert "handleSenpaiWelcomeKeydown" in show


def test_welcome_guide_restores_focus_and_clears_inert_on_close():
    close = DASHBOARD[DASHBOARD.index("function closeSenpaiWelcomeGuide"):]
    close = close[:close.index("\n}\n")]
    assert "_senpaiWelcomeBackgroundState.forEach" in close
    assert "_senpaiWelcomeBackgroundState.clear()" in close
    assert "previousFocus?.focus" in close
    assert 'guide.setAttribute("aria-modal", "false")' in close


def test_welcome_guide_traps_tab_and_escape():
    assert "function handleSenpaiWelcomeKeydown" in DASHBOARD
    trap = DASHBOARD[DASHBOARD.index("function handleSenpaiWelcomeKeydown"):]
    trap = trap[:trap.index("\n}\n")]
    assert 'event.key === "Escape"' in trap
    assert 'event.key !== "Tab"' in trap
    # wraps in both directions
    assert "event.shiftKey && document.activeElement === first" in trap
    assert "!event.shiftKey && document.activeElement === last" in trap


# ── Senpai bubble stops covering the panel underneath ─────────────────────────


def test_desktop_senpai_bubble_settles_when_idle():
    assert "@media (min-width: 576px)" in STYLE
    rule = ".dashboard-senpai:not(.is-expanded):not(.is-texting) .dashboard-senpai-bubble"
    assert rule in STYLE
    block = STYLE[STYLE.index(rule):]
    block = block[:block.index("}")]
    assert "opacity: 0" in block
    assert "pointer-events: none" in block


def test_new_quips_reopen_the_bubble_for_a_readable_dwell():
    assert "function revealBubbleForDwell" in DASHBOARD
    assert "SENPAI_BUBBLE_DWELL_MS" in DASHBOARD
    # both the rotation path and the direct-speak path must reveal
    for fn in ("function showQuote", "function speak"):
        body = DASHBOARD[DASHBOARD.index(fn):]
        body = body[:body.index("\n    }\n")]
        assert "revealBubbleForDwell()" in body, f"{fn} does not reveal the bubble"
