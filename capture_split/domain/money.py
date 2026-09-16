"""Dinheiro só em centavos inteiros. Float não entra neste domínio."""

from __future__ import annotations

from typing import NewType

Cents = NewType("Cents", int)

# Case: MDR 4,19% + R$ 0,39. 4,19% = 419 / 10_000.
MDR_RATE_PER_10000 = 419
MDR_FIXED_CENTS = Cents(39)


def require_cents(amount: int) -> Cents:
    if not isinstance(amount, int):
        raise TypeError("valores monetários precisam ser int (centavos)")
    if amount < 0:
        raise ValueError("centavos não podem ser negativos")
    return Cents(amount)


def mdr_amount(
    gross: Cents,
    rate_per_10000: int = MDR_RATE_PER_10000,
    fixed: Cents = MDR_FIXED_CENTS,
) -> Cents:
    """Percentual truncado para baixo; taxa fixa somada depois."""
    percentual = (int(gross) * rate_per_10000) // 10_000
    return Cents(percentual + int(fixed))


def net_after_mdr(gross: Cents, mdr: Cents) -> Cents:
    net = int(gross) - int(mdr)
    if net < 0:
        raise ValueError("MDR maior que o bruto")
    return Cents(net)


def divide_with_remainder_on_first(total: Cents, parts: int) -> list[Cents]:
    """19700/3 -> [6567, 6567, 6566]. Resto nas primeiras parcelas."""
    if parts < 1:
        raise ValueError("parts deve ser >= 1")
    base, rem = divmod(int(total), parts)
    return [Cents(base + (1 if i < rem else 0)) for i in range(parts)]
