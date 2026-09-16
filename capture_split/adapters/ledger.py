from __future__ import annotations

import json
import sqlite3
import threading
from capture_split.domain.service import CaptureRecord


class MemoryLedgerStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_id: dict[str, CaptureRecord] = {}
        self._by_key: dict[str, CaptureRecord] = {}
        self._outbox: dict[str, list[dict]] = {}

    def save_capture(self, record: CaptureRecord) -> None:
        with self._lock:
            self._by_id[record.capture_id] = record
            self._by_key[record.idempotency_key] = record

    def get_by_idempotency(self, key: str) -> CaptureRecord | None:
        return self._by_key.get(key)

    def append_outbox(self, capture_id: str, event: dict) -> None:
        with self._lock:
            self._outbox.setdefault(capture_id, []).append(event)

    def list_outbox(self, capture_id: str) -> list[dict]:
        return list(self._outbox.get(capture_id, []))


SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY,
    authorization_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    gross_cents INTEGER NOT NULL,
    mdr_cents INTEGER NOT NULL,
    net_cents INTEGER NOT NULL,
    split_json TEXT NOT NULL,
    ledger_json TEXT NOT NULL,
    installments_json TEXT NOT NULL,
    webhook_json TEXT NOT NULL,
    acquirer_capture_id TEXT
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    account TEXT NOT NULL,
    direction TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    FOREIGN KEY (capture_id) REFERENCES captures(capture_id)
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def _record_from_row(row: sqlite3.Row) -> CaptureRecord:
    return CaptureRecord(
        capture_id=row["capture_id"],
        authorization_id=row["authorization_id"],
        idempotency_key=row["idempotency_key"],
        status=row["status"],
        gross_cents=row["gross_cents"],
        mdr_cents=row["mdr_cents"],
        net_cents=row["net_cents"],
        split=json.loads(row["split_json"]),
        ledger=json.loads(row["ledger_json"]),
        installments=json.loads(row["installments_json"]),
        webhook=json.loads(row["webhook_json"]),
        acquirer_capture_id=row["acquirer_capture_id"],
    )


class SqliteLedgerStore:
    """Schema equivalente ao PostgreSQL do case; SQLite nos testes, Postgres no compose."""

    def __init__(self, dsn: str = ":memory:"):
        self._conn = sqlite3.connect(dsn, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(SCHEMA)

    def save_capture(self, record: CaptureRecord) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO captures (
                    capture_id, authorization_id, idempotency_key, status,
                    gross_cents, mdr_cents, net_cents, split_json, ledger_json,
                    installments_json, webhook_json, acquirer_capture_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capture_id) DO UPDATE SET
                    status=excluded.status,
                    webhook_json=excluded.webhook_json
                """,
                (
                    record.capture_id,
                    record.authorization_id,
                    record.idempotency_key,
                    record.status,
                    record.gross_cents,
                    record.mdr_cents,
                    record.net_cents,
                    json.dumps(record.split),
                    json.dumps(record.ledger),
                    json.dumps(record.installments),
                    json.dumps(record.webhook),
                    record.acquirer_capture_id,
                ),
            )
            self._conn.execute("DELETE FROM ledger_entries WHERE capture_id = ?", (record.capture_id,))
            self._conn.executemany(
                "INSERT INTO ledger_entries (capture_id, account, direction, amount_cents) VALUES (?, ?, ?, ?)",
                [
                    (record.capture_id, line["account"], line["direction"], line["amount_cents"])
                    for line in record.ledger
                ],
            )

    def get_by_idempotency(self, key: str) -> CaptureRecord | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM captures WHERE idempotency_key = ?", (key,)
            )
            row = cur.fetchone()
        return _record_from_row(row) if row else None

    def append_outbox(self, capture_id: str, event: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO outbox (capture_id, payload_json) VALUES (?, ?)",
                (capture_id, json.dumps(event)),
            )

    def list_outbox(self, capture_id: str) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM outbox WHERE capture_id = ? ORDER BY id",
                (capture_id,),
            )
            return [json.loads(r[0]) for r in cur.fetchall()]
