# app/services/mapping.py
from app.schemas.screening import GreenbankPaymentInput

def map_to_mulisa_payload(payment: GreenbankPaymentInput) -> dict:
    """
    Maps Greenbank's format into Mulisa's OpenAPI structure.
    Converts amount into minor units (RWF=no decimals, KES=2 decimals).
    """
    raw_amount = float(payment.amount)
    currency = payment.currency.upper()
    
    if currency == "RWF":
        minor_amount = int(raw_amount)
    elif currency == "KES":
        minor_amount = int(raw_amount * 100)
    else:
        minor_amount = int(raw_amount) 

    return {
        "transaction": {
            "id": payment.reference,
            "amount": minor_amount,
            "currency": currency,
            "timestamp": payment.createdAt.isoformat()
        },
        "sender": {
            "name": payment.debtor.name,
            "identifier": payment.debtor.msisdn,
            "account": payment.debtor.wallet
        },
        "receiver": {
            "name": payment.creditor.name,
            "identifier": payment.creditor.msisdn,
            "institution": payment.creditor.provider
        }
    }
