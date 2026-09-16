"""Split do líquido. Resto na casa do centavo fica com o lojista."""

from __future__ import annotations

from dataclasses import dataclass

from capture_split.domain.money import Cents


@dataclass(frozen=True, slots=True)
class SplitShares:
    merchant: Cents
    affiliate: Cents
    coproducer: Cents

    @property
    def total(self) -> Cents:
        return Cents(int(self.merchant) + int(self.affiliate) + int(self.coproducer))


# Case: 60 / 30 / 10 sobre o líquido. Lojista absorve o remainder.
MERCHANT_PCT = 60
AFFILIATE_PCT = 30
COPRODUCER_PCT = 10


def split_net(
    net: Cents,
    merchant_pct: int = MERCHANT_PCT,
    affiliate_pct: int = AFFILIATE_PCT,
    coproducer_pct: int = COPRODUCER_PCT,
) -> SplitShares:
    if merchant_pct + affiliate_pct + coproducer_pct != 100:
        raise ValueError("percentuais do split precisam somar 100")

    affiliate = Cents((int(net) * affiliate_pct) // 100)
    coproducer = Cents((int(net) * coproducer_pct) // 100)
    merchant = Cents(int(net) - int(affiliate) - int(coproducer))
    shares = SplitShares(merchant=merchant, affiliate=affiliate, coproducer=coproducer)
    if shares.total != net:
        raise RuntimeError("invariante quebrada: split não fecha no líquido")
    return shares
