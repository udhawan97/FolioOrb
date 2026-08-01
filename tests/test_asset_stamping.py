"""Every local asset URL is stamped from the file's own bytes, not by hand.

`index.html` used to carry hand-written cache-busting query strings —
`dashboard.js?v=105`, `style.css?v=111`. Editing a file and forgetting to bump
its number serves every existing user the previous version out of their browser
cache, and the failure is invisible to whoever made the edit, because their own
cache was already cold. Guarding it with a test that asserts the current number
only moved the problem: the number and the test had to be bumped together, and
neither had anything to do with whether the file had actually changed.

The stamp is now derived from the file's contents at startup, so it is exactly
as fresh as the file is: identical bytes keep the same URL and stay cached, and
any edit at all changes it. The literal in the template is only a placeholder.
"""
import re

from app.main import _STATIC_DIR, _stamp_static_assets

STAMPED = re.compile(r'/static/([\w./-]+)\?v=([\w]+)')


def test_every_stamped_asset_matches_its_file_on_disk():
    html = (_STATIC_DIR.parent / "templates" / "index.html").read_text(encoding="utf-8")
    stamped = _stamp_static_assets(html)

    found = STAMPED.findall(stamped)
    assert found, "no stamped assets found — the template stopped using ?v="
    for relative_path, token in found:
        expected = _stamp_static_assets(f'"/static/{relative_path}?v=0"')
        assert f"?v={token}" in expected, f"{relative_path} carries a stale stamp"


def test_identical_bytes_produce_an_identical_stamp():
    """A rebuild that changes nothing must not evict anybody's cache."""
    html = '<script src="/static/js/dashboard.js?v=1"></script>'
    assert _stamp_static_assets(html) == _stamp_static_assets(html)


def test_changed_bytes_produce_a_different_stamp():
    asset = _STATIC_DIR / "js" / "dashboard.js"
    original = asset.read_bytes()
    html = '<script src="/static/js/dashboard.js?v=1"></script>'
    before = _stamp_static_assets(html)
    try:
        asset.write_bytes(original + b"\n// touched\n")
        after = _stamp_static_assets(html)
    finally:
        asset.write_bytes(original)
    assert before != after, "editing the file did not change its cache-busting stamp"


def test_an_unknown_asset_keeps_whatever_it_had():
    """A typo in a path must not silently strip the only busting that was there."""
    html = '<script src="/static/js/does-not-exist.js?v=7"></script>'
    assert _stamp_static_assets(html) == html


def test_external_urls_are_left_alone():
    html = '<link href="https://cdn.example.com/x.css?v=3">'
    assert _stamp_static_assets(html) == html


def test_no_hand_written_version_numbers_remain_in_the_template():
    """The template must not go back to carrying a number somebody maintains."""
    html = (_STATIC_DIR.parent / "templates" / "index.html").read_text(encoding="utf-8")
    hand_written = [
        match for match in STAMPED.findall(html)
        if match[1] != "0"
    ]
    assert not hand_written, (
        "these assets carry a hand-written ?v= — use ?v=0, the stamper fills it in: "
        f"{[m[0] for m in hand_written]}"
    )
