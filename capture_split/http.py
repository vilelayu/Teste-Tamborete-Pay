from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from capture_split.domain.service import CaptureInDoubt
from capture_split.lambda_handler import get_service, handle_record

app = FastAPI(title="Tamborete Capture Split", version="0.1.0")


class CaptureRequest(BaseModel):
    authorization_id: str
    gross_cents: int = Field(ge=1)
    installments: int = Field(default=3, ge=1, le=12)
    merchant_webhook_url: str = "https://merchant.example/hooks"


@app.post("/captures")
def create_capture(
    body: CaptureRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key é obrigatório")
    try:
        return handle_record(
            {
                "idempotency_key": idempotency_key,
                "authorization_id": body.authorization_id,
                "gross_cents": body.gross_cents,
                "installments": body.installments,
                "merchant_webhook_url": body.merchant_webhook_url,
            }
        )
    except CaptureInDoubt:
        raise HTTPException(
            status_code=409,
            detail="captura in_doubt no adquirente; reenvie com a mesma Idempotency-Key",
        )


@app.get("/health")
def health():
    get_service()
    return {"ok": True}
