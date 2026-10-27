"""Schemas for Mulisa's POST /api/screen (from the public OpenAPI contract).
Fields the contract does not require and the bank message cannot supply are simply not sent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class MulisaTransaction(BaseModel):
    id: str  # Mulisa treats this as an IDEMPOTENCY KEY
    amount: int  # integer MINOR units
    currency: str
    type: str
    channel: str
    timestamp: str  # UTC, "...Z"
    reference: str
    country_from: str
    country_to: str | None = None


class MulisaParty(BaseModel):
    id: str
    name: str
    account: str
    institution_id: str
    country: str | None = None


class MulisaScreenRequest(BaseModel):
    transaction: MulisaTransaction
    sender: MulisaParty
    receiver: MulisaParty


class MulisaRuleResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rule_id: str | None = None
    matched: bool = False


class MulisaScreenResponse(BaseModel):
    """Only what we use. `status` is a Literal: anything but cleared/flagged fails validation,
    and a response that fails validation is treated as 'unavailable', never as 'cleared'."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["cleared", "flagged"]
    screening_id: str | None = None
    risk_score: float | None = None
    rule_results: list[MulisaRuleResult] = []
