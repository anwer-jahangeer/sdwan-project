"""Tests for MainWindow.wait_for_worker_to_finish: a pure, injectable
helper (fake worker + fake pump_events, no QApplication/QThread required)
that guarantees callers never drop a worker reference or read its final
steering status before its run() method has actually returned -- see
gui/main_window.py stop_monitoring/closeEvent, which rely on this to avoid
destroying a live QThread or inspecting steering settings mid-restore."""

from __future__ import annotations

from multilink_manager.gui.main_window import wait_for_worker_to_finish


class _FakeWorker:
    def __init__(self, finishes_after_calls: int):
        self._finishes_after_calls = finishes_after_calls
        self.calls = 0

    def wait(self, ms):
        self.calls += 1
        return self.calls >= self._finishes_after_calls


def test_returns_true_immediately_when_already_finished():
    worker = _FakeWorker(finishes_after_calls=1)
    pumps = []
    result = wait_for_worker_to_finish(worker, chunk_ms=100, max_total_ms=1000, pump_events=lambda: pumps.append(1))
    assert result is True
    assert worker.calls == 1
    assert pumps == []  # no pumping needed if it finished on the first check


def test_returns_true_after_several_chunks_and_pumps_events_between():
    worker = _FakeWorker(finishes_after_calls=4)
    pumps = []
    result = wait_for_worker_to_finish(worker, chunk_ms=100, max_total_ms=10000, pump_events=lambda: pumps.append(1))
    assert result is True
    assert worker.calls == 4
    assert len(pumps) == 3  # pumped once after each non-finished chunk


def test_returns_false_when_max_total_exceeded_without_dropping_semantics():
    worker = _FakeWorker(finishes_after_calls=1_000_000)
    pumps = []
    result = wait_for_worker_to_finish(worker, chunk_ms=100, max_total_ms=500, pump_events=lambda: pumps.append(1))
    assert result is False
    # Must have kept polling for the full budget, never given up early.
    assert worker.calls * 100 >= 500


def test_default_pump_events_not_invoked_when_finished_immediately():
    """When pump_events is not supplied, the default QApplication.processEvents
    lookup must not even be touched if the worker finishes on the very
    first check -- guards against import-time/QApplication requirements
    leaking into this otherwise pure helper for the common fast case."""
    worker = _FakeWorker(finishes_after_calls=1)
    result = wait_for_worker_to_finish(worker, chunk_ms=50, max_total_ms=1000)
    assert result is True
