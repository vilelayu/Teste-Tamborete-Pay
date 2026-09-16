"""Evento chegando fora de ordem não regride estado nem liquida parcela 2 antes da 1."""

from capture_split.domain.states import CaptureProjection, CaptureStatus, DomainEvent, EventType


def test_stale_seq_is_ignored():
    proj = CaptureProjection()
    first = proj.apply(DomainEvent(seq=2, type=EventType.REFUND_COMPLETED))
    stale = proj.apply(DomainEvent(seq=1, type=EventType.CAPTURE_COMPLETED))

    assert first.applied
    assert stale.ignored
    assert stale.reason == "stale_seq"
    assert proj.status == CaptureStatus.REFUNDED


def test_installment_two_before_one_is_buffered_then_applied():
    proj = CaptureProjection()
    proj.apply(DomainEvent(seq=1, type=EventType.CAPTURE_COMPLETED))

    late = proj.apply(
        DomainEvent(seq=3, type=EventType.INSTALLMENT_SETTLED, installment_index=1)
    )
    assert late.buffered
    assert late.settled_installments == ()

    proj.apply(DomainEvent(seq=2, type=EventType.INSTALLMENT_SETTLED, installment_index=0))
    assert proj.settled_installments == {0, 1}
    assert proj.status == CaptureStatus.CAPTURED
