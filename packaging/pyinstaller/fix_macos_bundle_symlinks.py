"""Repair broken data symlinks in a PyInstaller macOS .app bundle.

PyInstaller's macOS BUNDLE step splits the onedir output between
Contents/Frameworks (binaries) and Contents/Resources (pure data), leaving a
symlink in Frameworks pointing at Resources. For directories that are 100%
data with no compiled binary mixed in (observed with this app's own
static/templates dirs, and with pytz's zoneinfo data), PyInstaller sometimes
creates the Frameworks symlink but never materializes the Resources side —
leaving a dangling symlink and a runtime FileNotFoundError / missing-data
error the first time that path is touched.

The onedir COLLECT output (dist/FolioSenseAI/_internal/...) always has the
real files, since this bug is specific to the BUNDLE step, not COLLECT. This
script walks the .app for broken symlinks and heals each one by copying the
real file/directory from the onedir output. Run after `pyinstaller ...spec`
and before packaging the DMG.

Usage: python packaging/pyinstaller/fix_macos_bundle_symlinks.py <dist_dir>
"""

import shutil
import sys
from pathlib import Path


def _iter_broken_symlinks(root: Path):
    for path in root.rglob("*"):
        if path.is_symlink() and not path.exists():
            yield path


def _find_onedir_internal(dist_dir: Path) -> Path | None:
    """Locate the onedir COLLECT output's _internal/ dir alongside the .app.

    Same PyInstaller run, always has the real file for anything the BUNDLE
    step may have left as a dangling symlink.
    """
    for candidate in dist_dir.iterdir():
        internal = candidate / "_internal"
        if internal.is_dir():
            return internal
    return None


def _resolve_repair(link: Path, *, frameworks: Path, resources: Path,
                     onedir_internal: Path) -> tuple[Path, Path] | None:
    """Return (source, target) to heal one broken symlink, or None if unresolvable."""
    if "Frameworks" in link.parts:
        # Frameworks/<rel> -> ../Resources/<rel>, but Resources/<rel> was never
        # materialized. The onedir output always has the real file at this path.
        rel = link.relative_to(frameworks)
        source = onedir_internal / rel
        target = resources / rel
    else:
        # A top-level convenience symlink elsewhere in the bundle (observed for
        # pyarrow's libarrow*.dylib under Resources/) whose relative target was
        # never materialized, but the real file exists elsewhere in the bundle
        # (e.g. under Frameworks, where binaries are correctly placed for
        # code-signing). Resolve by basename search rather than a fixed direction.
        candidates = [p for p in frameworks.rglob(link.name) if not p.is_symlink()]
        if not candidates:
            candidates = [p for p in onedir_internal.rglob(link.name) if not p.is_symlink()]
        if not candidates:
            return None
        source, target = candidates[0], link  # replace the symlink itself in place

    if not source.exists():
        return None
    return source, target


def _apply_repair(source: Path, target: Path, link: Path) -> None:
    if target != link:
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        link.unlink()
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)


def main() -> int:
    dist_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist")
    app_bundles = list(dist_dir.glob("*.app"))
    if not app_bundles:
        print(f"No .app bundle found under {dist_dir}", file=sys.stderr)
        return 1
    app = app_bundles[0]
    resources = app / "Contents" / "Resources"
    frameworks = app / "Contents" / "Frameworks"

    onedir_internal = _find_onedir_internal(dist_dir)
    if onedir_internal is None:
        print("No onedir _internal/ output found alongside the .app bundle; "
              "cannot repair broken symlinks.", file=sys.stderr)
        return 1

    healed = []
    for link in _iter_broken_symlinks(app):
        resolved = _resolve_repair(
            link, frameworks=frameworks, resources=resources,
            onedir_internal=onedir_internal,
        )
        if resolved is None:
            continue
        source, target = resolved
        _apply_repair(source, target, link)
        healed.append(target.relative_to(app))

    for rel in healed:
        print(f"Healed broken symlink data: {rel}")

    remaining = list(_iter_broken_symlinks(app))
    if remaining:
        print(f"{len(remaining)} broken symlink(s) remain after repair:", file=sys.stderr)
        for link in remaining:
            print(f"  {link}", file=sys.stderr)
        return 1

    print(f"Healed {len(healed)} broken symlink(s); 0 remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
