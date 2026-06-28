import threading
import time
import webbrowser

import uvicorn

URL = "http://localhost:8000"


def _open_browser():
    time.sleep(2)
    webbrowser.open(URL)


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
