"""Orquestração da captura: idempotência, adquirente, ledger, outbox."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from capture_split.domain.money import (
    Cents,
    mdr_amount,
    net_after_mdr,
    require_cents,
    divide_with_remainder_on_first,
)
from capture_split.domain.split import SplitShares, split_net
from capture_split.domain.states import CaptureStatus, DomainEvent, EventType


class DuplicateCapture(Exception):
    """Mesma Idempotency-Key já concluiu uma captura."""

    def __init__(self, snapshot: "CaptureRecord"):
        super().__init__("captura já processada para esta Idempotency-Key")
        self.snapshot = snapshot


class CaptureInDoubt(Exception):
    """Timeout local; adquirente pode ter capturado. Retry deve reconciliar."""


class AcquirerTimeout(Exception):
    def __init__(self, captured_remotely: bool):
        super().__init__("timeout no adquirente")
        self.captured_remotely = captured_remotely


@dataclass(frozen=True, slots=True)
class CaptureCommand:
    idempotency_key: str
    authorization_id: str
    gross_cents: int
    installments: int
    merchant_webhook_url: str
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class LedgerLine:
    account: str
    direction: str  # debit | credit
    amount_cents: int


@dataclass(frozen=True, slots=True)
class InstallmentSchedule:
    index: int
    amount_cents: int
    settle_on: str  # ISO date D+30*(i+1)


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    capture_id: str
    authorization_id: str
    idempotency_key: str
    status: str
    gross_cents: int
    mdr_cents: int
    net_cents: int
    split: dict
    ledger: list[dict]
    installments: list[dict]
    webhook: dict
    acquirer_capture_id: str | None


class IdempotencyStore(Protocol):
    def begin(self, key: str, message_id: str | None) -> bool:
        """Put condicional. True se este caller ganhou a corrida."""

    def complete(self, key: str, snapshot: CaptureRecord) -> None: ...

    def fail(self, key: str) -> None:
        """Libera a key se a captura não chegou a gravar snapshot (erro antes do adquirente)."""

    def get(self, key: str) -> CaptureRecord | None: ...

    def mark_in_doubt(self, key: str, authorization_id: str) -> None: ...

    def get_in_doubt(self, key: str) -> str | None: ...


class LedgerStore(Protocol):
    def save_capture(self, record: CaptureRecord) -> None: ...

    def get_by_idempotency(self, key: str) -> CaptureRecord | None: ...

    def append_outbox(self, capture_id: str, event: dict) -> None: ...

    def list_outbox(self, capture_id: str) -> list[dict]: ...


class Acquirer(Protocol):
    def capture(self, authorization_id: str) -> str:
        """Retorna acquirer_capture_id. Levanta AcquirerTimeout."""

    def find_capture(self, authorization_id: str) -> str | None:
        """Consulta idempotente no adquirente (conciliação pós-timeout)."""


class WebhookDispatcher(Protocol):
    def dispatch(self, url: str, payload: dict) -> dict:
        """Assina, posta, retenta. Retorna metadados da entrega."""


def build_ledger(gross: Cents, mdr: Cents, shares: SplitShares) -> list[LedgerLine]:
    lines = [
        LedgerLine("card_receivable", "debit", int(gross)),
        LedgerLine("acquirer_mdr", "credit", int(mdr)),
        LedgerLine("merchant_payable", "credit", int(shares.merchant)),
        LedgerLine("affiliate_payable", "credit", int(shares.affiliate)),
        LedgerLine("coproducer_payable", "credit", int(shares.coproducer)),
    ]
    debits = sum(l.amount_cents for l in lines if l.direction == "debit")
    credits = sum(l.amount_cents for l in lines if l.direction == "credit")
    if debits != credits:
        raise RuntimeError(f"ledger desbalanceado: debit={debits} credit={credits}")
    return lines


def schedule_installments(gross: Cents, count: int, captured_at: datetime) -> list[InstallmentSchedule]:
    amounts = divide_with_remainder_on_first(gross, count)
    rows = []
    for i, amount in enumerate(amounts):
        settle = captured_at.date() + timedelta(days=30 * (i + 1))
        rows.append(
            InstallmentSchedule(index=i, amount_cents=int(amount), settle_on=settle.isoformat())
        )
    return rows


class CaptureService:
    def __init__(
        self,
        *,
        idempotency: IdempotencyStore,
        ledger: LedgerStore,
        acquirer: Acquirer,
        webhooks: WebhookDispatcher,
        clock=lambda: datetime.now(UTC),
        id_factory=lambda: f"cap_{uuid4().hex}",
    ):
        self._idempotency = idempotency
        self._ledger = ledger
        self._acquirer = acquirer
        self._webhooks = webhooks
        self._clock = clock
        self._id_factory = id_factory

    def capture(self, cmd: CaptureCommand) -> CaptureRecord:
        existing = self._idempotency.get(cmd.idempotency_key)
        if existing is not None:
            return existing

        won = self._idempotency.begin(cmd.idempotency_key, cmd.message_id)
        if not won:
            snapshot = self._wait_snapshot(cmd.idempotency_key)
            if snapshot is None:
                raise CaptureInDoubt()
            return snapshot

        try:
            return self._capture_locked(cmd)
        except Exception:
            in_doubt = self._idempotency.get_in_doubt(cmd.idempotency_key)
            if in_doubt:
                raise
            self._idempotency.fail(cmd.idempotency_key)
            raise

    def _wait_snapshot(self, key: str) -> CaptureRecord | None:
        waiter = getattr(self._idempotency, "wait_until_done", None)
        if waiter is not None:
            snapshot = waiter(key)
            if snapshot:
                return snapshot
        snapshot = self._idempotency.get(key)
        if snapshot:
            return snapshot
        return self._ledger.get_by_idempotency(key)

    def _capture_locked(self, cmd: CaptureCommand) -> CaptureRecord:
        acquirer_id = self._acquirer.find_capture(cmd.authorization_id)
        if acquirer_id is None:
            try:
                acquirer_id = self._acquirer.capture(cmd.authorization_id)
            except AcquirerTimeout as exc:
                self._idempotency.mark_in_doubt(cmd.idempotency_key, cmd.authorization_id)
                if exc.captured_remotely:
                    found = self._acquirer.find_capture(cmd.authorization_id)
                    if found:
                        acquirer_id = found
                    else:
                        raise CaptureInDoubt() from exc
                else:
                    self._idempotency.fail(cmd.idempotency_key)
                    raise

        gross = require_cents(cmd.gross_cents)
        mdr = mdr_amount(gross)
        net = net_after_mdr(gross, mdr)
        shares = split_net(net)
        now = self._clock()
        capture_id = self._id_factory()
        lines = build_ledger(gross, mdr, shares)
        installments = schedule_installments(gross, cmd.installments, now)

        event = DomainEvent(seq=1, type=EventType.CAPTURE_COMPLETED)
        payload = {
            "event": event.type.value,
            "seq": event.seq,
            "capture_id": capture_id,
            "authorization_id": cmd.authorization_id,
            "status": CaptureStatus.CAPTURED.value,
            "gross_cents": int(gross),
            "net_cents": int(net),
            "split": {
                "merchant_cents": int(shares.merchant),
                "affiliate_cents": int(shares.affiliate),
                "coproducer_cents": int(shares.coproducer),
            },
        }
        record = CaptureRecord(
            capture_id=capture_id,
            authorization_id=cmd.authorization_id,
            idempotency_key=cmd.idempotency_key,
            status=CaptureStatus.CAPTURED.value,
            gross_cents=int(gross),
            mdr_cents=int(mdr),
            net_cents=int(net),
            split={
                "merchant_cents": int(shares.merchant),
                "affiliate_cents": int(shares.affiliate),
                "coproducer_cents": int(shares.coproducer),
                "remainder_policy": "merchant",
            },
            ledger=[asdict(line) for line in lines],
            installments=[asdict(row) for row in installments],
            webhook={},
            acquirer_capture_id=acquirer_id,
        )
        self._ledger.save_capture(record)
        self._ledger.append_outbox(capture_id, payload)
        self._idempotency.complete(cmd.idempotency_key, record)
        webhook_meta = self._webhooks.dispatch(cmd.merchant_webhook_url, payload)
        record = CaptureRecord(**{**asdict(record), "webhook": webhook_meta})
        self._ledger.save_capture(record)
        self._idempotency.complete(cmd.idempotency_key, record)
        return record
