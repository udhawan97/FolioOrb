"""
Regression test for concurrent token accounting.

Sync FastAPI handlers run in a threadpool, so several dashboard requests can call
ai_service._track_usage() at the same time. The accumulator is a non-atomic dict
`+=`, so every mutation must happen while _USAGE_LOCK is held or updates get lost.

Reproducing a lost update deterministically is unreliable on CPython, so instead we
assert the invariant that makes the code safe: the accumulator dict is only ever
mutated while the lock is held. This fails on the unlocked version and passes once
the read-modify-write is guarded.
"""
import threading

from app.services import ai_service


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _LockAssertingDict(dict):
    """A dict that asserts _USAGE_LOCK is held whenever it is mutated."""

    def __setitem__(self, key, value):
        assert ai_service._USAGE_LOCK.locked(), (
            "token accumulator mutated without holding _USAGE_LOCK"
        )
        super().__setitem__(key, value)


def test_track_usage_mutates_only_under_lock(monkeypatch):
    guarded = _LockAssertingDict({"total_in": 0, "total_out": 0})
    monkeypatch.setattr(ai_service, "_TOKEN_USAGE", guarded)

    ai_service._track_usage("model", _FakeUsage(input_tokens=3, output_tokens=2))

    total = ai_service.get_accumulated_usage()
    assert total == {"total_in": 3, "total_out": 2}


def test_track_usage_accumulates_under_thread_contention(monkeypatch):
    """Smoke test: heavy concurrent use still lands on the exact expected total."""
    monkeypatch.setattr(ai_service, "_TOKEN_USAGE", {"total_in": 0, "total_out": 0})

    threads_count = 16
    increments = 5000
    usage = _FakeUsage(input_tokens=3, output_tokens=2)
    barrier = threading.Barrier(threads_count)

    def worker():
        barrier.wait()
        for _ in range(increments):
            ai_service._track_usage("model", usage)

    workers = [threading.Thread(target=worker) for _ in range(threads_count)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()

    total = ai_service.get_accumulated_usage()
    assert total["total_in"] == threads_count * increments * usage.input_tokens
    assert total["total_out"] == threads_count * increments * usage.output_tokens
