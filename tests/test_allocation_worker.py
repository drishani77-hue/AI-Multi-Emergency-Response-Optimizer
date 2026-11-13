import threading

from backend.allocation_worker import AllocationWorker


class FakeCoordinator:
    def __init__(self, fail_first=False):
        self.timeout_calls = 0
        self.pass_calls = 0
        self.fail_first = fail_first
        self.lock = threading.Lock()
        self.called = threading.Event()

    def process_allocation_timeouts(self):
        with self.lock:
            self.timeout_calls += 1
            call_number = self.timeout_calls
            self.called.set()

        if self.fail_first and call_number == 1:
            raise RuntimeError("simulated timeout failure")

    def run_coordinator_pass(self):
        with self.lock:
            self.pass_calls += 1
            self.called.set()


def test_worker_starts_once_and_stops_cleanly():
    coordinator = FakeCoordinator()
    worker = AllocationWorker(
        coordinator,
        tick_seconds=0.01,
        pending_pass_interval=2,
    )

    worker.start()
    worker.start()

    assert coordinator.called.wait(timeout=1)
    assert worker.stop(timeout=2) is True
    assert worker.is_running is False
    assert coordinator.timeout_calls >= 1


def test_worker_runs_periodic_pending_passes():
    coordinator = FakeCoordinator()
    worker = AllocationWorker(
        coordinator,
        tick_seconds=0.01,
        pending_pass_interval=2,
    )

    worker.start()
    try:
        deadline = threading.Event()
        assert coordinator.called.wait(timeout=1)

        import time
        end_time = time.monotonic() + 1

        while coordinator.pass_calls < 1 and time.monotonic() < end_time:
            deadline.wait(0.01)

        assert coordinator.pass_calls >= 1
    finally:
        assert worker.stop(timeout=2) is True


def test_worker_continues_after_cycle_failure():
    coordinator = FakeCoordinator(fail_first=True)
    worker = AllocationWorker(
        coordinator,
        tick_seconds=0.01,
        pending_pass_interval=2,
    )

    worker.start()
    try:
        import time
        end_time = time.monotonic() + 1

        while coordinator.timeout_calls < 2 and time.monotonic() < end_time:
            time.sleep(0.01)

        assert coordinator.timeout_calls >= 2
    finally:
        assert worker.stop(timeout=2) is True


def test_worker_can_stop_before_start():
    worker = AllocationWorker(FakeCoordinator())

    assert worker.stop() is True
    assert worker.is_running is False
