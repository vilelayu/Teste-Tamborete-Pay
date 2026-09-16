"""Máquina de estados: autorização ≠ captura ≠ liquidação ≠ estorno.

Eventos fora de ordem não regridem status. Seq monotônico; parcela só
liquida se a anterior já liquidou (senão o evento fica buffered).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CaptureStatus(StrEnum):
    AUTHORIZED = "authorized"
    IN_DOUBT = "in_doubt"
    CAPTURED = "captured"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


_FORWARD: dict[CaptureStatus, frozenset[CaptureStatus]] = {
    CaptureStatus.AUTHORIZED: frozenset(
        {
            CaptureStatus.IN_DOUBT,
            CaptureStatus.CAPTURED,
            CaptureStatus.REFUNDED,
        }
    ),
    CaptureStatus.IN_DOUBT: frozenset(
        {CaptureStatus.CAPTURED, CaptureStatus.REFUNDED}
    ),
    CaptureStatus.CAPTURED: frozenset(
        {CaptureStatus.PARTIALLY_REFUNDED, CaptureStatus.REFUNDED}
    ),
    CaptureStatus.PARTIALLY_REFUNDED: frozenset({CaptureStatus.REFUNDED}),
    CaptureStatus.REFUNDED: frozenset(),
}


class EventType(StrEnum):
    CAPTURE_COMPLETED = "capture.completed"
    INSTALLMENT_SETTLED = "installment.settled"
    REFUND_COMPLETED = "refund.completed"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    seq: int
    type: EventType
    installment_index: int | None = None


@dataclass(slots=True)
class ApplyResult:
    applied: bool
    ignored: bool
    buffered: bool
    reason: str
    status: CaptureStatus
    last_seq: int
    settled_installments: tuple[int, ...]


@dataclass
class CaptureProjection:
    status: CaptureStatus = CaptureStatus.AUTHORIZED
    last_seq: int = 0
    settled_installments: set[int] = field(default_factory=set)
    buffered: list[DomainEvent] = field(default_factory=list)
    installment_count: int = 3

    def apply(self, event: DomainEvent) -> ApplyResult:
        if event.seq <= self.last_seq:
            return self._result(
                applied=False,
                ignored=True,
                buffered=False,
                reason="stale_seq",
            )

        if event.type == EventType.INSTALLMENT_SETTLED:
            idx = event.installment_index
            if idx is None:
                raise ValueError("installment.settled exige installment_index")
            expected = 0 if not self.settled_installments else max(self.settled_installments) + 1
            if idx != expected:
                self.buffered.append(event)
                self.buffered.sort(key=lambda e: (e.installment_index or 0, e.seq))
                return self._result(
                    applied=False,
                    ignored=False,
                    buffered=True,
                    reason="out_of_order_installment",
                )

        if event.type == EventType.CAPTURE_COMPLETED:
            self._transition(CaptureStatus.CAPTURED)
        elif event.type == EventType.REFUND_COMPLETED:
            target = (
                CaptureStatus.REFUNDED
                if self.status in {CaptureStatus.CAPTURED, CaptureStatus.PARTIALLY_REFUNDED, CaptureStatus.REFUNDED}
                else CaptureStatus.REFUNDED
            )
            if self.status != CaptureStatus.REFUNDED:
                self._transition(target)
        elif event.type == EventType.INSTALLMENT_SETTLED:
            self.settled_installments.add(event.installment_index or 0)

        self.last_seq = event.seq
        self._drain_buffer()
        return self._result(applied=True, ignored=False, buffered=False, reason="ok")

    def _drain_buffer(self) -> None:
        changed = True
        while changed:
            changed = False
            remaining: list[DomainEvent] = []
            for event in self.buffered:
                if event.type != EventType.INSTALLMENT_SETTLED:
                    remaining.append(event)
                    continue
                expected = 0 if not self.settled_installments else max(self.settled_installments) + 1
                if event.installment_index == expected and event.seq > self.last_seq:
                    self.settled_installments.add(event.installment_index or 0)
                    self.last_seq = max(self.last_seq, event.seq)
                    changed = True
                else:
                    remaining.append(event)
            self.buffered = remaining

    def _transition(self, target: CaptureStatus) -> None:
        if target == self.status:
            return
        allowed = _FORWARD[self.status]
        if target not in allowed:
            return
        self.status = target

    def _result(
        self,
        *,
        applied: bool,
        ignored: bool,
        buffered: bool,
        reason: str,
    ) -> ApplyResult:
        return ApplyResult(
            applied=applied,
            ignored=ignored,
            buffered=buffered,
            reason=reason,
            status=self.status,
            last_seq=self.last_seq,
            settled_installments=tuple(sorted(self.settled_installments)),
        )
