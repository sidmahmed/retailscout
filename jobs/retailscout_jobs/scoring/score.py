"""Compute analytics.location_score for the active release (§15).

Deterministic, versioned, profile-weighted scoring (ADR-003 — no ML).
For every grid cell and each business profile:

1. Gather one raw metric per component from the feature tables:
   - foot_traffic: mean weekday pedestrian estimate (cell_pedestrian_daypart)
   - worker_demand: jobs_800m (location_feature)
   - competition:   café-competitor saturation = cafe_restaurant_400m + takeaway_food_400m
   - transport:     transit stops = tram_400 + bus_400 + train_800
   - development:   dev_pipeline_people_800m (status/decay-weighted pipeline)
2. Normalise each to a robust 0-100 city percentile (§15.2, percent_rank
   over cells that HAVE the metric). competition is inverted
   (100 − saturation percentile: less competition scores higher — a v1
   simplification; the §11.2 cluster-strength nuance is deferred).
3. Weight per profile (jobs/registry/score_profiles.yaml) and take the
   weighted mean over the PRESENT components only — a missing component
   (foot_traffic where pedestrian data is insufficient; development if
   its feature was not built) is reweighted out of numerator AND
   denominator (§15.5), never treated as 0.
4. Confidence is scored SEPARATELY (§15.3) from the cell's foot-traffic
   confidence band, and every component + confidence travels with the
   total in an API-shaped `explanation` jsonb (§17.3, invariant 6).

Percentiles are within-city relative — a score of 80 means "busier /
better than ~80% of the city's cells", not an absolute. Idempotent
upsert on (release_id, cell_id, business_profile, score_version).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..score_config import COMPONENTS, ScoreConfig, load_score_config

_ACTIVE_RELEASE_SQL = text("SELECT release_id FROM analytics.active_release WHERE only_one")
_LATEST_BASELINE_SQL = text(
    "SELECT baseline_version FROM analytics.sensor_daypart_baseline "
    "ORDER BY calculated_at DESC LIMIT 1"
)

_BUILD_SQL = text("""
    WITH ped AS (
        SELECT cell_id,
               avg(pedestrian_estimate) FILTER (WHERE day_type = 'weekday') AS ped_weekday_avg,
               (array_agg(foot_traffic_confidence)
                    FILTER (WHERE day_type = 'weekday' AND daypart = 'lunch'))[1] AS conf_band,
               (array_agg(n_sensors)
                    FILTER (WHERE day_type = 'weekday' AND daypart = 'lunch'))[1] AS n_sensors,
               (array_agg(nearest_sensor_m)
                    FILTER (WHERE day_type = 'weekday' AND daypart = 'lunch'))[1] AS nearest_m
        FROM analytics.cell_pedestrian_daypart
        WHERE release_id = :release_id AND baseline_version = :baseline_version
        GROUP BY cell_id
    ),
    base AS (
        SELECT lf.cell_id,
               round(p.ped_weekday_avg, 0) AS ped_weekday_avg,
               coalesce(p.conf_band, 'insufficient') AS conf_band,
               p.n_sensors, p.nearest_m,
               lf.jobs_800m,
               coalesce(lf.cafe_restaurant_400m, 0) + coalesce(lf.takeaway_food_400m, 0)
                   AS saturation,
               coalesce(lf.tram_stops_400m, 0) + coalesce(lf.bus_stops_400m, 0)
                   + coalesce(lf.train_stops_800m, 0) AS transit,
               lf.dev_pipeline_people_800m AS dev_people,
               lf.dev_projects_800m AS dev_projects
        FROM analytics.location_feature lf
        LEFT JOIN ped p USING (cell_id)
        WHERE lf.release_id = :release_id AND lf.feature_version = :feature_version
    ),
    foot_pct AS (  -- percentile only among cells that have a pedestrian estimate
        SELECT cell_id, 100.0 * percent_rank() OVER (ORDER BY ped_weekday_avg) AS score
        FROM base WHERE ped_weekday_avg IS NOT NULL
    ),
    dev_pct AS (  -- percentile only among cells whose dev feature was built
        SELECT cell_id, 100.0 * percent_rank() OVER (ORDER BY dev_people) AS score
        FROM base WHERE dev_people IS NOT NULL
    ),
    comp AS (
        SELECT b.*,
               round(fp.score::numeric, 1) AS foot_traffic,
               round((100.0 * percent_rank() OVER (ORDER BY b.jobs_800m))::numeric, 1)
                   AS worker_demand,
               round((100.0 - 100.0 * percent_rank() OVER (ORDER BY b.saturation))::numeric, 1)
                   AS competition,
               round((100.0 * percent_rank() OVER (ORDER BY b.transit))::numeric, 1)
                   AS transport,
               round(dp.score::numeric, 1) AS development
        FROM base b
        LEFT JOIN foot_pct fp USING (cell_id)
        LEFT JOIN dev_pct dp USING (cell_id)
    ),
    profiles AS (
        SELECT * FROM unnest(
            CAST(:profiles AS text[]), CAST(:w_foot AS numeric[]), CAST(:w_worker AS numeric[]),
            CAST(:w_comp AS numeric[]), CAST(:w_transport AS numeric[]), CAST(:w_dev AS numeric[])
        ) AS t(business_profile, w_foot, w_worker, w_comp, w_transport, w_dev)
    ),
    scored AS (
        SELECT
            c.*, pr.business_profile,
            pr.w_foot, pr.w_worker, pr.w_comp, pr.w_transport, pr.w_dev,
            CASE c.conf_band
                WHEN 'high' THEN :c_high WHEN 'medium' THEN :c_med
                WHEN 'low' THEN :c_low ELSE :c_insuff END AS confidence_score,
            -- weighted mean over PRESENT components (foot_traffic absent where
            -- no pedestrian estimate; development absent if its feature was
            -- not built)
            round((
                coalesce(pr.w_foot * c.foot_traffic, 0)
                + pr.w_worker * c.worker_demand
                + pr.w_comp * c.competition
                + pr.w_transport * c.transport
                + coalesce(pr.w_dev * c.development, 0)
            ) / nullif(
                (CASE WHEN c.foot_traffic IS NOT NULL THEN pr.w_foot ELSE 0 END)
                + pr.w_worker + pr.w_comp + pr.w_transport
                + (CASE WHEN c.development IS NOT NULL THEN pr.w_dev ELSE 0 END)
            , 0), 1) AS total_score
        FROM comp c CROSS JOIN profiles pr
    )
    INSERT INTO analytics.location_score
        (release_id, cell_id, business_profile, score_version, feature_version,
         total_score, foot_traffic_score, worker_demand_score, competition_score,
         transport_score, development_score, confidence_score, explanation)
    SELECT
        :release_id, s.cell_id, s.business_profile, :score_version, :feature_version,
        s.total_score, s.foot_traffic, s.worker_demand, s.competition, s.transport,
        s.development, s.confidence_score,
        jsonb_build_object(
            'components', jsonb_build_array(
                jsonb_build_object('key', 'pedestrian_demand', 'score', s.foot_traffic,
                    'weight', s.w_foot,
                    'evidence', jsonb_build_object('weekday_avg_estimate', s.ped_weekday_avg)),
                jsonb_build_object('key', 'worker_demand', 'score', s.worker_demand,
                    'weight', s.w_worker,
                    'evidence', jsonb_build_object('jobs_800m', s.jobs_800m)),
                jsonb_build_object('key', 'competition', 'score', s.competition,
                    'weight', s.w_comp,
                    'evidence', jsonb_build_object('cafe_competitors_400m', s.saturation)),
                jsonb_build_object('key', 'transport', 'score', s.transport,
                    'weight', s.w_transport,
                    'evidence', jsonb_build_object('transit_stops', s.transit)),
                jsonb_build_object('key', 'development', 'score', s.development,
                    'weight', s.w_dev,
                    'evidence', jsonb_build_object(
                        'pipeline_people_800m', s.dev_people,
                        'pipeline_projects_800m', s.dev_projects))
            ),
            'confidence', jsonb_build_object(
                'score', s.confidence_score, 'band', s.conf_band,
                'n_sensors', s.n_sensors, 'nearest_sensor_m', s.nearest_m)
        )
    FROM scored s
    ON CONFLICT (release_id, cell_id, business_profile, score_version) DO UPDATE SET
        feature_version     = EXCLUDED.feature_version,
        total_score         = EXCLUDED.total_score,
        foot_traffic_score  = EXCLUDED.foot_traffic_score,
        worker_demand_score = EXCLUDED.worker_demand_score,
        competition_score   = EXCLUDED.competition_score,
        transport_score     = EXCLUDED.transport_score,
        development_score    = EXCLUDED.development_score,
        confidence_score    = EXCLUDED.confidence_score,
        explanation         = EXCLUDED.explanation,
        calculated_at       = now()
""")


@dataclass
class ScoreResult:
    release_id: int
    score_version: str
    feature_version: str
    baseline_version: str
    rows_written: int


def build_scores(
    conn: Connection,
    config: ScoreConfig | None = None,
    feature_version: str = "v1",
    baseline_version: str | None = None,
) -> ScoreResult:
    """Compute location_score for the active release. Runs inside the
    caller's transaction — must not commit."""
    config = config or load_score_config()

    release_id = conn.execute(_ACTIVE_RELEASE_SQL).scalar_one_or_none()
    if release_id is None:
        raise ValueError("No active grid release — run `cli build-grid` first.")

    if baseline_version is None:
        baseline_version = conn.execute(_LATEST_BASELINE_SQL).scalar_one_or_none()
        if baseline_version is None:
            # Scoring can still run (foot_traffic just stays absent), but that
            # is almost certainly a mistake — surface it.
            raise ValueError(
                "No pedestrian baselines/features — run build-pedestrian-baselines "
                "and build-pedestrian-features first."
            )

    names = list(config.profiles)
    weights = {c: [config.profiles[n].as_dict()[c] for n in names] for c in COMPONENTS}

    conf = config.confidence_scores
    conn.execute(
        _BUILD_SQL,
        {
            "release_id": release_id,
            "feature_version": feature_version,
            "baseline_version": baseline_version,
            "score_version": config.version,
            "profiles": names,
            "w_foot": weights["foot_traffic"],
            "w_worker": weights["worker_demand"],
            "w_comp": weights["competition"],
            "w_transport": weights["transport"],
            "w_dev": weights["development"],
            "c_high": conf["high"],
            "c_med": conf["medium"],
            "c_low": conf["low"],
            "c_insuff": conf["insufficient"],
        },
    )

    rows_written = conn.execute(
        text(
            "SELECT count(*) FROM analytics.location_score "
            "WHERE release_id = :r AND score_version = :sv"
        ),
        {"r": release_id, "sv": config.version},
    ).scalar_one()

    return ScoreResult(
        release_id=release_id,
        score_version=config.version,
        feature_version=feature_version,
        baseline_version=baseline_version,
        rows_written=rows_written,
    )
