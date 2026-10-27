import pytest

from app.services.money import MoneyError, to_minor_units


def test_rwf_has_no_minor_units_and_kes_has_two() -> None:
    assert to_minor_units("250000", "RWF") == 250000
    assert to_minor_units("250000.00", "RWF") == 250000  # trailing zeros are harmless
    assert to_minor_units("1250.50", "KES") == 125050
    assert to_minor_units("0.10", "KES") == 10
    assert to_minor_units("5", "KES") == 500


def test_no_float_rounding_surprises() -> None:
    assert to_minor_units("19.99", "USD") == 1999  # 19.99 * 100 == 1998.9999999999998 as a float
    assert to_minor_units("1.15", "USD") == 115


@pytest.mark.parametrize(
    ("amount", "currency", "code"),
    [
        ("10.5", "RWF", "too_many_decimals"),
        ("1.234", "KES", "too_many_decimals"),
        ("0", "RWF", "amount_not_positive"),
        ("0.00", "KES", "amount_not_positive"),
        ("-5", "RWF", "invalid_amount"),
        ("1e5", "RWF", "invalid_amount"),
        ("abc", "RWF", "invalid_amount"),
        ("", "RWF", "invalid_amount"),
        (" 100", "RWF", "invalid_amount"),
        ("007", "RWF", "invalid_amount"),
        ("100", "XXX", "unsupported_currency"),
        ("99999999999999", "KES", "amount_too_large"),  # x100 passes 2**53
    ],
)
def test_rejects_bad_amounts(amount: str, currency: str, code: str) -> None:
    with pytest.raises(MoneyError) as caught:
        to_minor_units(amount, currency)
    assert caught.value.code == code
