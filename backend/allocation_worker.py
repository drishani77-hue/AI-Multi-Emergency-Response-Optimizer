"""Background worker for allocation timeout and retry processing."""

import logging
import threading


logger = logging.getLogger(__name__)


class AllocationWorker:
    """Periodically processes allocation deadlines and pending units."""

    def __init__(
        self,
        coordinator,
        *,
        tick_seconds: float = 1.0,
        pending_pass_interval: int = 5,
    ):
        if tick_seconds <= 0:
            raise ValueError("tick_seconds must be positive.")
        if pending_pass_interval <= 0:
            raise ValueError("pending_pass_interval must be positive.")

        self.coordinator = coordinator
        self.tick_seconds = float(tick_seconds)
        self.pending_pass_interval = int(pending_pass_interval)

        self._stop_event = threading.Event()
        self._thread = None
        self._lifecycle_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the worker once; repeated calls do not create extra threads."""
        with self._lifecycle_lock:
            if self.is_running:
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="resqtech-allocation-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> bool:
        """Request shutdown and wait for the worker to exit."""
        self._stop_event.set()
        thread = self._thread

        if thread is None:
            return True

        if thread is threading.current_thread():
            return False

        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        ticks = 0

        while not self._stop_event.wait(self.tick_seconds):
            try:
                self.coordinator.process_allocation_timeouts()
                ticks += 1

                if ticks % self.pending_pass_interval == 0:
                    self.coordinator.run_coordinator_pass()

            except Exception:
                logger.exception("Allocation worker cycle failed.")
