# Teste-Tamborete-Pay

Destino: **AWS Lambda + SQS**. Não há deploy. O handler em
`capture_split/lambda_handler.py` é o contrato.

## Como rodar

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn capture_split.http:app --reload
```

```bash
curl -s -X POST http://127.0.0.1:8000/captures \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: sale-197-3x' \
  -d '{"authorization_id":"auth-001","gross_cents":19700,"installments":3}'
```

`docker-compose.yml` sobe Postgres 16 e DynamoDB Local. Os testes não
dependem disso: o schema SQL e o put condicional estão exercitados in-process.

## Venda de exemplo (centavos)

| | |
|---|---|
| Bruto | 19700 |
| MDR % `floor(19700 × 419 / 10000)` | 825 |
| MDR fixo | 39 |
| Líquido | 18836 |
| Afiliado 30% (floor) | 5650 |
| Coprodutor 10% (floor) | 1883 |
| Lojista (resto) | 11303 |
| Parcelas do bruto | 6567 + 6567 + 6566 (D+30, D+60, D+90) |


Ledger (partida dobrada): débito `card_receivable` 19700; créditos
`acquirer_mdr` 864 + payables do split. Se débito ≠ crédito, a captura aborta.

## O que vai para onde

**PostgreSQL** (fonte da verdade do dinheiro): captura, linhas do ledger,
agenda de liquidação, outbox do evento `capture.completed`. Relacional
porque conciliação, estorno e relatório precisam de join e da invariante
débito = crédito numa transação.

**DynamoDB** (corrida e retry): `Idempotency-Key` com `attribute_not_exists(pk)`,
snapshot da resposta, status `pending | in_doubt | completed`. Acesso por
chave, TTL, e a primitiva certa para duas Lambdas no mesmo instante.
SQS reentrega a mesma `messageId`; a key de negócio ainda é a
`Idempotency-Key` do lojista.

## Lambda / SQS

- Pool/conexão no global do módulo (cold start vs invocação quente).
- Timeout da função **menor** que a visibility timeout da fila.
- `CaptureInDoubt` devolve a mensagem (`batchItemFailures`) para retry.
- Depois do teto: DLQ. Não reprocessar cego: `find_capture` no adquirente
  antes de capturar de novo.
- Partial batch failure: só a mensagem ruim volta.

## Webhook

Body canônico JSON, HMAC-SHA256 de `{timestamp}.{body}`, headers
`X-Tamborete-Signature` e `X-Tamborete-Timestamp`. O lojista confirma
que o evento veio da gente recalculando o HMAC com o secret compartilhado
e rejeitando timestamp fora de 5 minutos (anti-replay). Retry com backoff
exponencial; após o teto o outbox marca `dlq`.

Captura no ledger **antes** do HTTP do webhook. Webhook falho não duplica
captura; a entrega retenta.

## Eventos fora de ordem

Projeção com `seq` monotônico: evento stale é ignorado e **não regride**
status. Liquidação de parcela `n` só aplica se `n-1` já liquidou; senão
fica buffered.

Vocabulário: autorização ≠ captura ≠ liquidação ≠ estorno.

## O estorno total chega no D+45

A primeira parcela já foi liquidada e o afiliado já sacou. Liquidação
paga é fato: o desenho não “desfaz o Pix”. O estorno entra como novo
lançamento no ledger (não como delete) e as parcelas 2 e 3 deixam de
liquidar — receivables cancelados contra o adquirente.

A fatia já paga ao afiliado vira obrigação de clawback na conta dele. Se
o saldo não cobre, o risco operacional fica no lojista (dono do split e
quem recebeu o maior pedaço do líquido), não na plataforma imprimindo
centavos negativos no ar. Coprodutor e lojista fazem netting no que ainda
não liquidou. O lojista recebe webhook `refund.completed`. A conciliação
de fim de dia casa o estorno do adquirente com o que o ledger deve —
incluindo o buraco do saque do afiliado, que vira fila de cobrança, não
silêncio.

Este fluxo não está implementado ponta a ponta de propósito. O modelo
(o que é irreversível, quem absorve) está no status e no ledger para a
conversa presencial.

## Testes

```bash
pytest
```

- `test_idempotency.py` — replay sequencial e duas threads no mesmo instante
- `test_split.py` — venda R$ 197,00 / 3x que não fecha no centavo
- `test_ordering.py` — seq stale e parcela 2 antes da 1
- `test_acquirer_timeout.py` — timeout local com captura remota; retry não captura de novo

## Uso de IA

IA (Cursor / agente) escreveu a primeira versão do esqueleto, domínio em
centavos.
