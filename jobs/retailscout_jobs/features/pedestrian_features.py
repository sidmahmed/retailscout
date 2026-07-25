"""Pedestrian demand interpolation to cells (§10.3-10.4).

Step 2 of pedestrian demand: interpolates the per-sensor daypart
baselines (0010) to each grid cell of the active release, into
analytics.cell_pedestrian_daypart, with a separate foot-traffic
confidence band.

Method (§10.3): for each cell × day_type × daypart, take the sensors
that have a baseline for that slot AND a known location within
max_sensor_distance_m of the cell centroid, and compute a distance-decay
weighted mean of their baseline medians:

    weight_i = exp(-distance_i / decay_distance_m)
    estimate = Σ(weight_i · median_i) / Σ(weight_i)

Distance is GEODESIC (straight-line) — network distance (§10.3) is
deferred, so estimates are modelled/approximate and must NEVER be shown
as observed storefront footfall. sensor_quality and street_relationship
(§10.3) are 1.0 for all sensors in v1.

Confidence (§10.4) is stored SEPARATELY from the estimate: a cell with no
sensor in range is 'insufficient' and gets NO row (absent = insufficient);
otherwise the band comes from the nearest-sensor distance and count. The
raw signals (n_sensors, nearest_sensor_m) are stored so the banding can
evolve.

Idempotent upsert on (release_id, cell_id, day_type, daypart,
baseline_version). Only sensors with a location in core.pedestrian_sensor
contribute (orphan baseline sensor_ids have no geometry).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..pedestrian_config import PedestrianConfig, load_pedestrian_config

_ACTIVE_RELEASE_SQL = text("SELECT release_id FROM analytics.active_release WHERE only_one")
_LATEST_BASELINE_SQL = text(
    "SELECT baseline_version FROM analytics.sensor_daypart_baseline "
    "ORDER BY calculated_at DESC LIMIT 1"
)

_BUILD_SQL = text("""
    WITH cell_sensor AS (
        SELECT ac.cell_id, b.day_type, b.daypart, b.median_count,
               ST_Distance(ac.centroid::geography, s.geom::geography) AS dist_m
        FROM analytics.analysis_cell ac
        JOIN core.pedestrian_sensor s
            ON ST_DWithin(ac.centroid::geography, s.geom::geography, :max_dist)
        JOIN analytics.sensor_daypart_baseline b
            ON b.sensor_id = s.sensor_id AND b.baseline_version = :baseline_version
        WHERE ac.release_id = :release_id AND b.median_count IS NOT NULL
    )
    INSERT INTO analytics.cell_pedestrian_daypart
        (release_id, cell_id, day_type, daypart, baseline_version,
         pedestrian_estimate, n_sensors, nearest_sensor_m, foot_traffic_confidence)
    SELECT
        :release_id, cell_id, day_type, daypart, :baseline_version,
        round((sum(exp(-dist_m / :decay) * median_count)
               / sum(exp(-dist_m / :decay)))::numeric, 1),
        count(*),
        round(min(dist_m)::numeric),
        CASE
            WHEN min(dist_m) <= :high_near AND count(*) >= :high_n THEN 'high'
            WHEN min(dist_m) <= :med_near THEN 'medium'
            ELSE 'low'
        END
    FROM cell_sensor
    GROUP BY cell_id, day_type, daypart
    ON CONFLICT (release_id, cell_id, day_type, daypart, baseline_version) DO UPDATE SET
        pedestrian_estimate     = EXCLUDED.pedestrian_estimate,
        n_sensors               = EXCLUDED.n_sensors,
        nearest_sensor_m        = EXCLUDED.nearest_sensor_m,
        foot_traffic_confidence = EXCLUDED.foot_traffic_confidence,
        calculated_at           = now()
""")


@dataclass
class PedestrianFeatureResult:
    release_id: int
    baseline_version: str
    rows_written: int


def build_pedestrian_features(
    conn: Connection,
    config: PedestrianConfig | None = None,
    baseline_version: str | None = None,
) -> PedestrianFeatureResult:
    """Interpolate sensor baselines to the active release's cells. Runs
    inside the caller's transaction — must not commit."""
    config = config or load_pedestrian_config()

    release_id = conn.execute(_ACTIVE_RELEASE_SQL).scalar_one_or_none()
    if release_id is None:
        raise ValueError("No active grid release — run `cli build-grid` before building features.")

    if baseline_version is None:
        baseline_version = conn.execute(_LATEST_BASELINE_SQL).scalar_one_or_none()
        if baseline_version is None:
            raise ValueError("No sensor baselines — run `cli build-pedestrian-baselines` first.")

    i = config.interpolation
    conn.execute(
        _BUILD_SQL,
        {
            "release_id": release_id,
            "baseline_version": baseline_version,
            "max_dist": i.max_sensor_distance_m,
            "decay": i.decay_distance_m,
            "high_near": i.confidence_high_max_nearest_m,
            "high_n": i.confidence_high_min_sensors,
            "med_near": i.confidence_medium_max_nearest_m,
        },
    )

    rows_written = conn.execute(
        text(
            "SELECT count(*) FROM analytics.cell_pedestrian_daypart "
            "WHERE release_id = :r AND baseline_version = :bv"
        ),
        {"r": release_id, "bv": baseline_version},
    ).scalar_one()

    return PedestrianFeatureResult(
        release_id=release_id,
        baseline_version=baseline_version,
        rows_written=rows_written,
    )
