from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Liveness probe. Deliberately does not touch the database —
    a database outage must degrade features, not report the API dead."""
    return HealthResponse(status="ok", service="retailscout-api")
