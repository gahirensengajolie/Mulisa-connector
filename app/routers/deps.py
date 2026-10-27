"""Dependencies that build the per-request object graph: session -> repository -> service."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import get_settings_dep
from app.repositories.screening_repository import ScreeningRepository
from app.services.screening_service import ScreeningService


def get_db(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_screening_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ScreeningService:
    return ScreeningService(
        ScreeningRepository(session),
        request.app.state.mulisa_client,
        request.app.state.reference_locks,
        policy=settings.screening_unavailable_policy,
        bank_country=settings.bank_country,
        bank_institution_id=settings.bank_institution_id,
        id_prefix=settings.id_prefix,
        transaction_type=settings.mulisa_transaction_type,
        channel=settings.mulisa_channel,
        max_future_skew_seconds=settings.max_future_skew_seconds,
    )
