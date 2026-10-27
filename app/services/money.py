"""Money handling: decimal STRINGS in, integer minor units out. Amounts are never floats."""

import re
from decimal import Decimal

from app.core.reference_data import get_reference_data

# ISO 4217 minor-unit exponents, loaded from config/reference-data.json. An unknown currency is
# rejected, never guessed: guessing the exponent would make a payment 100x too big or too small.
CURRENCY_EXPONENT = get_reference_data().currencies

# Mulisa is a JavaScript service: integers above 2**53 - 1 lose precision.
MAX_MINOR_UNITS = 2**53 - 1

# No sign, no exponent notation, no whitespace, no leading zeros.
_DECIMAL_RE = re.compile(r"^(0|[1-9][0-9]{0,14})(\.[0-9]{1,6})?$")


class MoneyError(ValueError):
    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message


def to_minor_units(amount: str, currency: str) -> int:
    """Convert a decimal string to integer minor units, or raise MoneyError."""
    exponent = CURRENCY_EXPONENT.get(currency)
    if exponent is None:
        raise MoneyError("currency", "unsupported_currency", "currency is not supported")
    if not _DECIMAL_RE.match(amount):
        raise MoneyError(
            "amount",
            "invalid_amount",
            'amount must be a plain decimal string such as "250000" or "1250.50"',
        )
    scaled = Decimal(amount).scaleb(exponent)
    if scaled != scaled.to_integral_value():
        # e.g. "10.5" in RWF. Refuse instead of rounding someone's money.
        raise MoneyError(
            "amount",
            "too_many_decimals",
            f"{currency} allows at most {exponent} decimal places",
        )
    minor = int(scaled)
    if minor <= 0:
        raise MoneyError("amount", "amount_not_positive", "amount must be greater than zero")
    if minor > MAX_MINOR_UNITS:
        raise MoneyError("amount", "amount_too_large", "amount is too large")
    return minor
