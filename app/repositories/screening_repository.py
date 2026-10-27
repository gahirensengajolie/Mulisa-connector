"""Repository: the ONLY place that talks to the database about screening records."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.screening import ScreeningRecord


class RecordAlreadyExists(Exception):
    """Another request stored a decision for this reference first."""


class ScreeningRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_reference(self, reference: str) -> ScreeningRecord | None:
        statement = select(ScreeningRecord).where(ScreeningRecord.reference == reference)
        return self._session.execute(statement).scalar_one_or_none()

    def add(self, record: ScreeningRecord) -> ScreeningRecord:
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise RecordAlreadyExists(record.reference) from exc
        return record
