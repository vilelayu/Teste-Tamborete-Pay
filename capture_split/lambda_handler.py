from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from capture_split.adapters.acquirer import MockAcquirer
from capture_split.adapters.idempotency import MemoryIdempotencyStore
from capture_split.adapters.ledger import SqliteLedgerStore
from capture_split.adapters.webhooks import RetryingWebhookDispatcher, local_post_ok
from capture_split.domain.service import CaptureCommand, CaptureInDoubt, CaptureService

log = logging.getLogger(__name__)

# Pool fora do handler: sobrevive a invocações quentes; recria no cold start.
_SERVICE: CaptureService | None = None


def get_service() -> CaptureService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = CaptureService(
            idempotency=MemoryIdempotencyStore(),
            ledger=SqliteLedgerStore("captures.db"),
            acquirer=MockAcquirer(),
            webhooks=RetryingWebhookDispatcher("dev-webhook-secret", local_post_ok),
        )
    return _SERVICE


def reset_service(service: CaptureService | None = None) -> None:
    global _SERVICE
    _SERVICE = service


def handle_record(body: dict, message_id: str | None = None) -> dict:
    cmd = CaptureCommand(
        idempotency_key=body["idempotency_key"],
        authorization_id=body["authorization_id"],
        gross_cents=int(body["gross_cents"]),
        installments=int(body.get("installments", 3)),
        merchant_webhook_url=body.get("merchant_webhook_url", "https://merchant.example/hooks"),
        message_id=message_id,
    )
    record = get_service().capture(cmd)
    return {
        "capture_id": record.capture_id,
        "status": record.status,
        "gross_cents": record.gross_cents,
        "mdr_cents": record.mdr_cents,
        "net_cents": record.net_cents,
        "split": record.split,
        "installments": record.installments,
        "ledger": record.ledger,
        "webhook": record.webhook,
        "acquirer_capture_id": record.acquirer_capture_id,
    }


def handler(event: dict, context: object | None = None) -> dict:
    """Handler Lambda invocado por SQS.

    Reentrega da mesma mensagem: Idempotency-Key + messageId.
    CaptureInDoubt relança para a mensagem voltar à fila (visibilidade)
    até o teto; depois a DLQ. Timeout da função deve ser menor que
    a visibility timeout da fila.
    """
    failures: list[dict] = []
    started = datetime.now(UTC)
    remaining_ms = getattr(context, "get_remaining_time_in_millis", lambda: 30_000)()

    for record in event.get("Records", []):
        if remaining_ms < 5_000:
            failures.append({"itemIdentifier": record.get("messageId")})
            continue
        message_id = record.get("messageId")
        try:
            body = record.get("body")
            payload = json.loads(body) if isinstance(body, str) else body
            handle_record(payload, message_id=message_id)
        except CaptureInDoubt:
            log.warning("capture in_doubt, sqs retry message_id=%s", message_id)
            failures.append({"itemIdentifier": message_id})
        except Exception:
            log.exception("capture failed message_id=%s", message_id)
            failures.append({"itemIdentifier": message_id})

    elapsed = (datetime.now(UTC) - started).total_seconds()
    log.info("batch done elapsed_s=%.3f failures=%s", elapsed, len(failures))
    return {"batchItemFailures": failures}
