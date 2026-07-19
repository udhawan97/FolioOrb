"""Every animation the stylesheet asks for is an animation it actually defines.

A misspelled `animation-name` is still valid CSS: the name is a custom-ident, so
it parses, it survives every linter, and it raises nothing in the console. It
simply matches no `@keyframes` and the element sits there not animating. The
skeleton loaders are where this hides best — a static grey bar and a pulsing
grey bar look identical in a screenshot taken mid-pulse.

So the check is a whole-file one rather than a rule-by-rule one: collect the
names the stylesheet references, collect the names it defines, and require the
first set to be contained in the second.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

# Everything the `animation` shorthand accepts that is *not* the name: timing
# functions, directions, fill modes, play states, plus the CSS-wide keywords.
# `none` is omitted deliberately — it is a legal animation-name meaning "no
# animation", and treating it as a reference would be a false positive.
NON_NAME_KEYWORDS = frozenset(
    """
    linear ease ease-in ease-out ease-in-out step-start step-end
    normal reverse alternate alternate-reverse
    forwards backwards both
    running paused
    infinite none
    initial inherit unset revert revert-layer
    """.split()
)


def _css() -> str:
    """The stylesheet with comments removed.

    Comments are stripped rather than skipped because the file discusses its own
    animations in prose — `/* ... never referenced in animation:); ... */` reads
    as a declaration to any regex that has not been told otherwise.
    """
    raw = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    # Blank the body but keep the newlines, so reported line numbers stay true.
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), raw, flags=re.S)


def _strip_noise(value: str) -> str:
    """Drop `!important` and any function call, brackets and all.

    `cubic-bezier(.4, 0, .2, 1)` and `steps(4, end)` both contain commas and
    bare words, either of which would otherwise read as an animation name.
    """
    value = value.replace("!important", "")
    previous = None
    while previous != value:
        previous = value
        value = re.sub(r"[\w-]+\([^()]*\)", " ", value)
    return value


def _referenced_names(css: str) -> dict[str, int]:
    """Map each referenced animation name to the line it first appears on."""
    names: dict[str, int] = {}
    pattern = re.compile(r"(?<![\w-])animation(?:-name)?\s*:\s*([^;{}]+)")
    for match in pattern.finditer(css):
        line = css.count("\n", 0, match.start()) + 1
        for layer in _strip_noise(match.group(1)).split(","):
            for token in layer.split():
                if token in NON_NAME_KEYWORDS:
                    continue
                # A time (1.4s, 200ms) or an iteration count (2, .5).
                if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)(s|ms)?", token):
                    continue
                names.setdefault(token, line)
    return names


def _defined_names(css: str) -> set[str]:
    return set(re.findall(r"@(?:-\w+-)?keyframes\s+([\w-]+)", css))


def test_every_referenced_animation_is_defined():
    css = _css()
    defined = _defined_names(css)

    dangling = {
        name: line
        for name, line in _referenced_names(css).items()
        if name not in defined
    }

    assert not dangling, "animation names with no @keyframes: " + ", ".join(
        f"{name!r} (style.css:{line})" for name, line in sorted(dangling.items())
    )


def test_action_plan_skeleton_pulses():
    """The action-plan skeleton overrides the shared pulse; it must keep pulsing.

    `.shimmer-line` carries `animation: shimmerPulse ...`, and the action-plan
    rule re-declares the shorthand to retime it. Because the shorthand resets
    every `animation-*` longhand, that re-declaration has to name the keyframes
    again — dropping or misspelling the name silently stops the animation and
    strands the `animation-delay` stagger that follows it.
    """
    css = _css()
    rule = re.search(
        r"\.action-plan-skeleton\s+\.shimmer-line\s*\{([^}]*)\}",
        css,
    )
    assert rule, ".action-plan-skeleton .shimmer-line rule is missing"
    assert "shimmerPulse" in rule.group(1), (
        "the action-plan skeleton names no known keyframes, so it renders as "
        "static bars: " + rule.group(1).strip()
    )
