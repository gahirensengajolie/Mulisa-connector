from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import CONNECTOR_KEY, MockMulisa

Payment = Callable[..., dict[str, Any]]


class TestFlagThresholdBoundary:
    """The mock flags amounts strictly ABOVE 1,000,000 minor units."""

    def test_exactly_at_the_threshold_is_cleared(
        self, client: TestClient, payment: Payment
    ) -> None:
        assert (
            client.post("/payments/screen", json=payment(amount="1000000")).json()[
                "decision"
            ]
            == "cleared"
        )

    def test_one_unit_above_is_flagged(
        self, client: TestClient, payment: Payment
    ) -> None:
        assert (
            client.post("/payments/screen", json=payment(amount="1000001")).json()[
                "decision"
            ]
            == "flagged"
        )

    def test_kes_is_converted_to_minor_units_before_screening(
        self, client: TestClient, payment: Payment
    ) -> None:
        at = client.post(
            "/payments/screen", json=payment(amount="10000.00", currency="KES")
        ).json()
        above = client.post(
            "/payments/screen", json=payment(amount="10000.01", currency="KES")
        ).json()
        assert (at["decision"], above["decision"]) == ("cleared", "flagged")


class TestBankPrefixOnTransactionId:
    def test_default_prefix_is_the_bank_institution_id(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        sent = payment()
        client.post("/payments/screen", json=sent)
        tx = mulisa.state.bodies[0]["transaction"]
        assert tx["id"] == f"greenbank-{sent['reference']}"
        assert (
            tx["reference"] == sent["reference"]
        )  # the bank's own reference is still sent as-is

    def test_prefix_and_type_and_channel_come_from_settings(
        self,
        make_settings: Callable[..., Settings],
        mulisa: MockMulisa,
        payment: Payment,
    ) -> None:
        settings = make_settings(
            transaction_id_prefix="gb2",
            mulisa_transaction_type="remittance",
            mulisa_channel="mobile",
        )
        client = TestClient(create_app(settings), headers={"X-Api-Key": CONNECTOR_KEY})
        sent = payment()
        client.post("/payments/screen", json=sent)
        tx = mulisa.state.bodies[0]["transaction"]
        assert (tx["id"], tx["type"], tx["channel"]) == (
            f"gb2-{sent['reference']}",
            "remittance",
            "mobile",
        )


class TestFutureDates:
    def test_a_payment_dated_2099_is_refused_and_never_reaches_mulisa(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        response = client.post(
            "/payments/screen", json=payment(createdAt="2099-01-01T00:00:00Z")
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["code"] == "timestamp_in_future"
        assert mulisa.state.received == []


class TestApiDocsAreOffByDefault:
    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_hidden(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 404

    def test_can_be_switched_on(self, make_settings: Callable[..., Settings]) -> None:
        client = TestClient(create_app(make_settings(enable_api_docs=True)))
        assert client.get("/docs").status_code == 200
