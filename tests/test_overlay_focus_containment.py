"""A faded-out overlay must leave the keyboard tab order, not just the pointer's.

Static-assertion style, like tests/test_css_animations.py.

FolioOrb hides popovers, panels and callouts by fading them out: ``opacity: 0``
plus ``pointer-events: none``. That stops the mouse, but neither property removes
an element from the tab order, so controls inside a *closed* overlay stayed
reachable by Tab while invisible on screen and hidden from assistive technology.
Measured on the rendered dashboard, 14 of 47 tab stops were these ghosts — a run
of stops with no visible focus ring, at the tail of the tab order.

``visibility: hidden`` is the narrow fix: it removes the subtree from the tab
order *and* the accessibility tree while keeping the layout box, so popover code
that measures a closed panel still works (``allocationExternalTooltip`` reads
``offsetWidth`` before opening). The exit animation survives because visibility
flips only after the fade finishes (``visibility 0s linear <exit-duration>``).

Two guards, because neither alone is enough
-------------------------------------------
1. **A sweep**, so a *new* faded-out container fails by default: every rule in
   style.css that pairs ``opacity: 0`` with ``pointer-events: none`` must also
   set ``visibility: hidden``, unless named in ``DECORATIVE`` with a reason.
   Its trigger requires **both** properties in one rule body — which is the
   honest limit of a static sweep, and exactly why the second guard exists.
2. **An explicit list** of the rules this release fixed. ``.portfolio-manager-
   panel`` keeps its ``pointer-events: none`` on the *parent* popover, so the
   sweep cannot see it — and that rule covers 13 of the 14 tab stops originally
   measured. Reverting it must fail a test, so it is pinned by name.

An earlier version of this file had only a hand-written list, which is the "list
someone forgot to extend" shape that tests/test_event_loop_safety.py and
tests/test_ticker_path_shape_guard.py argue against; it would not have caught
``.dashboard-senpai.is-hidden`` or the holdings table during an AI scan. A later
version had only the sweep, which silently stopped policing the largest fix in
the release. Both are kept.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Selectors that fade out but can never stand between the user and a control.
# Pseudo-elements cannot contain focusable children at all; the rest are inert
# decoration whose subtree holds no interactive markup.
DECORATIVE = {
    "#holdings-bg-canvas": "bare <canvas> backdrop, no children",
    ".ai-agent-status::before, .ai-agent-status::after": "pseudo-elements",
    ".briefing-card::before": "pseudo-element",
    ".action-plan-card::before": "pseudo-element",
    "body > .fs-update-toast": "status toast built from divs/spans (updates.js)",
    ".market-pulse-card::before": "pseudo-element",
    ".btn-holding-intel::before": "pseudo-element",
    "#tip-popover": "text-only tooltip built from spans",
    "#tip-popover::before": "pseudo-element",
    "#tip-popover::after": "pseudo-element",
    ".card.stat-clickable::before": "pseudo-element",
    ".toast-apple": "status text, dismissed on a timer, no controls",
    ".dashboard-senpai-bubble::before": "pseudo-element",
    ".dashboard-senpai-texting": "typing indicator, three dots",
    ".market-tile::before": "pseudo-element",
    "#allocation-table tr[data-ticker] td:last-child::after": "pseudo-element",
    ".summary-segment::before": "pseudo-element",
    ".intel-loading-overlay": "shimmer overlay, no controls",
    ".intel-verdict.is-revealing::after": "pseudo-element",
    ".ai-scan-ticks": "animated tick marks",
    ".ai-scan-panel": "scan status panel, no controls",
    ".brand-cost-notif": "unread dot",
    ".nav-overflow-menu .brand-cost-callout": "text callout inside an inert menu",
    ".brand-cost-callout": "text callout, inert in markup",
}

RULE = re.compile(r"(?:^|\})\s*([^{}@]+?)\s*\{([^{}]*)\}", re.MULTILINE)
# Tolerates `0`, `0.0`, `!important`, and a missing final semicolon.
OPACITY_ZERO = re.compile(r"opacity:\s*0(?:\.0+)?\s*(?:!important)?\s*[;}]")

# Every closed-state rule this release fixed. The sweep below cannot see all of
# them (see the module docstring), so reverting any one must still fail here.
FIXED_CLOSED_STATES = [
    ".nav-overflow-menu",
    ".api-key-panel",
    ".portfolio-manager-panel",
    ".brand-intro-callout",
    ".hud-popover",
    ".alloc-popover",
    "#kbd-overlay",
    "body > .holding-expand-fab",
    ".dashboard-senpai.is-hidden",
    "#holdings-card.is-ai-checking .table-responsive",
    ".boot-splash.is-leaving",
]


def _css() -> str:
    return (ROOT / "static/css/style.css").read_text(encoding="utf-8")


def _strip_comments(css: str) -> str:
    """Drop /* … */ so a comment above a rule is not read as part of its selector."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _faded_rules(css: str) -> list[tuple[str, str]]:
    """Every top-level rule that fades out and blocks the pointer."""
    found = []
    for match in RULE.finditer(_strip_comments(css)):
        selector = " ".join(match.group(1).split())
        body = match.group(2)
        if OPACITY_ZERO.search(body + ";") and re.search(
            r"pointer-events:\s*none", body
        ):
            found.append((selector, body))
    return found


def test_every_rule_this_release_fixed_still_hides():
    """Pins the fixes by name, including the one the sweep cannot reach."""
    css = _css()
    regressed = [
        selector
        for selector in FIXED_CLOSED_STATES
        if not re.search(r"visibility:\s*hidden", _rule_body(css, selector))
    ]
    assert not regressed, (
        f"these closed-state rules lost visibility: hidden: {regressed}. Their "
        "controls are keyboard-focusable again while invisible."
    )


def test_the_sweep_actually_finds_faded_rules():
    # A regex bug would make the real assertion below vacuously pass.
    assert len(_faded_rules(_css())) >= 20


def test_every_faded_overlay_leaves_the_tab_order():
    offenders = []
    for selector, body in _faded_rules(_css()):
        if selector in DECORATIVE:
            continue
        if not re.search(r"visibility:\s*hidden", body):
            offenders.append(selector)

    assert not offenders, (
        "these rules fade to opacity 0 and block the pointer but never set "
        "visibility: hidden, so any control inside them stays keyboard-"
        f"focusable while invisible: {offenders}. Add visibility: hidden (and "
        "the matching visibility delay), or name the selector in DECORATIVE "
        "with a reason."
    )


def _transition_window(body: str) -> tuple[float | None, float | None]:
    """(opacity duration, longest animated duration), ignoring visibility itself."""
    transition = re.search(r"transition:\s*([^;]+);", body, re.DOTALL)
    if not transition:
        return None, None
    opacity = longest = None
    for part in transition.group(1).split(","):
        if "visibility" in part:
            continue
        seconds = re.search(r"([\d.]+)s", part)
        if not seconds:
            continue
        value = float(seconds.group(1))
        longest = value if longest is None else max(longest, value)
        if "opacity" in part:
            opacity = value
    return opacity, longest


def test_hidden_overlays_delay_visibility_until_the_fade_finishes():
    """The flip must land inside the rule's own animation window.

    Too early and the fade is cut off mid-curve; later than the rule's slowest
    property and the flip is scheduled past the point where the element is
    typically torn down, so it may never apply at all — a delay that merely
    *exists* is not evidence that it does anything.

    Limit worth stating: this can only compare a rule against itself. It cannot
    see a JS teardown that removes the element earlier, which is how a
    boot-splash rule once carried a 0.42s delay against a 260ms teardown. That
    one was caught in review, not here.
    """
    problems = []
    for selector, body in _faded_rules(_css()):
        if selector in DECORATIVE or not re.search(r"visibility:\s*hidden", body):
            continue
        # A rule with no transition at all never animated; nothing to preserve.
        if "transition" not in body:
            continue
        delay = re.search(r"visibility\s+0s\s+linear\s+([\d.]+)s", body)
        if not delay:
            problems.append(f"{selector}: hides without delaying the flip")
            continue
        seconds = float(delay.group(1))
        opacity, longest = _transition_window(body)
        if opacity is not None and seconds < opacity - 1e-9:
            problems.append(
                f"{selector}: visibility flips at {seconds}s, before its "
                f"{opacity}s fade finishes"
            )
        elif longest is not None and seconds > longest + 1e-9:
            problems.append(
                f"{selector}: visibility flips at {seconds}s, after its slowest "
                f"transition ({longest}s) — the flip may never apply"
            )

    assert not problems, "\n".join(problems)


# The open-state counterpart: hiding is only safe if opening reliably undoes it.
OPEN_STATES = [
    (".nav-overflow-menu", ".nav-overflow-menu.is-visible"),
    (".api-key-panel", ".api-key-panel.is-open"),
    (
        ".portfolio-manager-panel",
        "body > .portfolio-manager-popover.is-visible .portfolio-manager-panel",
    ),
    (".brand-intro-callout", ".brand-intro-callout.is-visible"),
    (".hud-popover", ".hud-popover.is-visible"),
    (".alloc-popover", ".alloc-popover.is-visible"),
    ("#kbd-overlay", "#kbd-overlay.kbd-visible"),
    ("body > .holding-expand-fab", ".holding-expand-fab.is-visible"),
]


def _rule_body(css: str, selector: str) -> str:
    pattern = re.compile(
        r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", re.MULTILINE
    )
    match = pattern.search(css)
    assert match, f"selector not found as its own rule: {selector}"
    return match.group(1)


def test_open_overlays_restore_visibility_immediately():
    css = _css()
    for closed, open_sel in OPEN_STATES:
        body = _rule_body(css, open_sel)
        assert re.search(r"visibility:\s*visible", body), (
            f"{open_sel} must restore visibility, otherwise {closed} stays "
            "hidden from the keyboard and screen readers when opened"
        )
        assert re.search(r"transition-delay:\s*0s", body), (
            f"{open_sel} must cancel the close-state visibility delay, "
            "otherwise the panel opens invisibly for the fade duration"
        )


def test_reduced_motion_override_keeps_the_visibility_component():
    """Redeclaring `transition` in a media query replaces the shorthand.

    The reduced-motion block for the overflow menu shortens the fade; if it
    drops the visibility component the panel flips hidden mid-fade.
    """
    css = _css()
    block = re.search(
        r"@media \(prefers-reduced-motion: reduce\) \{[^@]*?\.nav-overflow-menu,"
        r"[^@]*?\}\s*\}",
        css,
        re.DOTALL,
    )
    assert block, "reduced-motion override for .nav-overflow-menu not found"
    assert "visibility" in block.group(0), (
        "the reduced-motion transition drops the visibility component, so the "
        "closed menu flips hidden before its fade finishes"
    )
