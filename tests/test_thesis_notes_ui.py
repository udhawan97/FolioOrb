"""Tests for the thesis-notes section in each holding's expanded detail.

Same static-assertion style as tests/test_insider_ui.py: the section must
exist, render at every site, save through the real update endpoint, and never
clobber an editor the user is typing into.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js() -> str:
    return (ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")


def _render() -> str:
    js = _js()
    assert "function renderThesisNotes" in js
    return js.split("function renderThesisNotes")[1][:4000]


def test_expand_row_has_a_notes_section():
    assert "intel-notes-section" in _js()


def test_notes_are_wired_into_every_render_site():
    # Insider/fundamentals render at three sites; notes must ride along at each
    # or they render stale or not at all. 4 = the definition + 3 call sites.
    assert _js().count("renderThesisNotes(") >= 4


def test_notes_save_through_the_real_update_endpoint():
    js = _js()
    assert "function saveThesisNotes" in js
    save = js.split("function saveThesisNotes")[1][:2000]
    assert "/api/portfolio/holdings/" in save
    assert '"PUT"' in save
    assert "notes" in save


def test_editor_caps_length_to_match_the_schema():
    # HoldingUpdate.notes is Field(max_length=500); the textarea must agree so
    # the user hits the wall while typing, not on save.
    assert 'maxlength="500"' in _render()


def test_render_escapes_untrusted_text():
    # Notes are user text; they must pass through escapeHtml before innerHTML.
    assert "escapeHtml" in _render()


def test_render_never_clobbers_an_open_editor():
    # injectSummaryRows re-runs on refresh cycles; a render that replaces the
    # section's HTML while the user is typing would eat their thesis mid-word.
    render = _render()
    assert "is-editing" in render


def test_empty_state_invites_a_thesis():
    render = _render()
    assert "Why do you own" in render
