"""Worker-demand features: allocate CLUE block jobs to cell catchments.

Fills jobs_400m / jobs_800m on analytics.location_feature (§12) for the
active grid release. For each cell, the estimated jobs within a 400 m /
800 m catchment of the centroid, AREA-WEIGHTED across the CLUE blocks the
catchment overlaps (§9.3): a block contributes
total_jobs × (overlap_area / block_area). Blocks (~250 m) are large
relative to the catchment, so whole-block or centroid counting would be
crude — and block centroids are unreliable anyway (some fall outside
their own polygon; found loading core.clue_block).

Suppression preserved (invariant 4): a block with suppressed
(NULL) total_jobs contributes nothing, and a catchment that overlaps NO
block with a known total yields NULL — SUM over an empty filtered set is
NULL in SQL, which is exactly the semantics we want (unknown, not 0). So
0 means "known blocks, ~no jobs in range", NULL means "no known job data
in range".

Uses the latest census_year snapshot by default. Catchments are geodesic
ST_Buffer circles; the area RATIO is computed in EPSG:4326, where the
lon/lat distortion cancels between numerator and denominator at a block's
latitude, so the fraction is accurate without reprojecting.

Upserts only jobs_400m/jobs_800m for (release_id, cell_id,
feature_version), composing with the other feature-family loaders.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

DEFAULT_FEATURE_VERSION = "v1"
LOCAL_RADIUS_M = 400
WIDE_RADIUS_M = 800

_ACTIVE_RELEASE_SQL = text("SELECT release_id FROM analytics.active_release WHERE only_one")
_MAX_CENSUS_YEAR_SQL = text("SELECT max(census_year) FROM core.employment_block")

# Per cell: buffer the centroid to both radii (geodesic), find every block
# overlapping the WIDER catchment via the GiST index (cb.geom && c800),
# join its known job total, and area-weight into each radius. SUM over an
# empty filtered set returns NULL (suppressed/uncovered -> unknown).
_BUILD_SQL = text("""
    WITH cell_catchment AS (
        SELECT ac.cell_id,
               ST_Buffer(ac.centroid::geography, :r_local)::geometry AS c_local,
               ST_Buffer(ac.centroid::geography, :r_wide)::geometry  AS c_wide
        FROM analytics.analysis_cell ac
        WHERE ac.release_id = :release_id
    )
    INSERT INTO analytics.location_feature
        (release_id, cell_id, feature_version, jobs_400m, jobs_800m)
    SELECT
        :release_id, cc.cell_id, :feature_version,
        round(sum(
            eb.total_jobs
            * ST_Area(ST_Intersection(cb.geom, cc.c_local)) / ST_Area(cb.geom)
        ) FILTER (WHERE eb.total_jobs IS NOT NULL
                    AND ST_Intersects(cb.geom, cc.c_local)))::integer AS jobs_400m,
        round(sum(
            eb.total_jobs
            * ST_Area(ST_Intersection(cb.geom, cc.c_wide)) / ST_Area(cb.geom)
        ) FILTER (WHERE eb.total_jobs IS NOT NULL))::integer AS jobs_800m
    FROM cell_catchment cc
    LEFT JOIN core.clue_block cb ON cb.geom && cc.c_wide
    LEFT JOIN core.employment_block eb
        ON eb.block_id = cb.block_id AND eb.census_year = :census_year
    GROUP BY cc.cell_id
    ON CONFLICT (release_id, cell_id, feature_version) DO UPDATE SET
        jobs_400m     = EXCLUDED.jobs_400m,
        jobs_800m     = EXCLUDED.jobs_800m,
        calculated_at = now()
""")


@dataclass
class WorkerFeatureResult:
    release_id: int
    feature_version: str
    census_year: int
    cells_written: int


def build_worker_features(
    conn: Connection,
    feature_version: str = DEFAULT_FEATURE_VERSION,
    census_year: int | None = None,
) -> WorkerFeatureResult:
    """Compute worker-demand features for the active release's grid.
    Runs inside the caller's transaction — must not commit."""
    release_id = conn.execute(_ACTIVE_RELEASE_SQL).scalar_one_or_none()
    if release_id is None:
        raise ValueError("No active grid release — run `cli build-grid` before building features.")

    if census_year is None:
        census_year = conn.execute(_MAX_CENSUS_YEAR_SQL).scalar_one()
        if census_year is None:
            raise ValueError("core.employment_block is empty — load it first.")

    conn.execute(
        _BUILD_SQL,
        {
            "release_id": release_id,
            "feature_version": feature_version,
            "census_year": census_year,
            "r_local": LOCAL_RADIUS_M,
            "r_wide": WIDE_RADIUS_M,
        },
    )

    cells_written = conn.execute(
        text(
            "SELECT count(*) FROM analytics.location_feature "
            "WHERE release_id = :r AND feature_version = :fv"
        ),
        {"r": release_id, "fv": feature_version},
    ).scalar_one()

    return WorkerFeatureResult(
        release_id=release_id,
        feature_version=feature_version,
        census_year=census_year,
        cells_written=cells_written,
    )
