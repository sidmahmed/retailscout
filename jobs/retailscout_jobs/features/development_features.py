"""Development-pipeline features: weighted nearby pipeline per cell (§13).

Fills dev_pipeline_people_800m / dev_projects_800m on
analytics.location_feature for the active grid release. Each project in
the 800 m catchment of a cell centroid contributes

    people_equivalents × status_probability × linear distance decay

with every factor from jobs/registry/development_config.yaml (§13: "the
factors must be configuration, not hidden constants") — resolved in
Python and joined into SQL as unnest arrays (invariant 8), so the SQL
contains no policy numbers.

Real-data decisions (profiled against the full 2026-07-25 snapshot):
- COMPLETED projects (1,121 of 1,438, completions back to 2009) only
  count when year_completed >= completed_since_year: older completions
  are already in the observed CLUE stock (their workers in
  employment_block, their shops in business_establishment) — counting
  them as pipeline would double-count the present as the future.
- Every row has geometry and the dataset has no suppression, so a cell
  with nothing in range gets a real 0, never NULL (unlike jobs_800m —
  see migration 0013). All 317 non-COMPLETED rows have NULL
  year_completed, never a year; the recency test is COMPLETED-only.
- An unknown status (not in config) fails the build loudly: silently
  dropping it would quietly zero real pipeline.

Upserts only the dev_* columns for (release_id, cell_id,
feature_version), composing with the other feature-family loaders.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..development_config import DevelopmentConfig, load_development_config

DEFAULT_FEATURE_VERSION = "v1"

_ACTIVE_RELEASE_SQL = text("SELECT release_id FROM analytics.active_release WHERE only_one")
_LATEST_SOURCE_RELEASE_SQL = text("SELECT max(source_release_id) FROM core.development_project")
_STATUSES_SQL = text(
    "SELECT DISTINCT status FROM core.development_project "
    "WHERE source_release_id = :source_release_id AND status IS NOT NULL"
)

# Per project: people equivalents from the config's (field, coefficient)
# pairs over raw_attributes, times the status probability. Per cell: sum
# with linear decay over the 800 m catchment (GiST bbox pre-filter, then
# exact geography distance — same idiom as business_features). LEFT JOIN
# keeps every cell: no pipeline in range is an observed 0, never NULL.
_BUILD_SQL = text("""
    WITH pe AS (
        SELECT * FROM unnest(CAST(:pe_fields AS text[]), CAST(:pe_coeffs AS numeric[]))
            AS t(field, coeff)
    ),
    sp AS (
        SELECT * FROM unnest(CAST(:statuses AS text[]), CAST(:probs AS numeric[]))
            AS t(status, prob)
    ),
    proj AS (
        SELECT dp.development_id, dp.geom, sp.prob,
               sum(coalesce((dp.raw_attributes ->> pe.field)::numeric, 0) * pe.coeff)
                   AS people_equiv
        FROM core.development_project dp
        JOIN sp ON sp.status = dp.status
        CROSS JOIN pe
        WHERE dp.source_release_id = :source_release_id
          AND dp.geom IS NOT NULL
          AND (dp.status <> 'COMPLETED' OR dp.year_completed >= :completed_since_year)
        GROUP BY dp.development_id, dp.geom, sp.prob
    )
    INSERT INTO analytics.location_feature
        (release_id, cell_id, feature_version, dev_pipeline_people_800m, dev_projects_800m)
    SELECT
        ac.release_id, ac.cell_id, :feature_version,
        round(coalesce(sum(
            p.people_equiv * p.prob
            * (1 - ST_Distance(ac.centroid::geography, p.geom::geography) / :radius_m)
        ), 0)::numeric, 1) AS dev_pipeline_people_800m,
        count(p.development_id) AS dev_projects_800m
    FROM analytics.analysis_cell ac
    LEFT JOIN proj p
        ON p.geom && ST_Expand(ac.centroid, :bbox_deg)
       AND ST_DWithin(p.geom::geography, ac.centroid::geography, :radius_m)
    WHERE ac.release_id = :release_id
    GROUP BY ac.release_id, ac.cell_id
    ON CONFLICT (release_id, cell_id, feature_version) DO UPDATE SET
        dev_pipeline_people_800m = EXCLUDED.dev_pipeline_people_800m,
        dev_projects_800m        = EXCLUDED.dev_projects_800m,
        calculated_at            = now()
""")


@dataclass
class DevelopmentFeatureResult:
    release_id: int
    feature_version: str
    source_release_id: int
    config_version: str
    cells_written: int


def build_development_features(
    conn: Connection,
    feature_version: str = DEFAULT_FEATURE_VERSION,
    config: DevelopmentConfig | None = None,
    source_release_id: int | None = None,
) -> DevelopmentFeatureResult:
    """Compute development-pipeline features for the active release's
    grid. Runs inside the caller's transaction — must not commit."""
    config = config or load_development_config()

    release_id = conn.execute(_ACTIVE_RELEASE_SQL).scalar_one_or_none()
    if release_id is None:
        raise ValueError("No active grid release — run `cli build-grid` before building features.")

    if source_release_id is None:
        source_release_id = conn.execute(_LATEST_SOURCE_RELEASE_SQL).scalar_one_or_none()
        if source_release_id is None:
            raise ValueError("core.development_project is empty — load it first.")

    statuses = set(conn.execute(_STATUSES_SQL, {"source_release_id": source_release_id}).scalars())
    unknown = statuses - set(config.status_probability)
    if unknown:
        raise ValueError(
            f"Statuses in the data with no status_probability factor: {sorted(unknown)} "
            f"— add them to development_config.yaml (silently dropping them would "
            f"zero real pipeline)."
        )

    radius_m = config.distance_decay.radius_m
    conn.execute(
        _BUILD_SQL,
        {
            "release_id": release_id,
            "feature_version": feature_version,
            "source_release_id": source_release_id,
            "completed_since_year": config.completed_since_year,
            "pe_fields": list(config.people_equivalents),
            "pe_coeffs": list(config.people_equivalents.values()),
            "statuses": list(config.status_probability),
            "probs": list(config.status_probability.values()),
            "radius_m": radius_m,
            # >= radius at this latitude — same square pre-filter margin
            # as business_features (radius / 75_000).
            "bbox_deg": radius_m / 75_000.0,
        },
    )

    cells_written = conn.execute(
        text(
            "SELECT count(*) FROM analytics.location_feature "
            "WHERE release_id = :r AND feature_version = :fv "
            "AND dev_pipeline_people_800m IS NOT NULL"
        ),
        {"r": release_id, "fv": feature_version},
    ).scalar_one()

    return DevelopmentFeatureResult(
        release_id=release_id,
        feature_version=feature_version,
        source_release_id=source_release_id,
        config_version=config.version,
        cells_written=cells_written,
    )
