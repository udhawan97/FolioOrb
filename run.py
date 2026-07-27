import threading
import time
import webbrowser

import uvicorn

URL = "http://localhost:8000"


def _open_browser():
    time.sleep(2)
    webbrowser.open(URL)


if __name__ == "__main__":
    # Manual restores are swapped in before app.main imports SQLAlchemy and
    # opens the live SQLite file. The browser is opened only after that boundary.
    from app.services import backup_service

    backup_service.apply_pending_restore()
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
