"""Read-only queries against the analytics schema.

The runtime API only READS precomputed rows (architecture invariant 5):
the sole spatial work at request time is point-in-polygon lookups
against pre-built geometries (cell containment, boundary check) and
ST_AsMVT tile assembly over indexed, precomputed cells — no joins,
buffers, or scoring here. Explicit SQL per code-standards.md ("drop to
explicit SQL for non-trivial PostGIS operations").
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_ACTIVE_RELEASE_SQL = text("""
    SELECT ar.release_id, dr.created_at::date AS release_date
    FROM analytics.active_release ar
    JOIN analytics.data_release dr USING (release_id)
    WHERE ar.only_one
""")

# Latest score generation within the active release — the version the
# API serves. (Admin-pinned versions are future work, §15.6.)
_ACTIVE_SCORE_VERSION_SQL = text("""
    SELECT score_version FROM analytics.location_score
    WHERE release_id = :release_id
    ORDER BY calculated_at DESC LIMIT 1
""")

_CELL_FOR_POINT_SQL = text("""
    SELECT cell_id FROM analytics.analysis_cell
    WHERE release_id = :release_id
      AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
""")

_SCORE_ROW_SQL = text("""
    SELECT total_score, confidence_score, explanation, score_version, calculated_at
    FROM analytics.location_score
    WHERE release_id = :release_id AND cell_id = :cell_id
      AND business_profile = :profile AND score_version = :score_version
""")

_DAYPART_ROWS_SQL = text("""
    WITH chosen_baseline AS (
        SELECT baseline_version
        FROM analytics.cell_pedestrian_daypart
        WHERE release_id = :release_id
          AND cell_id = :cell_id
          AND calculated_at <= :score_calculated_at
        ORDER BY calculated_at DESC
        LIMIT 1
    )
    SELECT
        d.day_type,
        d.daypart,
        d.baseline_version,
        d.pedestrian_estimate,
        d.n_sensors,
        d.nearest_sensor_m,
        d.foot_traffic_confidence
    FROM analytics.cell_pedestrian_daypart d
    JOIN chosen_baseline b USING (baseline_version)
    WHERE d.release_id = :release_id
      AND d.cell_id = :cell_id
      AND d.pedestrian_estimate IS NOT NULL
""")

_PROFILES_SQL = text("""
    SELECT DISTINCT business_profile FROM analytics.location_score
    WHERE release_id = :release_id ORDER BY business_profile
""")

_COVERAGE_SQL = text("""
    SELECT ST_AsGeoJSON(ST_Simplify(geom, 0.0001)) AS boundary,
           ST_XMin(geom) AS min_lon, ST_YMin(geom) AS min_lat,
           ST_XMax(geom) AS max_lon, ST_YMax(geom) AS max_lat
    FROM core.municipal_boundary LIMIT 1
""")

# One MVT tile of scored hexes. ST_AsMVTGeom clips/quantises each cell
# to the requested WebMercator tile envelope; the && pre-filter uses the
# GiST index via the transformed envelope back in 4326.
_TILE_SQL = text("""
    WITH bounds AS (
        SELECT ST_TileEnvelope(:z, :x, :y) AS env
    ),
    mvtgeom AS (
        SELECT
            ac.cell_id,
            ls.total_score::float  AS total_score,
            ls.confidence_score::float AS confidence_score,
            ST_AsMVTGeom(ST_Transform(ac.geom, 3857), bounds.env) AS geom
        FROM analytics.analysis_cell ac
        JOIN analytics.location_score ls USING (release_id, cell_id)
        CROSS JOIN bounds
        WHERE ac.release_id = :release_id
          AND ls.business_profile = :profile
          AND ls.score_version = :score_version
          AND ac.geom && ST_Transform(bounds.env, 4326)
    )
    SELECT ST_AsMVT(mvtgeom, 'suitability', 4096, 'geom') FROM mvtgeom
""")


def get_active_release(session: Session) -> dict[str, Any] | None:
    row = session.execute(_ACTIVE_RELEASE_SQL).mappings().one_or_none()
    return dict(row) if row else None


def get_active_score_version(session: Session, release_id: int) -> str | None:
    return session.execute(
        _ACTIVE_SCORE_VERSION_SQL, {"release_id": release_id}
    ).scalar_one_or_none()


def get_cell_for_point(session: Session, release_id: int, lat: float, lon: float) -> str | None:
    return session.execute(
        _CELL_FOR_POINT_SQL, {"release_id": release_id, "lat": lat, "lon": lon}
    ).scalar_one_or_none()


def get_score_row(
    session: Session, release_id: int, cell_id: str, profile: str, score_version: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            _SCORE_ROW_SQL,
            {
                "release_id": release_id,
                "cell_id": cell_id,
                "profile": profile,
                "score_version": score_version,
            },
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def get_daypart_rows(
    session: Session, release_id: int, cell_id: str, score_calculated_at: Any
) -> list[dict[str, Any]]:
    rows = session.execute(
        _DAYPART_ROWS_SQL,
        {
            "release_id": release_id,
            "cell_id": cell_id,
            "score_calculated_at": score_calculated_at,
        },
    ).mappings()
    return [dict(row) for row in rows]


def list_profiles(session: Session, release_id: int) -> list[str]:
    return list(session.execute(_PROFILES_SQL, {"release_id": release_id}).scalars())


def get_coverage(session: Session) -> dict[str, Any] | None:
    row = session.execute(_COVERAGE_SQL).mappings().one_or_none()
    return dict(row) if row else None


def get_suitability_tile(
    session: Session, release_id: int, profile: str, score_version: str, z: int, x: int, y: int
) -> bytes:
    result = session.execute(
        _TILE_SQL,
        {
            "release_id": release_id,
            "profile": profile,
            "score_version": score_version,
            "z": z,
            "x": x,
            "y": y,
        },
    ).scalar_one_or_none()
    return bytes(result) if result else b""
