"""Tests for the cold-start boot splash.

Static-assertion style, like the other UI tests here.

The splash exists for the one case the caches can't cover: a genuinely cold
load, where there is no stale portfolio to paint and the backend is doing real
work. Everything about it is built so it can't become a lie — the progress
tracks the promises initDashboard already awaits, it never gates on the optional
AI phase, and it releases on a timer if the backend hangs.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js() -> str:
    return (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")


def _css() -> str:
    return (ROOT / "static/css/style.css").read_text(encoding="utf-8")


def _html() -> str:
    return (ROOT / "templates/index.html").read_text(encoding="utf-8")


def _init() -> str:
    return _js().split("async function initDashboard")[1][:3000]


# ── Honesty ───────────────────────────────────────────────────────────────────

def test_progress_tracks_the_promises_the_dashboard_already_awaits():
    """A bar that finishes before the data arrives is worse than no bar."""
    init = _init()
    assert 'splash.complete("prices")' in init
    assert 'splash.complete("market")' in init
    # `finally`, not `then`: a failed fetch must still release the overlay so the
    # dashboard can show its own error state.
    assert ".finally(() => splash.complete" in init


def test_dismissal_is_not_gated_on_the_optional_ai_phase():
    # A blank ANTHROPIC_API_KEY is a supported configuration, so the idle-phase
    # work may never complete. Waiting on it would strand the user forever.
    init = _init()
    finish = init.index("splash.complete(\"holdings\").finish()")
    idle = init.index("scheduleWhenIdle(")
    assert finish < idle, "the splash must be released before the idle phase"


def test_a_hung_backend_cannot_strand_the_user():
    body = _js().split("const BootSplash =")[1][:6000]
    assert "this.finish()" in body
    assert "8000" in body, "no hard timeout found"


def test_a_warm_load_gets_a_grace_period_instead_of_a_flash():
    # After the caches land, a switch repaints almost immediately. An overlay
    # over already-painted content would be a regression, so a warm start waits.
    body = _js().split("const BootSplash =")[1][:6000]
    assert "begin(warm)" in body
    assert "setTimeout(show, 300)" in body
    assert "BootSplash.begin(painted)" in _init()


def test_the_splash_is_skippable():
    body = _js().split("const BootSplash =")[1][:6000]
    assert 'e.key === "Escape"' in body
    assert "boot-splash-skip" in body
    assert 'id="boot-splash-skip"' in _html()


# ── Content ───────────────────────────────────────────────────────────────────

def test_every_fact_carries_a_figure_and_a_body():
    js = _js()
    block = js.split("const SPLASH_FACTS = [")[1].split("\n];")[0]
    assert block.count("figure:") == 13
    assert block.count("body:") == 13


def test_one_fact_per_boot_advances_across_sessions():
    # Most sessions are over in seconds, so rotating mid-load would just truncate
    # the first fact. Persisting the index makes the set a sequence instead.
    js = _js()
    assert 'SPLASH_FACT_KEY = "folioorb-splash-fact-v1"' in js
    body = js.split("function pickFact")[1][:600]
    assert "% SPLASH_FACTS.length" in body


def test_the_greeting_avoids_claude_specific_voice():
    # At boot we don't know whether Claude is reachable, and Senpai's Claude-mode
    # register would be a lie if it isn't.
    block = _js().split("const SPLASH_GREETINGS = [")[1].split("\n];")[0]
    assert "Claude" not in block
    assert block.count("Senpai") >= 3


# ── Presentation ──────────────────────────────────────────────────────────────

def test_the_overlay_outranks_the_apps_z_index_scale():
    # nav 11000, popovers 12000, action dialogs 13000. A splash any of those
    # punch through is not a splash.
    css = _css()
    block = css.split("body > .boot-splash {")[1][:600]
    assert "z-index: 14000" in block
    # A bare `.boot-splash` loses to `body > :not(.bg-orb)`, which sets
    # position: relative and would drop the overlay into the page flow.
    assert "body > .boot-splash {" in css


def test_meaningful_colour_uses_theme_aware_accents_not_brand_chrome():
    # --brand-cyan is #6fd6f0 in *both* themes, so it lands near 1.6:1 on the
    # light background. The house rule is brand for chrome, accents for meaning.
    # Match declarations, not the comments explaining them — the rationale
    # naturally names the token it is steering away from.
    def _declarations(block: str) -> list[str]:
        lines = []
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith(("/*", "*")) or not stripped:
                continue
            lines.append(stripped)
            if stripped.startswith("}"):
                break
        return lines

    figure = _declarations(_css().split(".boot-splash-figure {")[1])
    gradient = [line for line in figure if line.startswith("background:")]
    assert gradient, "no background declaration on the figure"
    assert "--accent-cyan" in gradient[0]
    assert "--brand-" not in gradient[0]

    # [-1]: the selector also appears in the shared track/fill rule above, whose
    # body carries stroke-width but not the stroke colour.
    fill = _declarations(_css().split(".boot-splash-curve-fill {")[-1])
    stroke = [line for line in fill if line.startswith("stroke:")]
    assert stroke and "--accent-cyan" in stroke[0]
    assert not any("--brand-" in line for line in fill)


def test_reduced_motion_is_respected():
    css = _css()
    block = css.split(".boot-splash-skip:focus-visible")[1]
    assert "prefers-reduced-motion" in block
    assert ".boot-splash-curve-fill" in block.split("prefers-reduced-motion")[1]


def test_the_progress_element_is_announced():
    html = _html()
    assert 'role="progressbar"' in html
    assert 'aria-valuenow="0"' in html
    assert 'aria-live="polite"' in html
    # aria-valuenow has to move, or the role is decoration.
    assert 'setAttribute("aria-valuenow"' in _js()


def test_the_curve_is_normalised_so_progress_is_just_a_percentage():
    assert 'pathLength="100"' in _html()
    assert "strokeDashoffset" in _js()
