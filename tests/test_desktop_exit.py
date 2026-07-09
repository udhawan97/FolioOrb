"""Guards for the desktop shell's process-exit path.

The frozen app must terminate via os._exit (bypassing interpreter finalization),
not via a normal return/SystemExit. Finalization flushes stdout/stderr while
uvicorn's server thread and the cache-warmup / update-scheduler daemon threads
may hold the buffer lock, which aborts the process with a fatal
`_enter_buffered_busy` error — the macOS "quit unexpectedly" crash dialog that
appeared on every quit. These are source-level asserts (the GUI window can't be
driven headlessly); the runtime behavior is covered by the `--smoke` path, which
exercises the identical exit funnel and is run on the frozen bundle in CI.
"""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "desktop" / "main.py"


def _source():
    return SRC.read_text(encoding="utf-8")


def test_hard_exit_uses_os_exit():
    src = _source()
    assert "def _hard_exit(" in src
    # _hard_exit must call os._exit (not sys.exit / return), or finalization runs.
    hard = src[src.index("def _hard_exit("):]
    hard = hard[: hard.index("\n\n\n") if "\n\n\n" in hard else len(hard)]
    assert "os._exit(" in hard


def test_entrypoint_exits_hard_not_via_systemexit():
    src = _source()
    # The module entrypoint must funnel through _hard_exit, never raise
    # SystemExit(main()) (which would run the crashing finalization path).
    assert "_hard_exit(main())" in src
    assert "raise SystemExit(main())" not in src


def test_quit_hook_flushes_before_exit():
    """The install/rollback quit hook must go through _hard_exit, not a raw exit."""
    src = _source()
    quit_fn = src[src.index("def _quit_app("):]
    quit_fn = quit_fn[: quit_fn.index("\n\n")]
    assert "_hard_exit(0)" in quit_fn


def test_no_bare_return_from_windowed_path_reaches_finalization():
    """main() must not fall off the end (implicit None -> finalization); every
    reachable path returns an int that __main__ hands to _hard_exit."""
    tree = ast.parse(_source())
    main_fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    # Every return in main() returns a value (never a bare `return`).
    for node in ast.walk(main_fn):
        if isinstance(node, ast.Return):
            assert node.value is not None, "bare return in main() leaks to finalization"
