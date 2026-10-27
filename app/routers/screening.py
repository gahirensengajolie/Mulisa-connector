"""HTTP layer for screening: parse, authenticate, delegate to the service. No business logic here."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.security import require_api_key
from app.routers.deps import get_screening_service
from app.schemas.payment import PaymentIn
from app.schemas.screening import ErrorEnvelope, ScreenResponse
from app.services.screening_service import ScreeningService

router = APIRouter(prefix="/payments", tags=["screening"])


@router.post(
    "/screen",
    response_model=ScreenResponse,
    response_model_exclude_none=True,
    summary="Screen a payment with Mulisa",
    responses={
        400: {"model": ErrorEnvelope, "description": "invalid_json"},
        401: {"model": ErrorEnvelope, "description": "unauthenticated"},
        409: {"model": ErrorEnvelope, "description": "reference_conflict"},
        413: {"model": ErrorEnvelope, "description": "payload_too_large"},
        422: {"model": ErrorEnvelope, "description": "validation_failed"},
    },
)
def screen_payment(
    payment: PaymentIn,
    request: Request,
    caller: Annotated[str, Depends(require_api_key)],
    service: Annotated[ScreeningService, Depends(get_screening_service)],
) -> ScreenResponse:
    return service.screen(payment, request_id=request.state.request_id, caller=caller)
