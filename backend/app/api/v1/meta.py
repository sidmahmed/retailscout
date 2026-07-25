"""Coverage + business-profile metadata endpoints (§17.1).

/coverage tells the frontend where the product works (boundary polygon
+ bounds for the initial map view) and which release is live;
/business-profiles drives the profile selector from what is actually
scored, so the UI can never offer an unscored profile.
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.repositories import scores as repo

router = APIRouter(tags=["meta"])

# Display metadata is presentation-only and safe to keep here; WHICH
# profiles exist comes from the database, never this dict.
_PROFILE_LABELS = {
    "cafe": ("Café", "Coffee, brunch and daytime dining"),
    "retail_shop": ("Retail shop", "Fashion, convenience and specialty retail"),
    "food_truck": ("Food truck", "Mobile food with kerbside access needs"),
    "pop_up": ("Pop-up", "Short-term retail or hospitality activation"),
}


class ProfileInfo(BaseModel):
    id: str
    label: str
    description: str


class Coverage(BaseModel):
    municipality: str = "City of Melbourne"
    data_release: str
    boundary: dict[str, Any] = Field(..., description="GeoJSON MultiPolygon, simplified")
    bounds: list[float] = Field(..., description="[min_lon, min_lat, max_lon, max_lat]")


@router.get("/business-profiles", response_model=list[ProfileInfo])
def get_business_profiles(session: Annotated[Session, Depends(get_session)]) -> list[ProfileInfo]:
    release = repo.get_active_release(session)
    if release is None:
        raise HTTPException(status_code=503, detail="No published data release")
    return [
        ProfileInfo(
            id=p,
            label=_PROFILE_LABELS.get(p, (p.replace("_", " ").title(), ""))[0],
            description=_PROFILE_LABELS.get(p, ("", ""))[1],
        )
        for p in repo.list_profiles(session, release["release_id"])
    ]


@router.get("/coverage", response_model=Coverage)
def get_coverage(session: Annotated[Session, Depends(get_session)]) -> Coverage:
    release = repo.get_active_release(session)
    if release is None:
        raise HTTPException(status_code=503, detail="No published data release")
    cov = repo.get_coverage(session)
    if cov is None:
        raise HTTPException(status_code=503, detail="Municipal boundary not loaded")
    return Coverage(
        data_release=f"melbourne-{release['release_date']}-r{release['release_id']}",
        boundary=json.loads(cov["boundary"]),
        bounds=[cov["min_lon"], cov["min_lat"], cov["max_lon"], cov["max_lat"]],
    )
