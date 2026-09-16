"""A mesma captura chegando duas vezes — inclusive no mesmo instante."""

from concurrent.futures import ThreadPoolExecutor

from tests.conftest import cmd, make_service
from capture_split.adapters.acquirer import MockAcquirer


def test_same_capture_twice_sequential():
    acquirer = MockAcquirer()
    service = make_service(acquirer)

    first = service.capture(cmd())
    second = service.capture(cmd())

    assert first.capture_id == second.capture_id
    assert first.acquirer_capture_id == second.acquirer_capture_id
    assert acquirer.calls == 1
    assert first.status == "captured"


def test_same_capture_twice_concurrent():
    acquirer = MockAcquirer(delay=0.05)
    service = make_service(acquirer)
    request = cmd()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(service.capture, request)
        b = pool.submit(service.capture, request)
        results = [a.result(), b.result()]

    ids = {r.capture_id for r in results}
    assert len(ids) == 1
    assert acquirer.calls == 1
    assert results[0].net_cents == results[1].net_cents == 18836
