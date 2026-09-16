from capture_split.adapters.webhooks import (
    RetryingWebhookDispatcher,
    sign_payload,
    verify_signature,
)
from capture_split.lambda_handler import handler, reset_service
from tests.conftest import make_service


def test_merchant_can_verify_hmac():
    body = b'{"event":"capture.completed"}'
    ts = "1710000000"
    sig = sign_payload("s3cret", ts, body)
    assert verify_signature("s3cret", ts, body, sig, now=1710000000)
    assert not verify_signature("s3cret", ts, body, sig, now=1710000000 + 301)
    assert not verify_signature("other", ts, body, sig, now=1710000000)


def test_webhook_retries_then_succeeds():
    calls = {"n": 0}

    def flaky(url, body, headers):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("down")
        return 200

    dispatcher = RetryingWebhookDispatcher("s", flaky, sleeper=lambda _: None)
    result = dispatcher.dispatch("https://merchant.example/hooks", {"event": "capture.completed"})
    assert result["delivered"] is True
    assert result["attempts"] == 3
    assert verify_signature("s", result["timestamp"], __import__("json").dumps({"event": "capture.completed"}, separators=(",", ":"), sort_keys=True).encode(), result["signature"], now=int(result["timestamp"]))


def test_sqs_redelivery_is_idempotent():
    service = make_service()
    reset_service(service)
    event = {
        "Records": [
            {
                "messageId": "m1",
                "body": '{"idempotency_key":"k1","authorization_id":"a1","gross_cents":19700,"installments":3}',
            },
            {
                "messageId": "m1",
                "body": '{"idempotency_key":"k1","authorization_id":"a1","gross_cents":19700,"installments":3}',
            },
        ]
    }
    result = handler(event, None)
    assert result["batchItemFailures"] == []
    stored = service._ledger.get_by_idempotency("k1")
    assert stored is not None
    assert service._acquirer.calls == 1
    reset_service(None)
