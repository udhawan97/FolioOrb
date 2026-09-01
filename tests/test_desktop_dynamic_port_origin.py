"""The packaged launcher freezes its API origin only after choosing its port."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


_PROCESS_REPLAY = r"""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import desktop.main as desktop_main

PORT = 49173
result = {}


class InlineThread:
    def __init__(self, *, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon

    def start(self):
        self.target(*self.args, **self.kwargs)


def inspect_server(port):
    from app.config import settings
    from app.services.local_request_guard import LocalRequestGuardMiddleware

    application = FastAPI()
    calls = {"mutations": 0}

    @application.post("/api/mutate")
    def mutate():
        calls["mutations"] += 1
        return {"ok": True}

    application.add_middleware(
        LocalRequestGuardMiddleware,
        allowed_origins=settings.CORS_ALLOWED_ORIGINS,
    )
    client = TestClient(application, base_url=f"http://127.0.0.1:{port}")
    accepted = client.post(
        "/api/mutate",
        headers={"Origin": f"http://localhost:{port}"},
    )
    rejected = client.post(
        "/api/mutate",
        headers={"Origin": "http://localhost:8000"},
    )
    result.update(
        {
            "port": port,
            "origins": settings.CORS_ALLOWED_ORIGINS,
            "accepted": accepted.status_code,
            "rejected": rejected.status_code,
            "mutations": calls["mutations"],
        }
    )


desktop_main._find_free_port = lambda _preferred: PORT
desktop_main._run_server = inspect_server
desktop_main._wait_for_health = lambda _url, _timeout: True
desktop_main._launch_window = lambda _url: 0
desktop_main.threading = SimpleNamespace(Thread=InlineThread)

result["return_code"] = desktop_main.main()
print(json.dumps(result, sort_keys=True))
"""


def test_dynamic_port_is_frozen_before_database_import(tmp_path: Path):
    """A non-8000 packaged origin can mutate; the old default cannot."""
    data_root = tmp_path / "profile"
    data_root.mkdir()
    environment = os.environ.copy()
    environment.pop("CORS_ALLOWED_ORIGINS", None)
    environment.update(
        {
            "FOLIOORB_DATA_DIR": str(data_root),
            "DATABASE_URL": f"sqlite:///{data_root / 'portfolio.db'}",
            "ANTHROPIC_API_KEY": "",
        }
    )

    completed = subprocess.run(
        [sys.executable, "-c", _PROCESS_REPLAY],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        "accepted": 200,
        "mutations": 1,
        "origins": [
            "http://127.0.0.1:49173",
            "http://localhost:49173",
        ],
        "port": 49173,
        "rejected": 403,
        "return_code": 0,
    }
