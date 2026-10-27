from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.session import Base, make_engine, make_session_factory
from app.models.screening import ScreeningRecord
from app.repositories.screening_repository import (
    RecordAlreadyExists,
    ScreeningRepository,
)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = make_engine(f"sqlite:///{tmp_path / 'repo.db'}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as db_session:
        yield db_session


def _record(reference: str = "REF-1") -> ScreeningRecord:
    return ScreeningRecord(
        reference=reference, payload_hash="h", decision="cleared", recommended_action="release",
        matched_rules=["r1"], attempts=1,
    )  # fmt: skip


def test_add_then_get_by_reference(session: Session) -> None:
    repo = ScreeningRepository(session)
    assert repo.get_by_reference("REF-1") is None
    repo.add(_record())
    found = repo.get_by_reference("REF-1")
    assert found is not None
    assert found.decision == "cleared"
    assert found.matched_rules == ["r1"]


def test_the_database_refuses_a_second_row_for_the_same_reference(
    session: Session,
) -> None:
    repo = ScreeningRepository(session)
    repo.add(_record())
    with pytest.raises(RecordAlreadyExists):
        repo.add(_record())
    assert repo.get_by_reference("REF-1") is not None  # the session is still usable
