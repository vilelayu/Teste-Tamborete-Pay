"""Split que não fecha no centavo: remainder explícito no lojista."""

from capture_split.domain.money import Cents, mdr_amount, net_after_mdr
from capture_split.domain.split import split_net
from tests.conftest import cmd, make_service


def test_example_sale_split_does_not_round_evenly():
    gross = Cents(19700)
    mdr = mdr_amount(gross)
    net = net_after_mdr(gross, mdr)
    shares = split_net(net)

    assert int(mdr) == 864
    assert int(net) == 18836
    assert int(shares.affiliate) == 5650
    assert int(shares.coproducer) == 1883
    assert int(shares.merchant) == 11303
    assert int(shares.total) == int(net)
    assert int(shares.merchant) != (int(net) * 60) // 100
    assert int(shares.merchant) - (int(net) * 60) // 100 == 2


def test_capture_ledger_balances_and_installments():
    record = make_service().capture(cmd())
    debits = sum(l["amount_cents"] for l in record.ledger if l["direction"] == "debit")
    credits = sum(l["amount_cents"] for l in record.ledger if l["direction"] == "credit")
    assert debits == credits == 19700
    amounts = [i["amount_cents"] for i in record.installments]
    assert amounts == [6567, 6567, 6566]
    assert sum(amounts) == 19700
    assert record.installments[0]["settle_on"] == "2026-10-15"
    assert record.installments[2]["settle_on"] == "2026-12-14"
    assert record.split["remainder_policy"] == "merchant"
