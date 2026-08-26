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
import shutil
import socket
import sys
import tempfile
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


def _configure_smoke_environment() -> str:
    """Select an isolated data root before a smoke run imports app modules."""
    smoke_root = tempfile.mkdtemp(prefix="folioorb-smoke-")
    os.environ["FOLIOORB_SMOKE_TEST"] = "1"
    os.environ["FOLIOORB_DATA_DIR"] = smoke_root
    os.environ["ANTHROPIC_API_KEY"] = ""
    smoke_db = os.path.join(smoke_root, "portfolio.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{smoke_db}"
    return smoke_root


def main() -> int:
    smoke = "--smoke" in sys.argv

    # A package smoke test must never open, migrate, restore, or record launch
    # state against the user's real FolioOrb data. CI normally starts from a
    # clean runner, but local release verification runs the same frozen binary
    # on a developer machine. Force a throwaway database and let app.main
    # suppress every nonessential startup side effect.
    if smoke:
        _configure_smoke_environment()

    # Apply an explicitly queued vault restore before the server thread imports
    # app.main and opens SQLAlchemy connections to the live database.
    if not smoke:
        from app.services import backup_service

        backup_service.apply_pending_restore()

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


def _fsync_parent(path: str) -> None:
    """Persist an atomic destination swap on POSIX; Windows has no directory fsync."""
    if os.name == "nt":
        return
    parent = os.path.dirname(os.path.abspath(path)) or "."
    fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_binary_file(path: str, payload: bytes) -> str:
    """Write through one private sibling temp, then atomically replace the target."""
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{os.path.basename(target)}-", suffix=".tmp", dir=parent
    )
    try:
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
        try:
            _fsync_parent(target)
        except OSError:
            # The complete, file-fsynced replacement is already visible. A
            # directory-fsync failure weakens crash durability but must not be
            # reported as "nothing was written" and invite a risky retry.
            pass
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return path


def _write_text_file(path: str, content: str) -> str:
    """Write text as UTF-8, adding exactly one BOM for CSV files.

    Exported CSVs open cleanly in Excel only with a BOM. ``fetch().text()`` in
    the page strips the server's BOM, so content arriving here usually has none —
    write CSV as ``utf-8-sig`` to add one. HTML remains plain UTF-8, and content
    that already carries a BOM is written as-is so it never doubles.
    """
    # CSV gets a BOM for Excel. HTML and other text exports stay plain UTF-8.
    is_csv = str(path).lower().endswith(".csv")
    encoding = "utf-8-sig" if is_csv and not content.startswith("﻿") else "utf-8"
    return _write_binary_file(path, content.encode(encoding))


class _NativeBridge:  # pylint: disable=too-few-public-methods
    """JS ↔ native bridge exposed to the page as ``window.pywebview.api``.

    The WebView has no download chrome: an ``<a download>`` or a blob-URL click
    just navigates and renders the file inline, stranding the user on a text page
    with no back button. ``save_file`` gives the page a real "Save As…" dialog so
    report exports and templates write actual files. The binary backup method
    uses the same native dialog without decoding SQLite. Real browsers never see
    this bridge and keep their own download path.
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

    def export_backup(self, name: str) -> dict:
        """Copy one verified database vault item through a native Save dialog."""
        try:
            import webview

            from app.services import backup_service

            source = backup_service.resolve_backup_name(name)
            if not source.exists() or not backup_service.verify_vault_backup(source):
                return {"saved": False, "path": None, "error": "unverified_backup"}
            window = webview.active_window()
            if window is None:
                return {"saved": False, "path": None}
            result = window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=source.name
            )
            path = result[0] if isinstance(result, (list, tuple)) else result
            if not path:
                return {"saved": False, "path": None}
            shutil.copyfile(source, path)
            return {"saved": True, "path": path}
        except Exception as exc:  # pylint: disable=broad-except
            return {"saved": False, "path": None, "error": type(exc).__name__}

    def export_portable_records(self) -> dict:
        """Build and save the human-readable records ZIP without text decoding."""
        try:
            import webview

            from app.database import SessionLocal
            from app.services import portfolio_records

            with SessionLocal() as db:
                payload = portfolio_records.build_portable_archive(db)
            window = webview.active_window()
            if window is None:
                return {"saved": False, "path": None}
            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename="folioorb-portable-export.zip",
            )
            path = result[0] if isinstance(result, (list, tuple)) else result
            if not path:
                return {"saved": False, "path": None}
            _write_binary_file(path, payload)
            return {"saved": True, "path": path}
        except Exception as exc:  # pylint: disable=broad-except
            return {"saved": False, "path": None, "error": type(exc).__name__}

    def export_review_bundle(self, portfolio_id: int, period: str) -> dict:
        """Build and save one Review Bundle without decoding its ZIP."""
        try:
            import webview

            from app.database import SessionLocal
            from app.services import review_bundle

            numeric_id = int(portfolio_id)
            selected_period = str(period)
            with SessionLocal() as db:
                payload = review_bundle.build_review_bundle(
                    db, numeric_id, selected_period
                )
            filename = review_bundle.bundle_filename(numeric_id, selected_period)
            window = webview.active_window()
            if window is None:
                return {"saved": False, "path": None}
            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
            )
            path = result[0] if isinstance(result, (list, tuple)) else result
            if not path:
                return {"saved": False, "path": None}
            _write_binary_file(path, payload)
            return {"saved": True, "path": path}
        except Exception as exc:  # pylint: disable=broad-except
            return {"saved": False, "path": None, "error": type(exc).__name__}

    def open_url(self, url: str) -> dict:
        """Open an external http(s) link in the user's real browser.

        The WebView has no browser chrome, so a ``target="_blank"`` link strands
        the user in a frameless window (or does nothing). The page routes such
        links here so they open in the default system browser instead. Only
        http/https is allowed — never ``file:``, ``javascript:``, etc.
        """
        try:
            import webbrowser
            from urllib.parse import urlparse

            parsed = urlparse((url or "").strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return {"opened": False, "error": "unsupported_scheme"}
            webbrowser.open(url)
            return {"opened": True}
        except Exception as exc:  # pylint: disable=broad-except
            return {"opened": False, "error": type(exc).__name__}


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
