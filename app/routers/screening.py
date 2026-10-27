# app/routers/screening.py
from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.screening import GreenbankPaymentInput, ScreeningDecisionResponse
from app.services.screening_service import ScreeningService
from app.routers.deps import get_api_key  # Assume dependencies check static API tokens

router = APIRouter(prefix="/payments", tags=["Screening"])
screening_service = ScreeningService()

@router.post("/screen", response_model=ScreeningDecisionResponse, status_code=status.HTTP_200_OK)
async def screen_payment(
    payment: GreenbankPaymentInput,
    api_key: str = Depends(get_api_key)
):
    try:
        response = await screening_service.screen_payment(payment)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while routing the screening request."
        )
