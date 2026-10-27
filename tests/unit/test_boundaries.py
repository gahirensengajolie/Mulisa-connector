"""Boundary and edge cases: the value just inside and just outside every limit."""

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.errors import ApiError
from app.core.reference_data import get_reference_data, load_reference_data
from app.db.session import Base, make_engine, make_session_factory
from app.models import screening as _models  # noqa: F401  (registers the table)
from app.repositories.screening_repository import ScreeningRepository
from app.schemas.mulisa import MulisaScreenResponse
from app.schemas.payment import PaymentIn
from app.services.money import MoneyError, to_minor_units
from app.services.mulisa_client import Decided
from app.services.screening_service import ReferenceLocks, ScreeningService
from tests.conftest import make_payment


def valid(**overrides: Any) -> bool:
    try:
        PaymentIn.model_validate(make_payment(**overrides))
        return True
    except ValidationError:
        return False


def party(**fields: str) -> dict[str, str]:
    return {
        "msisdn": "250788000111",
        "name": "Aline Uwase",
        "wallet": "GB-0001",
        **fields,
    }


class TestFieldLengthBoundaries:
    @pytest.mark.parametrize(
        ("size", "ok"), [(1, True), (64, True), (0, False), (65, False)]
    )
    def test_reference_length(self, size: int, ok: bool) -> None:
        assert valid(reference="A" * size) is ok

    @pytest.mark.parametrize(
        ("digits", "ok"), [(8, True), (15, True), (7, False), (16, False)]
    )
    def test_msisdn_digits(self, digits: int, ok: bool) -> None:
        assert valid(debtor=party(msisdn="2" * digits)) is ok

    @pytest.mark.parametrize(("size", "ok"), [(1, True), (100, True), (101, False)])
    def test_name_length(self, size: int, ok: bool) -> None:
        assert valid(debtor=party(name="n" * size)) is ok

    @pytest.mark.parametrize(("size", "ok"), [(32, True), (33, False)])
    def test_wallet_length(self, size: int, ok: bool) -> None:
        assert valid(debtor=party(wallet="W" * size)) is ok


class TestAmountBoundaries:
    def test_smallest_amount_of_each_currency(self) -> None:
        assert to_minor_units("1", "RWF") == 1
        assert to_minor_units("0.01", "KES") == 1

    def test_largest_amount_that_fits_exactly_in_a_javascript_number(self) -> None:
        # Mulisa is JavaScript: 2**53 - 1 = 9007199254740991 is the last safe integer.
        assert to_minor_units("90071992547409.91", "KES") == 2**53 - 1

    def test_one_minor_unit_above_it_is_refused(self) -> None:
        with pytest.raises(MoneyError) as caught:
            to_minor_units("90071992547409.92", "KES")
        assert caught.value.code == "amount_too_large"

    @pytest.mark.parametrize(
        ("amount", "code"), [("9" * 15, None), ("9" * 16, "invalid_amount")]
    )
    def test_fifteen_whole_digits_pass_sixteen_fail(
        self, amount: str, code: str | None
    ) -> None:
        if code is None:
            assert to_minor_units(amount, "RWF") == int(amount)
        else:
            with pytest.raises(MoneyError) as caught:
                to_minor_units(amount, "RWF")
            assert caught.value.code == code

    @pytest.mark.parametrize(
        ("amount", "code"),
        [("1.000001", "too_many_decimals"), ("1.0000000", "invalid_amount")],
    )
    def test_decimal_places_beyond_the_pattern_or_the_currency(
        self, amount: str, code: str
    ) -> None:
        with pytest.raises(MoneyError) as caught:
            to_minor_units(amount, "USD")
        assert caught.value.code == code


class FakeScreener:
    def __init__(self) -> None:
        self.calls = 0

    def screen(self, request: Any, request_id: str) -> Decided:
        self.calls += 1
        return Decided(
            result=MulisaScreenResponse(status="cleared", screening_id="scr_1"),
            attempts=1,
        )


NOW = datetime(2026, 10, 22, 9, 0, 0, tzinfo=timezone.utc)


def make_service(skew: int, screener: FakeScreener) -> ScreeningService:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return ScreeningService(
        ScreeningRepository(make_session_factory(engine)()),
        screener,
        ReferenceLocks(),
        policy="fail_closed",
        bank_country="RW",
        bank_institution_id="greenbank",
        id_prefix="greenbank",
        transaction_type="transfer",
        channel="api",
        max_future_skew_seconds=skew,
        clock=lambda: NOW,  # a frozen clock: the boundary does not depend on the real time
    )


class TestFutureTimestampBoundary:
    """now = 2026-10-22T09:00:00Z"""

    def screen(self, service: ScreeningService, created_at: str) -> Any:
        payment = PaymentIn.model_validate(make_payment(createdAt=created_at))
        return service.screen(payment, request_id="r1", caller="test")

    def test_exactly_now_plus_skew_is_accepted(self) -> None:
        assert (
            self.screen(
                make_service(300, FakeScreener()), "2026-10-22T09:05:00Z"
            ).decision
            == "cleared"
        )

    def test_one_second_beyond_is_refused_and_mulisa_is_not_called(self) -> None:
        screener = FakeScreener()
        with pytest.raises(ApiError) as caught:
            self.screen(make_service(300, screener), "2026-10-22T09:05:01Z")
        assert caught.value.status_code == 422
        assert (
            caught.value.details
            and caught.value.details[0]["code"] == "timestamp_in_future"
        )
        assert screener.calls == 0

    def test_with_zero_skew_now_passes_and_one_second_later_fails(self) -> None:
        service = make_service(0, FakeScreener())
        assert self.screen(service, "2026-10-22T09:00:00Z").decision == "cleared"
        with pytest.raises(ApiError):
            self.screen(service, "2026-10-22T09:00:01Z")

    def test_an_old_payment_is_fine(self) -> None:
        assert (
            self.screen(
                make_service(300, FakeScreener()), "2020-01-01T00:00:00Z"
            ).decision
            == "cleared"
        )

    def test_a_future_time_written_with_an_offset_is_compared_in_utc(self) -> None:
        # 11:06+02:00 is 09:06 UTC: one minute past the 09:05 limit
        with pytest.raises(ApiError):
            self.screen(make_service(300, FakeScreener()), "2026-10-22T11:06:00+02:00")


class TestReferenceDataFile:
    def test_the_shipped_file_has_the_currencies_the_brief_mentions(self) -> None:
        currencies = get_reference_data().currencies
        assert currencies["RWF"] == 0 and currencies["KES"] == 2

    def test_a_new_currency_is_one_line_in_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "ref.json"
        path.write_text(
            '{"currencies": {"RWF": 0, "JOD": 3}, "callingCodes": {"250": "RW"}}'
        )
        assert load_reference_data(path).currencies["JOD"] == 3

    @pytest.mark.parametrize(
        "content",
        [
            "not json",
            "{}",
            '{"currencies": {"rwf": 0}, "callingCodes": {}}',  # lower case code
            '{"currencies": {"RWF": 9}, "callingCodes": {}}',  # exponent out of range
            '{"currencies": {"RWF": "0"}, "callingCodes": {}}',  # exponent not a number
            '{"currencies": {"RWF": 0}, "callingCodes": {"2500": "RW"}}',  # prefix too long
            '{"currencies": {"RWF": 0}, "callingCodes": {"250": "rwa"}}',  # bad country
        ],
    )
    def test_a_bad_file_is_refused(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / "ref.json"
        path.write_text(content)
        with pytest.raises(ValueError):
            load_reference_data(path)

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            load_reference_data(tmp_path / "nope.json")


class TestNewSettings:
    def test_defaults(self, make_settings: Callable[..., Any]) -> None:
        settings = make_settings()
        assert settings.id_prefix == "greenbank"  # falls back to the bank id
        assert settings.mulisa_transaction_type == "transfer"
        assert settings.enable_api_docs is False

    @pytest.mark.parametrize(
        ("skew", "ok"), [(0, True), (86400, True), (-1, False), (86401, False)]
    )
    def test_skew_bounds(
        self, make_settings: Callable[..., Any], skew: int, ok: bool
    ) -> None:
        if ok:
            assert (
                make_settings(max_future_skew_seconds=skew).max_future_skew_seconds
                == skew
            )
        else:
            with pytest.raises(ValidationError):
                make_settings(max_future_skew_seconds=skew)

    @pytest.mark.parametrize("prefix", ["a b", "gb/x", "gb:1", "é"])
    def test_bad_prefix_is_refused(
        self, make_settings: Callable[..., Any], prefix: str
    ) -> None:
        with pytest.raises(ValidationError):
            make_settings(transaction_id_prefix=prefix)
