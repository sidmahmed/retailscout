"""Location scoring endpoints.

Implementation order (context/progress-tracker.md): the score endpoint
is Phase 3, and depends on analytics tables that Phase 1/2 jobs
populate. Until then it returns 501 with the response contract already
published in OpenAPI so the frontend/contract work can proceed.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.schemas.score import BusinessProfile, ScoreResponse

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get(
    "/score",
    response_model=ScoreResponse,
    responses={
        400: {"description": "Point outside the supported municipal boundary (FR-02)"},
        501: {"description": "Scoring pipeline not yet implemented"},
    },
)
def get_location_score(
    lat: Annotated[float, Query(ge=-90, le=90, description="WGS84 latitude")],
    lon: Annotated[float, Query(ge=-180, le=180, description="WGS84 longitude")],
    profile: Annotated[BusinessProfile, Query()],
) -> ScoreResponse:
    """Score a candidate point for a business profile.

    Contract notes for the implementer:
    - Validate the point against core.municipal_boundary FIRST; reject
      out-of-boundary points with 400, never silently score them.
    - Map the point to its analytics.analysis_cell, then read the
      precomputed analytics.location_score row for (cell, profile,
      active score_version, active data_release).
    - No spatial computation beyond point-in-polygon + cell lookup
      happens at request time.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Scoring not implemented yet. Requires analytics.location_score "
            "populated by jobs/ (Phases 1-2). See context/progress-tracker.md."
        ),
    )
