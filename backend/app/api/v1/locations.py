"""Location scoring endpoints — served from precomputed analytics rows.

FR-02: a point outside the municipal grid is rejected with 400 and an
explicit reason, never silently scored. 503 means the pipeline has not
published a release/scores yet (a deploy-order state, not a bug).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.schemas.score import BusinessProfile, ScoreResponse
from app.services.scores import NoDataError, OutsideBoundaryError, get_score

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get(
    "/score",
    response_model=ScoreResponse,
    responses={
        400: {"description": "Point outside the supported municipal boundary (FR-02)"},
        503: {"description": "No published data release / scores yet"},
    },
)
def get_location_score(
    lat: Annotated[float, Query(ge=-90, le=90, description="WGS84 latitude")],
    lon: Annotated[float, Query(ge=-180, le=180, description="WGS84 longitude")],
    profile: Annotated[BusinessProfile, Query()],
    session: Annotated[Session, Depends(get_session)],
) -> ScoreResponse:
    """Score a candidate point: point -> containing analysis cell ->
    precomputed score row. No spatial computation beyond containment."""
    try:
        return get_score(session, lat=lat, lon=lon, profile=profile)
    except OutsideBoundaryError:
        raise HTTPException(
            status_code=400,
            detail="Point is outside the City of Melbourne analysis area (FR-02).",
        ) from None
    except NoDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
