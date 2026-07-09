# pylint: disable=protected-access,redefined-outer-name,unused-argument,unnecessary-lambda
"""Consecutive-failed-launch counter that gates the proactive rollback offer."""
import pytest

from app import paths
from app.services import launch_health


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path


def test_record_and_reset():
    assert launch_health.record_launch_attempt() == 1
    assert launch_health.record_launch_attempt() == 2
    assert launch_health.failed_launch_count() == 2
    launch_health.mark_launch_healthy()
    assert launch_health.failed_launch_count() == 0


def test_offer_requires_threshold_and_rollback_point():
    from app import app_settings

    # One failure: below threshold.
    launch_health.record_launch_attempt()
    assert launch_health.should_offer_rollback() is False

    # Two failures but no rollback point yet.
    launch_health.record_launch_attempt()
    assert launch_health.should_offer_rollback() is False

    # Two failures AND a rollback point → offer.
    app_settings.save_settings({"rollback_point": {"version": "4.3.0"}})
    assert launch_health.should_offer_rollback() is True

    # A healthy launch clears the offer.
    launch_health.mark_launch_healthy()
    assert launch_health.should_offer_rollback() is False
