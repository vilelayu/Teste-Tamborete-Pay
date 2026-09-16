"""Adquirente responde timeout mas capturou do lado dele."""

import pytest

from capture_split.adapters.acquirer import MockAcquirer
from capture_split.domain.service import CaptureInDoubt
from tests.conftest import cmd, make_service


def test_timeout_after_remote_capture_reconciles_on_retry():
    acquirer = MockAcquirer(mode="timeout_after_capture", find_fails_remaining=1)
    service = make_service(acquirer)

    with pytest.raises(CaptureInDoubt):
        service.capture(cmd())

    assert acquirer.calls == 1
    assert acquirer.find_capture("auth-1") == "acq_auth-1"

    record = service.capture(cmd())

    assert record.status == "captured"
    assert record.acquirer_capture_id == "acq_auth-1"
    assert acquirer.calls == 1
    assert record.net_cents == 18836


def test_timeout_before_capture_does_not_invent_money():
    acquirer = MockAcquirer(mode="timeout_before")
    service = make_service(acquirer)

    with pytest.raises(Exception):
        service.capture(cmd())

    assert acquirer.calls == 1
    assert acquirer.find_capture("auth-1") is None
    assert service._ledger.get_by_idempotency("idem-1") is None
