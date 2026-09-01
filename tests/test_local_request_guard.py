"""The local HTTP boundary rejects requests before any mutation handler runs."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import run
from app.services.local_request_guard import LocalRequestGuardMiddleware


def _guarded_app(origins: list[str]) -> tuple[FastAPI, dict[str, int]]:
    application = FastAPI()
    calls = {"mutations": 0}

    @application.post("/mutate")
    def mutate():
        calls["mutations"] += 1
        return {"ok": True}

    @application.get("/read")
    def read():
        return {"ok": True}

    application.add_middleware(
        LocalRequestGuardMiddleware,
        allowed_origins=origins,
    )
    return application, calls


def test_source_launcher_is_loopback_only():
    assert run.HOST == "127.0.0.1"


def test_actual_application_installs_the_local_request_guard():
    from app.main import app

    assert any(
        middleware.cls is LocalRequestGuardMiddleware
        for middleware in app.user_middleware
    )


def test_source_browser_mutation_with_matching_local_origin_passes():
    app, calls = _guarded_app(
        ["http://localhost:8000", "http://127.0.0.1:8000"]
    )
    client = TestClient(app, base_url="http://localhost:8000")

    response = client.post("/mutate", headers={"Origin": "http://localhost:8000"})

    assert response.status_code == 200
    assert calls["mutations"] == 1


def test_desktop_dynamic_port_and_loopback_alias_pass():
    port = 49173
    app, calls = _guarded_app(
        [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
    )
    client = TestClient(app, base_url=f"http://127.0.0.1:{port}")

    response = client.post(
        "/mutate", headers={"Origin": f"http://localhost:{port}"}
    )

    assert response.status_code == 200
    assert calls["mutations"] == 1


def test_reads_do_not_require_origin_but_still_require_local_host():
    app, _calls = _guarded_app(["http://localhost:8000"])

    assert TestClient(app, base_url="http://localhost:8000").get("/read").status_code == 200
    assert TestClient(app, base_url="http://attacker.example").get("/read").status_code == 400


@pytest.mark.parametrize("host", ("localhost:not-a-port", "localhost:8000?"))
def test_malformed_host_rejects_before_mutation(host):
    app, calls = _guarded_app(["http://localhost:8000"])
    client = TestClient(app, base_url="http://localhost:8000")

    response = client.post(
        "/mutate",
        headers={"Host": host, "Origin": "http://localhost:8000"},
    )

    assert response.status_code == 400
    assert calls["mutations"] == 0


def test_missing_host_rejects_before_mutation():
    app, calls = _guarded_app(["http://localhost:8000"])
    client = TestClient(app, base_url="http://localhost:8000")

    response = client.post(
        "/mutate", headers={"Host": "", "Origin": "http://localhost:8000"}
    )

    assert response.status_code == 400
    assert calls["mutations"] == 0


@pytest.mark.parametrize(
    "origin",
    (
        None,
        "null",
        "https://attacker.example",
        "http://localhost:9999",
        "http://localhost:8000#",
    ),
)
def test_missing_null_hostile_and_wrong_port_origins_change_nothing(origin):
    app, calls = _guarded_app(["http://localhost:8000"])
    client = TestClient(app, base_url="http://localhost:8000")
    headers = {} if origin is None else {"Origin": origin}

    response = client.post("/mutate", headers=headers)

    assert response.status_code == 403
    assert calls["mutations"] == 0
