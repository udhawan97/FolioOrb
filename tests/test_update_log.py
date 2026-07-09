"""The dedicated, rotating update log writes to the data dir and sanitizes input."""
import pytest

from app import paths
from app.services import update_log


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    update_log._reset_for_tests()
    yield
    update_log._reset_for_tests()


def test_event_writes_to_updates_log(tmp_path):
    update_log.event("download start version=4.4.0 size=100")
    log_file = tmp_path / "logs" / "updates.log"
    assert log_file.exists()
    assert "download start version=4.4.0" in log_file.read_text(encoding="utf-8")


def test_event_strips_newlines(tmp_path):
    update_log.event("legit\nFORGED admin line")
    contents = (tmp_path / "logs" / "updates.log").read_text(encoding="utf-8")
    # The injected newline is removed so it can't forge a separate log line.
    assert "legitFORGED admin line" in contents
