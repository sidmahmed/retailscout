"""Per-sensor pedestrian daypart baselines (§10.1-10.2).

For each sensor, day type, and daypart, computes robust typical hourly
pedestrian counts over the trailing window from core.pedestrian_observation
into analytics.sensor_daypart_baseline. Step 1 of pedestrian demand; the
next unit interpolates these sensor baselines to grid cells (§10.3).

observed_at is stored UTC; dayparts/day types are derived in LOCAL time
(config timezone) via `observed_at AT TIME ZONE ...`, because foot
traffic follows local wall-clock. Daypart/day-type definitions come from
the versioned config (jobs/registry/pedestrian_config.yaml, invariant 8),
resolved to plain hour→daypart / isodow→day_type mappings that SQL joins
as arrays — never hard-coded in SQL. Hours in no daypart (e.g. 10:00,
overnight) and days beyond the trailing window are excluded.

Stores median (headline robust stat), mean, p25, p75, plus n_observations
and n_days so the confidence step (§10.4) has a sample-size signal.
Idempotent upsert on (sensor_id, day_type, daypart, baseline_version).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..pedestrian_config import PedestrianConfig, load_pedestrian_config

# Latest observation instant, and the trailing-window start N months back.
_WINDOW_SQL = text("""
    SELECT max(observed_at) AS window_end_utc,
           max(observed_at) - make_interval(months => :months) AS window_start_utc,
           max(source_release_id) AS source_release_id
    FROM core.pedestrian_observation
""")

# Convert each observation to local time, map its local hour→daypart and
# isodow→day_type via the config arrays, then aggregate robust stats per
# (sensor, day_type, daypart). Observations whose local hour is in no
# daypart simply don't join hour_map and are excluded.
_BUILD_SQL = text("""
    WITH hour_map AS (
        SELECT hour, daypart FROM unnest(CAST(:hours AS int[]), CAST(:dayparts AS text[]))
            AS t(hour, daypart)
    ),
    dow_map AS (
        SELECT dow, day_type FROM unnest(CAST(:dows AS int[]), CAST(:daytypes AS text[]))
            AS t(dow, day_type)
    ),
    local_obs AS (
        SELECT o.sensor_id,
               o.pedestrian_count,
               (o.observed_at AT TIME ZONE :tz)::date AS local_date,
               EXTRACT(hour   FROM o.observed_at AT TIME ZONE :tz)::int AS local_hour,
               EXTRACT(isodow FROM o.observed_at AT TIME ZONE :tz)::int AS local_dow
        FROM core.pedestrian_observation o
        WHERE o.observed_at >= :window_start_utc
    )
    INSERT INTO analytics.sensor_daypart_baseline
        (sensor_id, day_type, daypart, baseline_version,
         median_count, mean_count, p25_count, p75_count,
         n_observations, n_days, window_start, window_end, source_release_id)
    SELECT
        lo.sensor_id, dm.day_type, hm.daypart, :baseline_version,
        percentile_cont(0.5)  WITHIN GROUP (ORDER BY lo.pedestrian_count),
        avg(lo.pedestrian_count),
        percentile_cont(0.25) WITHIN GROUP (ORDER BY lo.pedestrian_count),
        percentile_cont(0.75) WITHIN GROUP (ORDER BY lo.pedestrian_count),
        count(*),
        count(DISTINCT lo.local_date),
        :window_start, :window_end, :source_release_id
    FROM local_obs lo
    JOIN hour_map hm ON hm.hour = lo.local_hour
    JOIN dow_map dm  ON dm.dow  = lo.local_dow
    GROUP BY lo.sensor_id, dm.day_type, hm.daypart
    ON CONFLICT (sensor_id, day_type, daypart, baseline_version) DO UPDATE SET
        median_count = EXCLUDED.median_count,
        mean_count   = EXCLUDED.mean_count,
        p25_count    = EXCLUDED.p25_count,
        p75_count    = EXCLUDED.p75_count,
        n_observations = EXCLUDED.n_observations,
        n_days       = EXCLUDED.n_days,
        window_start = EXCLUDED.window_start,
        window_end   = EXCLUDED.window_end,
        source_release_id = EXCLUDED.source_release_id,
        calculated_at = now()
""")


@dataclass
class BaselineResult:
    baseline_version: str
    window_start: str
    window_end: str
    rows_written: int


def build_sensor_baselines(
    conn: Connection,
    config: PedestrianConfig | None = None,
) -> BaselineResult:
    """Compute per-sensor daypart baselines. Runs inside the caller's
    transaction — must not commit."""
    config = config or load_pedestrian_config()

    window = conn.execute(_WINDOW_SQL, {"months": config.trailing_months}).one()
    if window.window_end_utc is None:
        raise ValueError("core.pedestrian_observation is empty — load it first.")

    hour_map = config.hour_to_daypart()
    dow_map = config.isodow_to_daytype()
    window_start = window.window_start_utc.date()
    window_end = window.window_end_utc.date()

    conn.execute(
        _BUILD_SQL,
        {
            "hours": list(hour_map.keys()),
            "dayparts": list(hour_map.values()),
            "dows": list(dow_map.keys()),
            "daytypes": list(dow_map.values()),
            "tz": config.timezone,
            "window_start_utc": window.window_start_utc,
            "baseline_version": config.version,
            "window_start": window_start,
            "window_end": window_end,
            "source_release_id": window.source_release_id,
        },
    )

    rows_written = conn.execute(
        text("SELECT count(*) FROM analytics.sensor_daypart_baseline WHERE baseline_version = :v"),
        {"v": config.version},
    ).scalar_one()

    return BaselineResult(
        baseline_version=config.version,
        window_start=str(window_start),
        window_end=str(window_end),
        rows_written=rows_written,
    )
