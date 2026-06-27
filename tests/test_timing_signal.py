from concurrent.futures import Future

from app.services import timing_signal


def test_timing_signal_computes_smas_and_golden_cross_recency():
    closes = [100] * 210 + [102, 104, 106, 108, 110]

    signal = timing_signal.build_timing_signal(closes)

    assert signal["sma50"] == 100.6
    assert signal["sma200"] == 100.15
    assert signal["cross"] == {"type": "golden", "sessions_ago": 4, "recent": True}
    assert signal["momentum_state"] == "trend_intact"


def test_timing_signal_detects_death_cross_and_drawdown():
    closes = [120] * 210 + [116, 112, 108, 104, 100]

    signal = timing_signal.build_timing_signal(
        closes,
        current_price=100,
        high_52w=125,
        low_52w=98,
    )

    assert signal["cross"]["type"] == "death"
    assert signal["cross"]["sessions_ago"] == 4
    assert signal["momentum_state"] == "weakening"
    assert signal["drawdown_from_52w_high_pct"] == 20.0
    assert signal["near_52w_low"] is True


def test_timing_signal_includes_sparkline_30d():
    closes = [100 + (i * 0.2) for i in range(40)]
    signal = timing_signal.build_timing_signal(closes, current_price=closes[-1])
    assert len(signal["sparkline_30d"]) >= 2
    assert signal["sparkline_30d"][0] == 0.0


def test_timing_signal_uses_info_mas_as_thin_history_fallback():
    signal = timing_signal.build_timing_signal(
        [99, 100, 101],
        current_price=105,
        fallback_ma50=100,
        fallback_ma200=95,
    )

    assert signal["source"] == "history"
    assert signal["sma50"] == 100
    assert signal["sma200"] == 95
    assert signal["vs50d_pct"] == 5.0
    assert signal["vs200d_pct"] == 10.5


def test_batched_history_is_concurrent_deduped_and_cached(monkeypatch):
    timing_signal.clear_history_cache()
    calls = []
    executor_sizes = []

    def fake_fetch(ticker, period):
        calls.append((ticker, period))
        return [100.0, 101.0]

    class RecordingExecutor:
        def __init__(self, max_workers):
            executor_sizes.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def submit(self, fn, *args):
            future = Future()
            future.set_result(fn(*args))
            return future

    monkeypatch.setattr(timing_signal, "_fetch_history_closes", fake_fetch)
    monkeypatch.setattr(timing_signal, "ThreadPoolExecutor", RecordingExecutor)

    first = timing_signal.get_batched_history_closes(["VOO", "VOO", "AAPL"])
    second = timing_signal.get_batched_history_closes(["AAPL", "VOO"])

    assert first == {"AAPL": [100.0, 101.0], "VOO": [100.0, 101.0]}
    assert second == first
    assert sorted(calls) == [("AAPL", "1y"), ("VOO", "1y")]
    assert executor_sizes == [2]
