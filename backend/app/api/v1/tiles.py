"""Suitability vector tiles (§17.4): scored hex cells as Mapbox Vector
Tiles, assembled by PostGIS ST_AsMVT over precomputed geometries. The
heatmap layer loads thousands of cells without any per-cell requests.

Tiles are immutable per (release, score_version, profile), so long
Cache-Control is safe — a new release changes the data, and the frontend
can bust caches by keying the tile URL on /coverage's release id if ever
needed (MVP: 1h cache is plenty).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.repositories import scores as repo
from app.schemas.score import BusinessProfile

router = APIRouter(prefix="/tiles", tags=["tiles"])

MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"


@router.get(
    "/suitability/{profile}/{z}/{x}/{y}.mvt",
    responses={200: {"content": {MVT_CONTENT_TYPE: {}}}},
    response_class=Response,
)
def get_suitability_tile(
    profile: BusinessProfile,
    z: Annotated[int, Path(ge=0, le=22)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    release = repo.get_active_release(session)
    if release is None:
        raise HTTPException(status_code=503, detail="No published data release")
    score_version = repo.get_active_score_version(session, release["release_id"])
    if score_version is None:
        raise HTTPException(status_code=503, detail="No scores published yet")

    tile = repo.get_suitability_tile(
        session, release["release_id"], profile.value, score_version, z, x, y
    )
    return Response(
        content=tile,
        media_type=MVT_CONTENT_TYPE,
        headers={"Cache-Control": "public, max-age=3600"},
    )
