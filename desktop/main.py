"""Desktop entry point for the packaged FolioOrb app.

Runs the existing FastAPI application in-process on a loopback port and shows it
in a native window (WKWebView on macOS, WebView2 on Windows) via pywebview.
Closing the window shuts the server down. This is the target frozen by
PyInstaller — the browser-launching ``run.py`` remains the source/dev entry.

Run with ``--smoke`` to boot the server, confirm ``/health``, print the version,
and exit 0. CI uses this on the frozen binary to prove the bundle actually
starts before an installer is ever published.
"""

import os
import socket
import sys
import threading
import time
import urllib.request

# PyInstaller's --windowed/console=False mode sets sys.stdout/sys.stderr to
# None (no console attached, no pipe to redirect to). Any print() call would
# then raise AttributeError and crash the app before it even gets to show a
# window. This is a documented PyInstaller gotcha, not specific to this app —
# guard it unconditionally so every print() below is safe on every platform.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # pylint: disable=consider-using-with
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # pylint: disable=consider-using-with

# When run from a source checkout (python desktop/main.py), the repo root isn't
# on sys.path, so the `app` package can't be imported. A frozen build gets its
# path set up by PyInstaller, so only patch this in the non-frozen case.
if not getattr(sys, "frozen", False):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

HOST = "127.0.0.1"
PREFERRED_PORT = 8000
HEALTH_TIMEOUT_SECONDS = 40.0

# Holds the server thread's startup exception, if any. A dict (rather than a
# module-level name rebound via `global`) so _run_server can record into it
# without a global statement.
_STARTUP_STATE: dict = {"error": None}


def _find_free_port(preferred: int) -> int:
    """Return the preferred port if free, otherwise an OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def _wait_for_health(base_url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # pylint: disable=broad-except
            time.sleep(0.25)
    return False


def _run_server(port: int) -> None:
    try:
        # Imported lazily and inside the thread so the CORS origin below is
        # already set in the environment before app.config builds its
        # settings singleton.
        import uvicorn
        from app.main import app

        uvicorn.run(app, host=HOST, port=port, log_level="warning")
    except Exception as exc:  # pylint: disable=broad-except
        # A daemon thread's default exception hook only prints to stderr,
        # which can be a devnull-backed guard on a windowed build (see the
        # sys.stderr None handling above) — capture it so main() can surface
        # a real reason instead of a generic "timed out" message.
        _STARTUP_STATE["error"] = f"{type(exc).__name__}: {exc}"


def main() -> int:
    smoke = "--smoke" in sys.argv
    port = _find_free_port(PREFERRED_PORT)
    base_url = f"http://{HOST}:{port}"

    # The window's origin must be allowed by CORS. Set this before the server
    # thread imports app.main (which reads CORS_ALLOWED_ORIGINS at import time).
    os.environ["CORS_ALLOWED_ORIGINS"] = f"http://127.0.0.1:{port},http://localhost:{port}"

    # Count this launch so a run that dies before it's healthy (e.g. a bad
    # update that won't start) is detected and rollback can be offered. Skipped
    # in smoke mode so CI doesn't perturb the counter.
    if not smoke:
        try:
            from app.services import launch_health

            launch_health.record_launch_attempt()
        except Exception:  # pylint: disable=broad-except
            pass

    threading.Thread(target=_run_server, args=(port,), daemon=True).start()

    if not _wait_for_health(base_url, HEALTH_TIMEOUT_SECONDS):
        if _STARTUP_STATE["error"]:
            print(f"FolioOrb failed to start: {_STARTUP_STATE['error']}", file=sys.stderr)
        else:
            print("FolioOrb failed to start within the timeout.", file=sys.stderr)
        return 1

    if smoke:
        from app.version import __version__

        print(f"FolioOrb {__version__} started and healthy at {base_url}")
        return 0

    return _launch_window(base_url)


def _safe_download_name(name: str) -> str:
    """Reduce a page-suggested download name to a bare, safe basename.

    The name comes from the web layer, so strip any directory components (an
    accidental or malicious ``../``) and fall back to a sensible default.
    """
    base = os.path.basename(str(name or "").strip())
    return base or "export.csv"


def _write_text_file(path: str, content: str) -> str:
    """Write ``content`` to ``path`` as UTF-8 with exactly one leading BOM.

    Exported CSVs open cleanly in Excel only with a BOM. ``fetch().text()`` in
    the page strips the server's BOM, so content arriving here usually has none —
    write it as ``utf-8-sig`` to add one. Content that already carries a BOM is
    written as-is so it never doubles.
    """
    encoding = "utf-8" if content.startswith("﻿") else "utf-8-sig"
    with open(path, "w", encoding=encoding, newline="") as handle:
        handle.write(content)
    return path


class _NativeBridge:  # pylint: disable=too-few-public-methods
    """JS ↔ native bridge exposed to the page as ``window.pywebview.api``.

    The WebView has no download chrome: an ``<a download>`` or a blob-URL click
    just navigates and renders the file inline, stranding the user on a text page
    with no back button. ``save_file`` gives the page a real "Save As…" dialog so
    CSV export and template download write an actual file. Real browsers never
    see this bridge and keep their own download path.
    """

    def save_file(self, filename: str, content: str) -> dict:
        """Prompt for a location and write ``content`` there.

        Returns ``{"saved": bool, "path": str|None}``; a cancelled dialog is a
        clean ``saved=False`` (not an error).
        """
        try:
            import webview

            window = webview.active_window()
            if window is None:
                return {"saved": False, "path": None}
            result = window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=_safe_download_name(filename)
            )
            # SAVE_DIALOG yields a path string (some builds: a 1-tuple) or None.
            path = result[0] if isinstance(result, (list, tuple)) else result
            if not path:
                return {"saved": False, "path": None}
            _write_text_file(path, content or "")
            return {"saved": True, "path": path}
        except Exception as exc:  # pylint: disable=broad-except
            return {"saved": False, "path": None, "error": type(exc).__name__}


def _launch_window(base_url: str) -> int:
    """Create the native window (with menu + exit hook) and run the UI loop."""
    import webbrowser

    import webview

    # After several failed launches with a rollback available, open straight to
    # the rollback offer so a broken update is recoverable.
    offer_rollback = False
    try:
        from app.services import launch_health

        offer_rollback = launch_health.should_offer_rollback()
    except Exception:  # pylint: disable=broad-except
        pass

    # `?app=1` tells the dashboard it's running inside the native WebView so it
    # can switch to a lighter rendering profile (no backdrop-filter, fewer
    # ambient animations) for smooth scrolling. The in-browser experience is
    # unaffected. Tab switching is client-side, so this query persists.
    start_url = f"{base_url}/?app=1" + ("&rollback=1" if offer_rollback else "")
    window = webview.create_window(
        "FolioOrb",
        start_url,
        width=1440,
        height=920,
        min_size=(1024, 720),
        js_api=_NativeBridge(),
    )

    # The server is up and the window is created: this launch is healthy, so
    # clear the failed-launch counter.
    try:
        from app.services import launch_health

        launch_health.mark_launch_healthy()
    except Exception:  # pylint: disable=broad-except
        pass

    # Let the update installer quit the app so a launched installer can replace
    # files the running app would otherwise hold open. Falls back to a hard exit
    # if the window can't be destroyed cleanly.
    def _quit_app() -> None:
        try:
            window.destroy()
        except Exception:  # pylint: disable=broad-except
            _hard_exit(0)

    try:
        from app.services import update_installer

        update_installer.register_exit_hook(_quit_app)
    except Exception:  # pylint: disable=broad-except
        pass

    def _check_for_updates() -> None:
        # Drive the in-page update sheet from the native menu. Guarded inside JS
        # so it's a no-op if the page hasn't finished loading updates.js.
        try:
            window.evaluate_js("window.FolioUpdates && window.FolioUpdates.openAndCheck()")
        except Exception:  # pylint: disable=broad-except
            pass

    def _open_in_browser() -> None:
        try:
            webbrowser.open(f"{base_url}/")
        except Exception:  # pylint: disable=broad-except
            pass

    # A native menu with "Check for Updates…" (per the update-system design) and
    # an escape hatch to the default browser. pywebview cannot inject into the
    # standard macOS application menu, so these live under a custom top-level
    # menu. Wrapped defensively: a pywebview build without the menu API still
    # launches the window normally.
    try:
        import webview.menu as wm

        menu_items = [
            wm.Menu(
                "FolioOrb",
                [
                    wm.MenuAction("Check for Updates…", _check_for_updates),
                    wm.MenuSeparator(),
                    wm.MenuAction("Open in Browser", _open_in_browser),
                ],
            )
        ]
        webview.start(menu=menu_items)
    except (ImportError, AttributeError, TypeError):
        webview.start()

    # webview.start() has returned — the window was closed (by the user, or by
    # _quit_app for an install/rollback handoff). Return; __main__ terminates
    # the process via _hard_exit.
    return 0


def _hard_exit(code: int) -> None:
    """Terminate the process immediately, bypassing interpreter finalization.

    Every exit path funnels through here. A normal ``SystemExit``/return would
    run ``Py_FinalizeEx``, which flushes stdout/stderr while the still-running
    daemon threads (uvicorn's server thread, the cache-warmup thread, the
    update-check scheduler) may be mid-write to those same buffered streams. If a
    daemon holds the buffer lock at that moment, CPython aborts with a fatal
    ``_enter_buffered_busy`` error — surfacing as a macOS "FolioOrb quit
    unexpectedly" crash dialog on every quit (reproduced deterministically in the
    frozen build). A desktop app being closed needs no graceful teardown: daemon
    threads die with the process and the OS reclaims the loopback socket, so we
    flush what we can and skip finalization entirely.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # pylint: disable=broad-except
            pass
    os._exit(code)  # pylint: disable=protected-access


def _run() -> int:
    """Run main(), converting ANY escaping exception into an exit code.

    An exception unwinding out of main() (e.g. webview.start() raising something
    other than the ImportError/AttributeError/TypeError we fall back on, a socket
    or thread-start failure, a WebKit init error) must not propagate to normal
    interpreter shutdown — that runs finalization and hits the same daemon-thread
    buffer-flush abort. Catching it here guarantees every exit still leaves via
    _hard_exit.
    """
    try:
        return main()
    except SystemExit as exc:  # an explicit sys.exit somewhere in startup
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException as exc:  # pylint: disable=broad-exception-caught
        try:
            print(f"FolioOrb exited on error: {type(exc).__name__}: {exc}", file=sys.stderr)
        except Exception:  # pylint: disable=broad-except
            pass
        return 1


if __name__ == "__main__":
    _hard_exit(_run())
