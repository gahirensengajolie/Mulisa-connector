"""Schemas for what the bank's core system sends us (greenbank's own JSON format)."""

from typing import Annotated, Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    field_validator,
)

# strict=True: no silent coercion (a JSON number is never accepted where a string is required).
Reference = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,64}$")]
Msisdn = Annotated[
    StrictStr, StringConstraints(pattern=r"^[0-9]{8,15}$")
]  # digits only, no "+"
Currency = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{3}$")]
Name = Annotated[
    StrictStr,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
Wallet = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,32}$")]
Provider = Annotated[
    StrictStr, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,31}$")
]


class Debtor(BaseModel):
    msisdn: Msisdn
    name: Name
    wallet: Wallet


class Creditor(BaseModel):
    msisdn: Msisdn
    name: Name
    provider: Provider


class PaymentIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reference: Reference
    # A decimal STRING ("250000", "1250.50"): JSON numbers are binary floats. The amount is
    # converted to minor units in the service, because the exponent depends on the currency.
    amount: StrictStr
    currency: Currency
    debtor: Debtor
    creditor: Creditor
    # AwareDatetime refuses a time without a zone: it would be ambiguous.
    created_at: AwareDatetime = Field(alias="createdAt")

    @field_validator("created_at", mode="before")
    @classmethod
    def _timestamp_must_be_text(cls, value: Any) -> Any:
        if not isinstance(
            value, str
        ):  # pydantic would also accept a unix timestamp number
            raise ValueError("must be an ISO 8601 timestamp string with a time zone")
        return value
