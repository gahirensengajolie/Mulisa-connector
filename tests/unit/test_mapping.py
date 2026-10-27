import pytest
from app.schemas.screening import GreenbankPaymentInput
from app.services.mapping import map_to_mulisa_payload

kes_dynamic_cases = [(str(val / 100), "KES", val) for val in range(101, 301)]
rwf_dynamic_cases = [(str(val), "RWF", val) for val in range(5000, 5200)]

static_boundary_cases = [
    ("100.00", "KES", 10000),
    ("0.01", "KES", 1),
    ("999999.99", "KES", 99999999),
    ("250000", "RWF", 250000),
    ("150.75", "kes", 15075),
]

@pytest.mark.parametrize(
    "amount, currency, expected_minor_units",
    static_boundary_cases + kes_dynamic_cases + rwf_dynamic_cases
)
def test_mapping_amounts_and_currencies_matrix(amount, currency, expected_minor_units):
    payload = GreenbankPaymentInput(
        reference=f"REF-{amount}-{currency}",
        amount=amount,
        currency=currency,
        debtor={"msisdn": "250788000111", "name": "Aline Uwase", "wallet": "GB-0001"},
        creditor={"msisdn": "250722000333", "name": "Eric Mugisha", "provider": "bluemobile"},
        createdAt="2026-10-14T16:40:00Z"
    )
    mapped = map_to_mulisa_payload(payload)
    assert mapped["transaction"]["amount"] == expected_minor_units
