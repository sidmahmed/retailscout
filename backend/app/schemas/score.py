"""The score response contract — architecture doc §17.3, verbatim shape.

This is the most important schema in the product: the generated
TypeScript client, the UI evidence panel, and saved analyses all hang
off it. Changing it is a contract change — regenerate contracts/ and
check frontend compatibility in the same unit of work.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, Field


class BusinessProfile(StrEnum):
    CAFE = "cafe"
    RETAIL_SHOP = "retail_shop"
    FOOD_TRUCK = "food_truck"
    POP_UP = "pop_up"


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class ScoreLocation(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    cell_id: str


class Confidence(BaseModel):
    """Shown separately from suitability — never blended invisibly."""

    score: int = Field(..., ge=0, le=100)
    band: ConfidenceBand
    reasons: list[str] = Field(
        ...,
        description="Human-readable evidence, e.g. 'Nearest sensor is 430 m away'",
    )


class ComponentScore(BaseModel):
    key: str = Field(..., description="e.g. pedestrian_demand, worker_demand, market_fit")
    score: int = Field(..., ge=0, le=100)
    weight: int = Field(..., ge=0, le=100)
    evidence: dict[str, float | int | str | None] = Field(
        default_factory=dict,
        description="Raw supporting values and percentiles; nulls mean 'not observed'",
    )


class ScoreResponse(BaseModel):
    location: ScoreLocation
    profile: BusinessProfile
    score: float | None = Field(
        None,
        ge=0,
        le=100,
        description="Overall suitability. Null when critical evidence is missing — "
        "a withheld score is a valid product outcome, not an error.",
    )
    confidence: Confidence
    components: list[ComponentScore]
    top_drivers: list[str] = Field(default_factory=list, max_length=3)
    top_risks: list[str] = Field(default_factory=list, max_length=3)
    score_version: str = Field(..., description="e.g. cafe-v1.0.0")
    data_release: str = Field(..., description="e.g. melbourne-2026-07-25")
    generated_at: dt.datetime
