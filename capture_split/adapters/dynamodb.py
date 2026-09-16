"""Idempotência no DynamoDB (produção).

PutItem com ConditionExpression attribute_not_exists(pk).
pk = Idempotency-Key. Item guarda snapshot JSON e status
(pending | in_doubt | completed). TTL de 24h.

Este módulo não é importado nos testes para não exigir AWS.
O MemoryIdempotencyStore replica a mesma semântica de corrida.
"""

CONDITION_PUT = {
    "TableName": "capture_idempotency",
    "Item": {
        "pk": {"S": "{idempotency_key}"},
        "status": {"S": "pending"},
    },
    "ConditionExpression": "attribute_not_exists(pk)",
}
