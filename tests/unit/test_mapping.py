from app.schemas.payment import PaymentIn
from app.services.mapping import build_mulisa_request, country_from_msisdn
from tests.conftest import make_payment

BANK = {
    "bank_country": "RW",
    "bank_institution_id": "greenbank",
    "id_prefix": "greenbank",
    "transaction_type": "transfer",
    "channel": "api",
}


def test_minor_units_utc_time_countries_and_idempotency_key() -> None:
    payment = PaymentIn.model_validate(
        make_payment(
            reference="GB-PAY-1",
            currency="KES",
            createdAt="2026-10-14T18:40:00+02:00",
            creditor={
                "msisdn": "254712000555",
                "name": "W T",
                "provider": "bluemobile",
            },
        )
    )
    request = build_mulisa_request(payment, 125050, **BANK)
    assert request.transaction.id == "greenbank-GB-PAY-1"  # bank prefix + reference
    assert request.transaction.amount == 125050
    assert request.transaction.timestamp == "2026-10-14T16:40:00Z"
    assert request.transaction.country_to == "KE"
    assert request.sender.country == "RW"
    assert request.receiver.institution_id == "bluemobile"


def test_unknown_calling_code_leaves_the_country_out_instead_of_guessing() -> None:
    assert country_from_msisdn("99912345678") is None
    assert country_from_msisdn("27821234567") == "ZA"  # a 2-digit calling code
    payment = PaymentIn.model_validate(
        make_payment(creditor={"msisdn": "99912345678", "name": "X Y", "provider": "bluemobile"})
    )
    body = build_mulisa_request(payment, 1000, **BANK).model_dump(exclude_none=True)
    assert "country_to" not in body["transaction"]
    assert "country" not in body["receiver"]
