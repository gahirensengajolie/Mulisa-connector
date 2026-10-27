from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Unauthenticated liveness check. Reveals nothing."""
    return {"status": "ok"}
