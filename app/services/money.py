"""Money handling: decimal STRINGS in, integer minor units out. Amounts are never floats."""

import re
from decimal import Decimal
CURRENCY_EXPONENT = {
    "RWF": 0, "UGX": 0, "BIF": 0, "XOF": 0, "XAF": 0,
    "KES": 2, "TZS": 2, "ETB": 2, "CDF": 2, "ZAR": 2, "USD": 2, "EUR": 2, "GBP": 2,
}  

MAX_MINOR_UNITS = 2**53 - 1
DECIMAL_RE = re.compile(r"^(0|[1-9][0-9]{0,14})(\.[0-9]{1,6})?$")


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
    if not DECIMAL_RE.match(amount):
        raise MoneyError(
            "amount", "invalid_amount", 'amount must be a plain decimal string such as "250000" or "1250.50"'
        )
    scaled = Decimal(amount).scaleb(exponent)
    if scaled != scaled.to_integral_value():
        raise MoneyError(
            "amount", "too_many_decimals", f"{currency} allows at most {exponent} decimal places"
        )
    minor = int(scaled)
    if minor <= 0:
        raise MoneyError("amount", "amount_not_positive", "amount must be greater than zero")
    if minor > MAX_MINOR_UNITS:
        raise MoneyError("amount", "amount_too_large", "amount is too large")
    return minor
