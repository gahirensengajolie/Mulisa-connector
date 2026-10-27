"""Map greenbank's payment message to Mulisa's POST /api/screen request.
Everything here that the public contract does not state is an ASSUMPTION (see the README)."""

from datetime import timezone

from app.core.reference_data import get_reference_data
from app.schemas.mulisa import MulisaParty, MulisaScreenRequest, MulisaTransaction
from app.schemas.payment import PaymentIn


def country_from_msisdn(msisdn: str) -> str | None:
    """Longest calling-code prefix wins (3 digits, then 2, then 1). Unknown prefix -> None."""
    codes = get_reference_data().calling_codes
    for length in (3, 2, 1):
        country = codes.get(msisdn[:length])
        if country:
            return country
    return None


def build_mulisa_request(
    payment: PaymentIn,
    amount_minor: int,
    *,
    bank_country: str,
    bank_institution_id: str,
    id_prefix: str,
    transaction_type: str,
    channel: str,
) -> MulisaScreenRequest:
    """Built ONCE per payment: a retry re-sends this exact request, so transaction.id is
    identical on every attempt (Mulisa's idempotency key).

    Mulisa's transaction.id is unique across the WHOLE Mulisa instance (every bank), so we
    prefix our own reference with the bank id: two banks can never collide."""
    receiver_country = country_from_msisdn(payment.creditor.msisdn)
    return MulisaScreenRequest(
        transaction=MulisaTransaction(
            id=f"{id_prefix}-{payment.reference}",
            amount=amount_minor,
            currency=payment.currency,
            type=transaction_type,  # assumption: the bank message has no type (setting)
            channel=channel,  # setting: the core system calls over an API
            timestamp=payment.created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            reference=payment.reference,
            country_from=bank_country,
            country_to=receiver_country,
        ),
        sender=MulisaParty(
            id=payment.debtor.wallet,
            name=payment.debtor.name,
            account=payment.debtor.wallet,  # the ledger account that is debited
            institution_id=bank_institution_id,
            country=bank_country,
        ),
        receiver=MulisaParty(
            id=payment.creditor.msisdn,
            name=payment.creditor.name,
            account=payment.creditor.msisdn,  # the only receiver identifier we have
            institution_id=payment.creditor.provider,
            country=receiver_country,
        ),
    )
