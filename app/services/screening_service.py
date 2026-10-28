"""The screening flow.

validate -> duplicate check -> map -> call Mulisa -> normalise -> apply policy.

The service knows nothing about HTTP or FastAPI. It receives a repository and a client."""

import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.core.errors import ApiError, ReferenceConflict
from app.core.log import log_event
from app.models.screening import ScreeningRecord
from app.repositories.screening_repository import (
    RecordAlreadyExists,
    ScreeningRepository,
)
from app.schemas.mulisa import MulisaScreenRequest
from app.schemas.payment import PaymentIn
from app.schemas.screening import ScreenResponse
from app.services.mapping import build_mulisa_request
from app.services.money import MoneyError, to_minor_units
from app.services.mulisa_client import Decided, Unavailable


class Screener(Protocol):
    def screen(self, request: MulisaScreenRequest, request_id: str) -> Decided | Unavailable: ...


class ReferenceLocks:
    """One lock per payment reference, shared by all requests in this process.
    A concurrent duplicate waits here, then finds the stored decision instead of calling Mulisa.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}

    @contextmanager
    def hold(self, reference: str) -> Iterator[None]:
        with self._guard:
            lock, users = self._locks.get(reference, (threading.Lock(), 0))
            self._locks[reference] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                lock, users = self._locks[reference]
                if users <= 1:
                    del self._locks[reference]
                else:
                    self._locks[reference] = (lock, users - 1)


def payload_hash(payment: PaymentIn, amount_minor: int) -> str:
    """Hash of the canonical payment, so "250000" and "250000.00" count as the same payment."""
    canonical = json.dumps(
        [
            payment.reference, amount_minor, payment.currency,
            payment.debtor.msisdn, payment.debtor.name, payment.debtor.wallet,
            payment.creditor.msisdn, payment.creditor.name, payment.creditor.provider,
            payment.created_at.timestamp(),
        ],
        separators=(",", ":"),
    )  # fmt: skip
    return hashlib.sha256(canonical.encode()).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScreeningService:
    def __init__(
        self,
        repository: ScreeningRepository,
        client: Screener,
        locks: ReferenceLocks,
        *,
        policy: str,
        bank_country: str,
        bank_institution_id: str,
        id_prefix: str,
        transaction_type: str,
        channel: str,
        max_future_skew_seconds: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repo = repository
        self._client = client
        self._locks = locks
        self._policy = policy
        self._bank_country = bank_country
        self._bank_institution_id = bank_institution_id
        self._id_prefix = id_prefix
        self._transaction_type = transaction_type
        self._channel = channel
        self._max_future_skew = timedelta(seconds=max_future_skew_seconds)
        self._clock = clock

    def screen(self, payment: PaymentIn, *, request_id: str, caller: str) -> ScreenResponse:
        try:
            amount_minor = to_minor_units(payment.amount, payment.currency)
        except MoneyError as exc:
            raise ApiError(
                422,
                "validation_failed",
                "the payment message is invalid",
                [{"field": exc.field, "code": exc.code, "message": exc.message}],
            ) from exc
        if payment.created_at > self._clock() + self._max_future_skew:
            raise ApiError(
                422,
                "validation_failed",
                "the payment message is invalid",
                [
                    {
                        "field": "createdAt",
                        "code": "timestamp_in_future",
                        "message": "createdAt is too far in the future",
                    }
                ],
            )
        digest = payload_hash(payment, amount_minor)

        with self._locks.hold(payment.reference):
            # 1. Already screened: answer from the database. Mulisa is NOT called.
            existing = self._repo.get_by_reference(payment.reference)
            if existing is not None:
                return self._replay(existing, digest, request_id)

            # 2. New payment: map once, call Mulisa.
            request = build_mulisa_request(
                payment,
                amount_minor,
                bank_country=self._bank_country,
                bank_institution_id=self._bank_institution_id,
                id_prefix=self._id_prefix,
                transaction_type=self._transaction_type,
                channel=self._channel,
            )
            outcome = self._client.screen(request, request_id)

            if isinstance(outcome, Unavailable):
                # Nothing was screened, so nothing is stored: a re-submission gets a fresh attempt.
                log_event(
                    "screen_unavailable", request_id=request_id, caller=caller,
                    reference=payment.reference, reason=outcome.reason,
                    policy=self._policy, attempts=outcome.attempts,
                )  # fmt: skip
                return ScreenResponse(
                    reference=payment.reference,
                    decision="unavailable",
                    recommended_action=("release" if self._policy == "fail_open" else "hold"),
                    policy_applied=self._policy,  # type: ignore[arg-type]
                    reason=outcome.reason,  # type: ignore[arg-type]
                    replayed=False,
                    attempts=outcome.attempts,
                    request_id=request_id,
                )

            result = outcome.result
            record = ScreeningRecord(
                reference=payment.reference,
                payload_hash=digest,
                decision=result.status,
                # flagged is advisory: the bank decides, we advise "hold"
                recommended_action="release" if result.status == "cleared" else "hold",
                screening_id=result.screening_id,
                risk_score=result.risk_score,
                matched_rules=[r.rule_id for r in result.rule_results if r.matched and r.rule_id],
                attempts=outcome.attempts,
            )
            try:
                self._repo.add(record)
            except RecordAlreadyExists:  # another PROCESS won the race: the DB unique key caught it
                existing = self._repo.get_by_reference(payment.reference)
                if existing is None:  # pragma: no cover
                    raise
                return self._replay(existing, digest, request_id)

            log_event(
                "screen_decided", request_id=request_id, caller=caller,
                reference=payment.reference, decision=record.decision, attempts=outcome.attempts,
            )  # fmt: skip
            return self._to_response(record, replayed=False, request_id=request_id)

    def _replay(self, record: ScreeningRecord, digest: str, request_id: str) -> ScreenResponse:
        if record.payload_hash != digest:
            raise ReferenceConflict
        log_event(
            "screen_replayed", request_id=request_id,
            reference=record.reference, decision=record.decision,
        )  # fmt: skip
        return self._to_response(record, replayed=True, request_id=request_id)

    @staticmethod
    def _to_response(record: ScreeningRecord, *, replayed: bool, request_id: str) -> ScreenResponse:
        return ScreenResponse(
            reference=record.reference,
            decision=record.decision,  # type: ignore[arg-type]
            recommended_action=record.recommended_action,  # type: ignore[arg-type]
            screening_id=record.screening_id,
            risk_score=record.risk_score,
            matched_rules=list(record.matched_rules or []),
            replayed=replayed,
            attempts=record.attempts,
            request_id=request_id,
        )
