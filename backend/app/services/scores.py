"""Assemble ScoreResponse objects from precomputed analytics rows.

All numbers come from analytics.location_score (jobs/ computed them);
this layer only reshapes the stored `explanation` jsonb into the §17.3
contract and derives the human-readable strings (top drivers, risks,
confidence reasons) deterministically from those stored values — no
recomputation, no new judgment calls at request time.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.repositories import scores as repo
from app.schemas.score import (
    BusinessProfile,
    ComponentScore,
    Confidence,
    ConfidenceBand,
    ScoreLocation,
    ScoreResponse,
)

_COMPONENT_LABELS = {
    "pedestrian_demand": "pedestrian activity",
    "worker_demand": "nearby worker population",
    "competition": "competitive pressure",
    "transport": "public-transport access",
    "development": "development pipeline",
}


class OutsideBoundaryError(Exception):
    """FR-02: the point is not inside any analysis cell."""


class NoDataError(Exception):
    """No published data release / scores available to serve."""


def _drivers_and_risks(components: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Deterministic §15.7 strings from stored component scores: top-3
    scored components are drivers (>=60), bottom scored are risks (<40).
    Components with a null score (not computed) are neither."""
    scored = [c for c in components if c.get("score") is not None and c.get("weight", 0) > 0]
    ranked = sorted(scored, key=lambda c: c["score"], reverse=True)
    drivers = [
        f"Strong {_COMPONENT_LABELS.get(c['key'], c['key'])} "
        f"({round(c['score'])}th percentile city-wide)"
        for c in ranked
        if c["score"] >= 60
    ][:3]
    risks = [
        f"Weak {_COMPONENT_LABELS.get(c['key'], c['key'])} "
        f"({round(c['score'])}th percentile city-wide)"
        for c in reversed(ranked)
        if c["score"] < 40
    ][:3]
    return drivers, risks


def _confidence_reasons(conf: dict[str, Any]) -> list[str]:
    band = conf.get("band", "insufficient")
    reasons: list[str] = []
    n, nearest = conf.get("n_sensors"), conf.get("nearest_sensor_m")
    if band == "insufficient" or n is None:
        reasons.append(
            "No pedestrian sensor within the configured catchment — "
            "foot-traffic evidence is withheld rather than guessed"
        )
    else:
        plural = "sensor" if n == 1 else "sensors"
        reasons.append(f"{n} pedestrian {plural} within the configured catchment")
        if nearest is not None:
            reasons.append(f"Nearest sensor is {round(float(nearest))} m away")
        reasons.append("Foot traffic is modelled from nearby sensors, not observed at this point")
    reasons.append("Business and employment data are from the 2024 CLUE census release")
    return reasons[:4]


def get_score(session: Session, lat: float, lon: float, profile: BusinessProfile) -> ScoreResponse:
    release = repo.get_active_release(session)
    if release is None:
        raise NoDataError("No published data release")
    release_id = release["release_id"]

    score_version = repo.get_active_score_version(session, release_id)
    if score_version is None:
        raise NoDataError("No scores published for the active release")

    cell_id = repo.get_cell_for_point(session, release_id, lat, lon)
    if cell_id is None:
        raise OutsideBoundaryError

    row = repo.get_score_row(session, release_id, cell_id, profile.value, score_version)
    if row is None:
        raise NoDataError(f"No score for cell {cell_id} / profile {profile.value}")

    explanation = row["explanation"] or {}
    raw_components: list[dict[str, Any]] = explanation.get("components", [])
    raw_conf: dict[str, Any] = explanation.get("confidence", {})
    drivers, risks = _drivers_and_risks(raw_components)

    return ScoreResponse(
        location=ScoreLocation(lat=lat, lon=lon, cell_id=cell_id),
        profile=profile,
        score=float(row["total_score"]) if row["total_score"] is not None else None,
        confidence=Confidence(
            score=round(float(row["confidence_score"])),
            band=ConfidenceBand(raw_conf.get("band", "insufficient")),
            reasons=_confidence_reasons(raw_conf),
        ),
        components=[
            ComponentScore(
                key=c["key"],
                score=round(c["score"]) if c.get("score") is not None else None,
                weight=round(c.get("weight", 0)),
                evidence=c.get("evidence") or {},
            )
            for c in raw_components
        ],
        top_drivers=drivers,
        top_risks=risks,
        score_version=str(row["score_version"]),
        data_release=f"melbourne-{release['release_date']}-r{release_id}",
        generated_at=dt.datetime.now(dt.UTC),
    )
