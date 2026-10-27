import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import CONNECTOR_KEY, MockMulisa

Payment = Callable[..., dict[str, Any]]


class TestHappyPaths:
    def test_cleared_payment_is_released(
        self, client: TestClient, payment: Payment
    ) -> None:
        response = client.post("/payments/screen", json=payment())
        body = response.json()
        assert response.status_code == 200
        assert body["decision"] == "cleared"
        assert body["recommended_action"] == "release"
        assert body["replayed"] is False
        assert body["attempts"] == 1
        assert body["screening_id"]
        assert response.headers["x-request-id"] == body["request_id"]

    def test_high_value_payment_is_flagged_and_held(
        self, client: TestClient, payment: Payment
    ) -> None:
        body = client.post("/payments/screen", json=payment(amount="1500000")).json()
        assert body["decision"] == "flagged"
        assert body["recommended_action"] == "hold"
        assert body["matched_rules"] == ["high-value-transfer"]

    def test_blacklisted_creditor_is_flagged(
        self, client: TestClient, payment: Payment
    ) -> None:
        creditor = {
            "msisdn": "250722000999",
            "name": "Test Blacklisted",
            "provider": "bluemobile",
        }
        assert (
            client.post("/payments/screen", json=payment(creditor=creditor)).json()[
                "decision"
            ]
            == "flagged"
        )

    def test_what_reaches_mulisa(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        creditor = {
            "msisdn": "254712000555",
            "name": "Wanjiru Test",
            "provider": "bluemobile",
        }
        sent = payment(amount="1250.50", currency="KES", creditor=creditor)
        client.post("/payments/screen", json=sent)
        body = mulisa.state.bodies[0]
        assert body["transaction"]["id"] == f"greenbank-{sent['reference']}"
        assert body["transaction"]["amount"] == 125050
        assert isinstance(body["transaction"]["amount"], int)
        assert body["transaction"]["timestamp"] == "2026-10-14T16:40:00Z"


class TestMalformedInput:
    @pytest.mark.parametrize(
        "mutation",
        [
            {"amount": 250000},
            {"amount": "10.5"},
            {"amount": "-1"},
            {"currency": "XXX"},
            {"currency": "rwf"},
            {"reference": "a b/../c"},
            {"debtor": "Eric"},
            {"createdAt": "2026-10-14T16:40:00"},
        ],
    )
    def test_422_and_mulisa_is_never_called(
        self,
        client: TestClient,
        mulisa: MockMulisa,
        payment: Payment,
        mutation: dict[str, Any],
    ) -> None:
        response = client.post("/payments/screen", json=payment(**mutation))
        error = response.json()["error"]
        assert response.status_code == 422
        assert error["code"] == "validation_failed"
        assert error["request_id"]
        assert error["details"]
        assert mulisa.state.received == []

    def test_missing_field_is_422(self, client: TestClient, payment: Payment) -> None:
        body = payment()
        del body["amount"]
        assert client.post("/payments/screen", json=body).status_code == 422

    def test_errors_never_echo_the_values(
        self, client: TestClient, payment: Payment
    ) -> None:
        debtor = {
            "msisdn": "not-a-number",
            "name": "Zed Secretname",
            "wallet": "GB 0001!",
        }
        text = client.post("/payments/screen", json=payment(debtor=debtor)).text
        assert "Zed Secretname" not in text
        assert "not-a-number" not in text

    def test_invalid_json_is_400_without_a_stack_trace(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/payments/screen",
            content="{not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_json"
        assert "Traceback" not in response.text

    def test_oversized_body_is_413(self, client: TestClient) -> None:
        response = client.post("/payments/screen", json={"pad": "x" * 20_000})
        assert response.status_code == 413


class TestAuthentication:
    def test_missing_wrong_and_empty_keys_are_401(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        for headers in (
            {},
            {"X-Api-Key": "wrong-key-wrong-key-123"},
            {"X-Api-Key": ""},
        ):
            fresh = TestClient(client.app)  # no default headers
            response = fresh.post("/payments/screen", json=payment(), headers=headers)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "unauthenticated"
        assert mulisa.state.received == []

    def test_bearer_token_works_too(self, client: TestClient, payment: Payment) -> None:
        fresh = TestClient(client.app)
        response = fresh.post(
            "/payments/screen",
            json=payment(),
            headers={"Authorization": f"Bearer {CONNECTOR_KEY}"},
        )
        assert response.status_code == 200

    def test_health_is_open_and_unknown_paths_are_json_errors(
        self, client: TestClient
    ) -> None:
        fresh = TestClient(client.app)
        assert fresh.get("/health").json() == {"status": "ok"}
        missing = fresh.get("/nope")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        assert fresh.get("/payments/screen").status_code == 405


class TestDuplicates:
    def test_same_payment_twice_calls_mulisa_once(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        sent = payment()
        first = client.post("/payments/screen", json=sent).json()
        second = client.post("/payments/screen", json=sent).json()
        assert len(mulisa.state.received) == 1
        assert (first["replayed"], second["replayed"]) == (False, True)
        assert second["decision"] == first["decision"]
        assert second["screening_id"] == first["screening_id"]

    def test_differently_written_amount_is_the_same_payment(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        sent = payment()
        client.post("/payments/screen", json=sent)
        again = client.post("/payments/screen", json={**sent, "amount": "250000.00"})
        assert again.status_code == 200
        assert again.json()["replayed"] is True
        assert len(mulisa.state.received) == 1

    def test_same_reference_different_payment_is_409(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        sent = payment()
        client.post("/payments/screen", json=sent)
        response = client.post("/payments/screen", json={**sent, "amount": "999"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "reference_conflict"
        assert len(mulisa.state.received) == 1

    def test_four_simultaneous_duplicates_call_mulisa_once(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        sent = payment()
        mulisa.set_mode(
            "slow", 0.1
        )  # keep the first one running while the others arrive
        with ThreadPoolExecutor(4) as pool:
            results = list(
                pool.map(lambda _: client.post("/payments/screen", json=sent), range(4))
            )
        assert len(mulisa.state.received) == 1
        assert all(r.json()["decision"] == "cleared" for r in results)
        assert sum(1 for r in results if not r.json()["replayed"]) == 1

    def test_a_decision_survives_a_restart(
        self,
        make_settings: Callable[..., Settings],
        mulisa: MockMulisa,
        payment: Payment,
    ) -> None:
        sent = payment()
        settings = make_settings()
        headers = {"X-Api-Key": CONNECTOR_KEY}
        TestClient(create_app(settings), headers=headers).post(
            "/payments/screen", json=sent
        )
        restarted = TestClient(
            create_app(settings), headers=headers
        )  # same database file
        again = restarted.post("/payments/screen", json=sent).json()
        assert again["replayed"] is True
        assert len(mulisa.state.received) == 1


class TestTimeoutsAndRetries:
    def test_first_call_times_out_and_the_single_retry_reuses_the_transaction_id(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        sent = payment()
        mulisa.set_mode("flaky_once", 0.8)
        body = client.post("/payments/screen", json=sent).json()
        assert body["decision"] == "cleared"
        assert body["attempts"] == 2
        assert (
            mulisa.state.received == [f"greenbank-{sent['reference']}"] * 2
        )  # identical id both times
        assert mulisa.state.processed == 1  # Mulisa screened it once, not twice

    def test_persistent_timeout_is_one_retry_bounded_in_time_then_policy(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        mulisa.set_mode("slow", 0.8)
        started = time.monotonic()
        response = client.post("/payments/screen", json=payment())
        elapsed = time.monotonic() - started
        body = response.json()
        assert response.status_code == 200
        assert (body["decision"], body["reason"], body["attempts"]) == (
            "unavailable",
            "timeout",
            2,
        )
        assert len(mulisa.state.received) == 2  # never a third call
        assert elapsed < 1.5  # about 2 x 0.3 s + delay, not 2 x 0.8 s

    def test_a_retryable_503_is_retried_once_then_succeeds(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        mulisa.set_mode("error_503_once")
        body = client.post("/payments/screen", json=payment()).json()
        assert (body["decision"], body["attempts"]) == ("cleared", 2)

    def test_a_persistent_503_stops_after_one_retry(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        mulisa.set_mode("error_503")
        body = client.post("/payments/screen", json=payment()).json()
        assert (body["decision"], body["reason"]) == ("unavailable", "upstream_error")
        assert len(mulisa.state.received) == 2

    @pytest.mark.parametrize(
        ("mode", "reason"),
        [("error_500", "upstream_error"), ("error_400", "upstream_rejected")],
    )
    def test_non_retryable_errors_are_not_retried(
        self,
        client: TestClient,
        mulisa: MockMulisa,
        payment: Payment,
        mode: str,
        reason: str,
    ) -> None:
        mulisa.set_mode(mode)
        body = client.post("/payments/screen", json=payment()).json()
        assert (body["decision"], body["reason"]) == ("unavailable", reason)
        assert len(mulisa.state.received) == 1

    @pytest.mark.parametrize("mode", ["bad_status", "garbage"])
    def test_an_answer_we_do_not_understand_is_never_cleared(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment, mode: str
    ) -> None:
        mulisa.set_mode(mode)
        body = client.post("/payments/screen", json=payment()).json()
        assert body["decision"] == "unavailable"
        assert body["reason"] == "upstream_bad_response"

    def test_unavailable_is_not_remembered(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        sent = payment()
        mulisa.set_mode("error_500")
        assert (
            client.post("/payments/screen", json=sent).json()["decision"]
            == "unavailable"
        )
        mulisa.set_mode("normal")
        again = client.post("/payments/screen", json=sent).json()
        assert (again["decision"], again["replayed"]) == ("cleared", False)

    def test_mulisa_completely_down_is_unavailable_and_not_retried(
        self, client: TestClient, mulisa: MockMulisa, payment: Payment
    ) -> None:
        mulisa.stop()
        response = client.post("/payments/screen", json=payment())
        body = response.json()
        assert response.status_code == 200
        assert (body["decision"], body["reason"], body["attempts"]) == (
            "unavailable",
            "upstream_unreachable",
            1,
        )


class TestPolicy:
    @pytest.mark.parametrize(
        ("policy", "action"), [("fail_closed", "hold"), ("fail_open", "release")]
    )
    def test_policy_decides_what_unavailable_means(
        self,
        make_settings: Callable[..., Settings],
        mulisa: MockMulisa,
        payment: Payment,
        policy: str,
        action: str,
    ) -> None:
        mulisa.set_mode("error_500")
        app_client = TestClient(
            create_app(make_settings(screening_unavailable_policy=policy)),
            headers={"X-Api-Key": CONNECTOR_KEY},
        )
        body = app_client.post("/payments/screen", json=payment()).json()
        assert body["decision"] == "unavailable"
        assert body["policy_applied"] == policy
        assert body["recommended_action"] == action


class TestLogHygiene:
    def test_no_personal_data_or_keys_in_any_log_line(
        self,
        client: TestClient,
        mulisa: MockMulisa,
        payment: Payment,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG)
        client.post("/payments/screen", json=payment())  # success
        client.post("/payments/screen", json=payment(amount=5))  # validation failure
        TestClient(client.app).post(  # authentication failure
            "/payments/screen",
            json=payment(),
            headers={"X-Api-Key": "wrong-key-wrong-key-123"},
        )
        duplicate = payment()
        client.post("/payments/screen", json=duplicate)
        client.post("/payments/screen", json=duplicate)  # duplicate
        mulisa.set_mode("error_500")
        client.post("/payments/screen", json=payment())  # upstream failure
        text = "\n".join(record.getMessage() for record in caplog.records)
        assert len(caplog.records) > 5
        for secret in (
            "250788000111", "250722000333", "Aline", "Uwase", "Eric", "Mugisha",
            "GB-0001", CONNECTOR_KEY, "wrong-key-wrong-key-123", "test-mulisa-key",
        ):  # fmt: skip
            assert secret not in text, f"log contains {secret}"
