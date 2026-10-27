from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.payment import PaymentIn
from tests.conftest import make_payment


def test_a_good_payment_parses_and_normalises_the_timestamp() -> None:
    payment = PaymentIn.model_validate(make_payment(createdAt="2026-10-14T18:40:00+02:00"))
    assert payment.created_at.utcoffset() is not None
    assert (
        payment.created_at.timestamp()
        == PaymentIn.model_validate(make_payment()).created_at.timestamp()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"amount": 250000},  # a JSON number: money must be a string
        {"amount": None},
        {"currency": "rwf"},
        {"reference": "a b/../c"},
        {"debtor": {"msisdn": "abc", "name": "A B", "wallet": "GB-1"}},
        {"debtor": "Aline"},
        {"creditor": {"msisdn": "250722000333", "name": "", "provider": "bluemobile"}},
        {"createdAt": "2026-10-14T16:40:00"},  # no time zone
        {"createdAt": 1760460000},  # a unix timestamp number
        {"createdAt": "2026-02-30T10:00:00Z"},  # not a real date
    ],
)
def test_rejects_malformed_payments(mutation: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PaymentIn.model_validate(make_payment(**mutation))
