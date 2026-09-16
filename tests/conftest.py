from datetime import UTC, datetime

from capture_split.adapters.acquirer import MockAcquirer
from capture_split.adapters.idempotency import MemoryIdempotencyStore
from capture_split.adapters.ledger import SqliteLedgerStore
from capture_split.adapters.webhooks import RetryingWebhookDispatcher, local_post_ok
from capture_split.domain.service import CaptureCommand, CaptureService

GROSS = 19700


def make_service(acquirer: MockAcquirer | None = None, post=local_post_ok) -> CaptureService:
    return CaptureService(
        idempotency=MemoryIdempotencyStore(),
        ledger=SqliteLedgerStore(":memory:"),
        acquirer=acquirer or MockAcquirer(),
        webhooks=RetryingWebhookDispatcher("test-secret", post, sleeper=lambda _: None),
        clock=lambda: datetime(2026, 9, 15, tzinfo=UTC),
    )


def cmd(key: str = "idem-1", auth: str = "auth-1") -> CaptureCommand:
    return CaptureCommand(
        idempotency_key=key,
        authorization_id=auth,
        gross_cents=GROSS,
        installments=3,
        merchant_webhook_url="https://merchant.example/hooks",
    )
