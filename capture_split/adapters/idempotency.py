from __future__ import annotations

import threading
from dataclasses import dataclass, field

from capture_split.domain.service import CaptureRecord


@dataclass
class _Slot:
    status: str  # pending | in_doubt | completed
    authorization_id: str | None = None
    snapshot: CaptureRecord | None = None
    message_id: str | None = None
    done: threading.Event = field(default_factory=threading.Event)


class MemoryIdempotencyStore:
    """Put condicional com lock. Equivale ao DynamoDB attribute_not_exists(pk)."""

    def __init__(self, wait_timeout: float = 2.0):
        self._lock = threading.Lock()
        self._slots: dict[str, _Slot] = {}
        self._wait_timeout = wait_timeout

    def begin(self, key: str, message_id: str | None) -> bool:
        with self._lock:
            slot = self._slots.get(key)
            if slot is None:
                self._slots[key] = _Slot(status="pending", message_id=message_id)
                return True
            if slot.status == "in_doubt":
                slot.status = "pending"
                slot.done.clear()
                return True
            if slot.status == "completed":
                return False
            return False

    def complete(self, key: str, snapshot: CaptureRecord) -> None:
        with self._lock:
            slot = self._slots[key]
            slot.status = "completed"
            slot.snapshot = snapshot
            slot.done.set()

    def fail(self, key: str) -> None:
        with self._lock:
            slot = self._slots.get(key)
            if slot is None or slot.status == "completed":
                return
            if slot.status == "in_doubt":
                return
            del self._slots[key]

    def get(self, key: str) -> CaptureRecord | None:
        slot = self._slots.get(key)
        if slot and slot.snapshot:
            return slot.snapshot
        return None

    def mark_in_doubt(self, key: str, authorization_id: str) -> None:
        with self._lock:
            slot = self._slots[key]
            slot.status = "in_doubt"
            slot.authorization_id = authorization_id

    def get_in_doubt(self, key: str) -> str | None:
        slot = self._slots.get(key)
        if slot and slot.status == "in_doubt":
            return slot.authorization_id
        return None

    def wait_until_done(self, key: str) -> CaptureRecord | None:
        slot = self._slots.get(key)
        if slot is None:
            return None
        slot.done.wait(timeout=self._wait_timeout)
        return slot.snapshot
