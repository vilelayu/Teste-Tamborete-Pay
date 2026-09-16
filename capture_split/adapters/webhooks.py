"""HMAC-SHA256 + timestamp. O lojista confirma origem recalculando a assinatura."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass


SIGNATURE_HEADER = "X-Tamborete-Signature"
TIMESTAMP_HEADER = "X-Tamborete-Timestamp"
REPLAY_WINDOW_SECONDS = 300


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(
        secret.encode(),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    )
    return mac.hexdigest()


def verify_signature(
    secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now: int | None = None,
) -> bool:
    now = int(time.time()) if now is None else now
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(now - ts) > REPLAY_WINDOW_SECONDS:
        return False
    expected = sign_payload(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


@dataclass
class WebhookAttempt:
    attempt: int
    ok: bool
    status_code: int | None
    error: str | None = None


class RetryingWebhookDispatcher:
    def __init__(
        self,
        secret: str,
        post,
        *,
        max_attempts: int = 4,
        backoff_seconds: tuple[float, ...] = (0.05, 0.1, 0.2),
        sleeper=time.sleep,
        clock=lambda: int(time.time()),
    ):
        self.secret = secret
        self._post = post
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._sleep = sleeper
        self._clock = clock
        self.attempts: list[WebhookAttempt] = []

    def dispatch(self, url: str, payload: dict) -> dict:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        timestamp = str(self._clock())
        signature = sign_payload(self.secret, timestamp, body)
        headers = {
            SIGNATURE_HEADER: signature,
            TIMESTAMP_HEADER: timestamp,
            "Content-Type": "application/json",
        }

        last_error = "exhausted"
        for attempt in range(1, self.max_attempts + 1):
            try:
                status = self._post(url, body, headers)
                ok = 200 <= int(status) < 300
                self.attempts.append(WebhookAttempt(attempt, ok, int(status)))
                if ok:
                    return {
                        "delivered": True,
                        "attempts": attempt,
                        "signature": signature,
                        "timestamp": timestamp,
                    }
                last_error = f"http_{status}"
            except Exception as exc:
                self.attempts.append(WebhookAttempt(attempt, False, None, str(exc)))
                last_error = str(exc)
            if attempt < self.max_attempts:
                delay = self.backoff_seconds[min(attempt - 1, len(self.backoff_seconds) - 1)]
                self._sleep(delay)

        return {
            "delivered": False,
            "attempts": self.max_attempts,
            "dlq": True,
            "error": last_error,
            "signature": signature,
            "timestamp": timestamp,
        }


def local_post_ok(url: str, body: bytes, headers: dict) -> int:
    return 200
