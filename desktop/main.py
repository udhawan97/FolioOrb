"""Desktop entry point for the packaged FolioSenseAI app.

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

    threading.Thread(target=_run_server, args=(port,), daemon=True).start()

    if not _wait_for_health(base_url, HEALTH_TIMEOUT_SECONDS):
        if _STARTUP_STATE["error"]:
            print(f"FolioSenseAI failed to start: {_STARTUP_STATE['error']}", file=sys.stderr)
        else:
            print("FolioSenseAI failed to start within the timeout.", file=sys.stderr)
        return 1

    if smoke:
        from app.version import __version__

        print(f"FolioSenseAI {__version__} started and healthy at {base_url}")
        return 0

    import webview

    # `?app=1` tells the dashboard it's running inside the native WebView so it
    # can switch to a lighter rendering profile (no backdrop-filter, fewer
    # ambient animations) for smooth scrolling. The in-browser experience is
    # unaffected. Tab switching is client-side, so this query persists.
    webview.create_window(
        "FolioSenseAI",
        f"{base_url}/?app=1",
        width=1440,
        height=920,
        min_size=(1024, 720),
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
