# app/schemas/screening.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

# 1. Incoming Greenbank Format
class DebtorSchema(BaseModel):
    msisdn: str
    name: str
    wallet: str

class CreditorSchema(BaseModel):
    msisdn: str
    name: str
    provider: str

class GreenbankPaymentInput(BaseModel):
    reference: str
    amount: str  # Kept as string to prevent float precision loss
    currency: str
    debtor: DebtorSchema
    creditor: CreditorSchema
    createdAt: datetime

# 2. Normalized Output Response
class ScreeningDecisionResponse(BaseModel):
    reference: str
    decision: str  # "cleared", "flagged", or "unavailable"
    policy_applied: Optional[str] = None
