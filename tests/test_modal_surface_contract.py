"""Every modal dialog takes its containment from one place.

Static-assertion style, like tests/test_overlay_focus_containment.py.

FolioOrb paints eight surfaces that declare ``aria-modal="true"``. Each used to
answer "what does modal mean" on its own, and the answers disagreed. Measured on
the rendered dashboard by walking the real tab order with a headless browser:

    portfolio-name-dialog     8 Tab presses → 6 landed outside the dialog
    portfolio-delete-dialog   8 Tab presses → 7 landed outside
    sale-dialog               8 Tab presses → 2 landed outside
    review-orbit              8 Tab presses → 1 landed outside
    update-sheet             10 Tab presses → 0, but with a live background
    portfolioModal           12 Tab presses → 0

Two of those are destructive confirmations. The keyboard could walk off
"Delete portfolio?" onto the dashboard behind it while the confirmation still
stood open, and the delete dialog leaked on its *first* Tab.

``static/js/modal-surface.js`` now owns the five things a modal surface has to
do — Tab containment (including re-entry when focus starts outside), an inert
background, Escape, a *checked* focus return, and a stack so nested surfaces
compose. Routing everything through it also fixed two bugs no single surface
could have found alone: a ``tabindex="-1"`` roving tab counted as a tab stop
(which is what made Review Orbit's wrap fire one element late), and
``document.body`` passing every staleness check a focus return could make.

Three guards, because none of them is enough alone
--------------------------------------------------
1. **A sweep of the markup**, so a *new* ``aria-modal="true"`` surface fails by
   default until it is named in ``ROUTED`` with the landmark it falls back to.
2. **A ban on private traps**, because opting in is worthless if a surface also
   keeps its own copy: the wrap-around idiom must not appear outside the seam.
3. **Load order**, since every caller reads ``FolioModalSurface`` at open time
   and a script tag in the wrong place turns that into a runtime error.

What this file cannot prove is that the containment *works* — that is
tests/js/modal-surface.test.cjs, which drives the seam against a fake DOM.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates/index.html").read_text(encoding="utf-8")
MODAL = (ROOT / "static/js/modal-surface.js").read_text(encoding="utf-8")

JS_DIR = ROOT / "static/js"
CALLERS = {
    name: (JS_DIR / name).read_text(encoding="utf-8")
    for name in (
        "dashboard.js",
        "dca-workflow.js",
        "review-orbit.js",
        "updates.js",
    )
}

# Every modal surface, and the durable landmark its focus return falls back to
# when the control that opened it is gone by the time it closes. That is the
# normal case, not the edge one: the rename and delete flows both re-render the
# switcher row that owned the trigger before the dialog resolves.
ROUTED = {
    "portfolio-name-dialog": "portfolio-switcher-trigger",
    "portfolio-delete-dialog": "portfolio-switcher-trigger",
    "portfolioModal": "portfolio-manager-trigger",
    "senpai-welcome-guide": "portfolio-manager-trigger",
    "review-orbit": "review-orbit-trigger",
    "update-sheet": "update-trigger",
    "dca-action-dialog": "dca-btn",
    "sale-dialog": "manage-holdings-search",
}

# Surfaces the markup sweep cannot see, each pinned by a guard below so the
# entry cannot become a fiction.
RUNTIME_SURFACES = {
    "sale-dialog": (
        'promptSaleDetails builds its overlay per sale, so its aria-modal="true" '
        "lives in a dashboard.js template string, not in index.html"
    ),
    "senpai-welcome-guide": (
        'ships as aria-modal="false" and is promoted when it actually opens, '
        "which is only for a portfolio with no holdings"
    ),
}

# `aria-modal="false"` is a deliberate not-a-modal: a popover or an inline
# confirmation that shares a dialog role but must not take the page hostage.
ARIA_MODAL_TRUE = re.compile(r'aria-modal="true"')


def _surface_ids() -> set[str]:
    """Every id in the markup that declares itself a modal.

    The id can sit on either side of the aria-modal attribute (the tag is often
    wrapped across lines), so both directions are searched within one tag.
    """
    found = set(RUNTIME_SURFACES)
    for tag in re.finditer(r"<(?:div|section)\b[^>]*>", INDEX, re.DOTALL):
        text = tag.group(0)
        if not ARIA_MODAL_TRUE.search(text):
            continue
        ident = re.search(r'\bid="([^"]+)"', text)
        assert ident, f"a modal surface with no id cannot be routed: {text[:120]}"
        found.add(ident.group(1))
    return found


def test_the_runtime_surfaces_really_are_modal():
    """RUNTIME_SURFACES is an exemption, so each entry must be earned."""
    dashboard = CALLERS["dashboard.js"]
    assert 'class="sale-dialog" role="dialog" aria-modal="true"' in dashboard, (
        "the sale dialog no longer declares itself modal in dashboard.js — if it "
        "moved into index.html the sweep will find it and this exemption is stale"
    )
    assert 'guide.setAttribute("aria-modal", "true")' in dashboard, (
        "the welcome guide is no longer promoted to a modal at open time"
    )


def test_the_sweep_actually_finds_modal_surfaces():
    # A regex bug would make the real assertions below vacuously pass.
    assert len(_surface_ids()) >= 6


def test_every_modal_surface_is_routed_through_the_shared_seam():
    unrouted = sorted(_surface_ids() - set(ROUTED))
    assert not unrouted, (
        f"these surfaces declare aria-modal=\"true\" but are not routed through "
        f"static/js/modal-surface.js: {unrouted}. Open them with "
        "FolioModalSurface.open(...) and name the landmark their focus return "
        "falls back to in ROUTED — or drop aria-modal if they are not modal."
    )


def test_routed_surfaces_still_exist():
    """ROUTED is a list someone has to maintain, so it must not rot."""
    known = _surface_ids() | set(RUNTIME_SURFACES)
    stale = sorted(name for name in ROUTED if name not in known)
    assert not stale, f"ROUTED names surfaces that no longer exist: {stale}"


def test_each_surface_names_a_fallback_that_outlives_its_trigger():
    """A checked focus return is only useful if there is somewhere to land."""
    combined = "\n".join(CALLERS.values())
    missing = [
        f"{surface} → {landmark}"
        for surface, landmark in ROUTED.items()
        if landmark not in combined
    ]
    assert not missing, (
        "these fallback landmarks are not referenced by any caller, so a torn-"
        f"down trigger would drop focus at the top of the document: {missing}"
    )


def test_the_seam_is_the_only_focus_trap():
    """Opting in is worthless if a surface also keeps a private copy.

    The wrap-around idiom is distinctive enough to sweep for: a comparison of
    the active element against the first or last focusable. It belongs in
    modal-surface.js and nowhere else.
    """
    idiom = re.compile(r"\b(?:active|activeElement) === (?:first|last)\b")
    offenders = sorted(name for name, source in CALLERS.items() if idiom.search(source))
    assert not offenders, (
        f"{offenders} still hand-roll a focus trap. Eight private copies is how "
        "the tabindex=-1 and <body> bugs survived; route the surface through "
        "FolioModalSurface.open instead."
    )
    assert idiom.search(MODAL), "the sweep's idiom no longer matches the seam itself"


def test_the_seam_loads_before_every_caller():
    order = re.findall(r'<script defer src="/static/js/([a-z-]+\.js)\?v=0"></script>', INDEX)
    assert "modal-surface.js" in order, "modal-surface.js is never loaded"
    seam = order.index("modal-surface.js")
    late = [name for name in CALLERS if name in order and order.index(name) < seam]
    assert not late, (
        f"{late} load before modal-surface.js, so FolioModalSurface is undefined "
        "when they open a dialog"
    )


def test_the_seam_keeps_the_two_checks_that_only_showed_up_across_surfaces():
    """Both were invisible until one implementation served every dialog."""
    assert 'getAttribute?.("tabindex") !== "-1"' in MODAL, (
        "a roving tabindex=-1 control is not a tab stop; counting it puts the "
        "wrap one element late and leaks a Tab press onto <body>"
    )
    assert "element === owner.body" in MODAL, (
        "document.body is connected, visible, and has a focus() that does "
        "nothing — restoring to it is losing focus, not returning it"
    )
    assert "owner.activeElement === element" in MODAL, (
        "focus() reports nothing when it fails, so the result must be confirmed"
    )


def test_nested_surfaces_are_thawed_and_refrozen():
    """The stack is what makes routing every surface through one seam safe."""
    assert "function thawBranch" in MODAL
    assert "skip: stack.map" in MODAL
    open_body = MODAL[MODAL.index("function open(root"):]
    assert "thawed: thawBranch(root, owner)" in open_body
    assert "restoreBackgroundInert(entry.thawed)" in open_body
    assert "stack[stack.length - 1] !== entry" in open_body, (
        "an outer surface must not answer the keyboard while an inner one is up"
    )
