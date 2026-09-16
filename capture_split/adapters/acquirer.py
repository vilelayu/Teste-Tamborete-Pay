from __future__ import annotations

import threading
import time

from capture_split.domain.service import AcquirerTimeout


class MockAcquirer:
    """Adquirente de teste: sucesso, timeout antes de capturar, ou timeout depois."""

    def __init__(self, mode: str = "ok", delay: float = 0.0, find_fails_remaining: int = 0):
        self.mode = mode
        self.delay = delay
        self.find_fails_remaining = find_fails_remaining
        self.calls = 0
        self._lock = threading.Lock()
        self._captured: dict[str, str] = {}

    def capture(self, authorization_id: str) -> str:
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self.calls += 1
            if authorization_id in self._captured:
                return self._captured[authorization_id]
            if self.mode == "timeout_before":
                raise AcquirerTimeout(captured_remotely=False)
            if self.mode == "timeout_after_capture":
                cap_id = f"acq_{authorization_id}"
                self._captured[authorization_id] = cap_id
                raise AcquirerTimeout(captured_remotely=True)
            cap_id = f"acq_{authorization_id}"
            self._captured[authorization_id] = cap_id
            return cap_id

    def find_capture(self, authorization_id: str) -> str | None:
        if self.find_fails_remaining > 0:
            self.find_fails_remaining -= 1
            return None
        return self._captured.get(authorization_id)

    def find_capture(self, authorization_id: str) -> str | None:
        return self._captured.get(authorization_id)

    def succeed_on_retry(self) -> None:
        self.mode = "ok"
