"""Business/competition features: count nearby establishments per cell.

Fills the business columns of analytics.location_feature (§11) for the
currently-active grid release: for every analysis cell, the number of
establishments of each RetailScout taxonomy category within a geodesic
catchment of the cell centroid (§9.3 "point businesses: distance to
cell centroid"). A pure ST_DWithin spatial count — no interpolation,
decay, or confidence modelling (those belong to the pedestrian-demand
unit).

Real-data decisions (profiled against the live DB, not assumed):
- Uses only the LATEST census_year snapshot (default max(census_year) =
  2024): 19,672 CURRENT establishments. The full table stacks every
  census year (413k rows) — counting all years would multiply-count a
  tenancy across years. Current competition is the current snapshot.
- Excludes ANZSIC4 "0000 Vacant Space" (5,335 rows) — not a business —
  via the taxonomy's exclude_codes.
- Category per establishment comes from jobs/registry/industry_taxonomy
  .yaml (invariant 8), resolved in Python; SQL only joins a plain
  (code -> category) mapping passed as arrays. ANZSIC4 4511 is a
  COMBINED "Cafes and Restaurants" group (source cannot split them), so
  the column is cafe_restaurant_400m — see the 0005 migration docstring.

Catchment is a geodesic buffer (ST_DWithin on geography), labelled
approximate: §9.2 prefers pedestrian-network distance, deferred until a
maintained network exists. Cells with no establishments in range get a
real 0 (LEFT JOIN), never NULL — 0 is observed ("no cafés within
400m"), distinct from "not computed" (invariant 4).

Runs against the ACTIVE release's grid (analytics.active_release). In
the eventual full pipeline a fresh release is built, ALL features +
scores computed into it, then published atomically (invariant 3); until
the scoring stage exists, computing against the live grid release is the
pragmatic path and is idempotent (upsert on the PK).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..taxonomy import IndustryTaxonomy, load_taxonomy

DEFAULT_FEATURE_VERSION = "v1"

_ACTIVE_RELEASE_SQL = text("SELECT release_id FROM analytics.active_release WHERE only_one")

_MAX_CENSUS_YEAR_SQL = text("SELECT max(census_year) FROM core.business_establishment")

# One statement: map each in-catchment establishment to its category via
# the passed (code, category) arrays, count per category per cell, and
# upsert. LEFT JOINs keep every active-release cell, counting 0 where no
# establishment (or none of a category) is in range.
_BUILD_SQL = text("""
    WITH code_category AS (
        SELECT code, category
        FROM unnest(CAST(:codes AS text[]), CAST(:cats AS text[])) AS t(code, category)
    )
    INSERT INTO analytics.location_feature
        (release_id, cell_id, feature_version,
         cafe_restaurant_400m, takeaway_food_400m, bar_pub_400m,
         retail_400m, complementary_400m)
    SELECT
        ac.release_id, ac.cell_id, :feature_version,
        count(*) FILTER (WHERE m.category = 'cafe_restaurant') AS cafe_restaurant_400m,
        count(*) FILTER (WHERE m.category = 'takeaway_food')   AS takeaway_food_400m,
        count(*) FILTER (WHERE m.category = 'bar_pub')         AS bar_pub_400m,
        count(*) FILTER (WHERE m.category = 'retail')          AS retail_400m,
        count(*) FILTER (WHERE m.category = 'complementary')   AS complementary_400m
    FROM analytics.analysis_cell ac
    LEFT JOIN core.business_establishment b
        ON b.census_year = :census_year
       AND b.geom IS NOT NULL
       -- Index-accelerated bbox pre-filter (uses business_establishment_geom_idx):
       -- ST_Expand by :bbox_deg (>=:radius m at this latitude) narrows the
       -- candidate set, then the geography ST_DWithin gives the exact 400 m
       -- circle. Casting straight to geography would ignore the GiST index.
       AND b.geom && ST_Expand(ac.centroid, :bbox_deg)
       AND ST_DWithin(b.geom::geography, ac.centroid::geography, :radius)
    LEFT JOIN code_category m ON m.code = b.industry_anzsic4_code
    WHERE ac.release_id = :release_id
    GROUP BY ac.release_id, ac.cell_id
    ON CONFLICT (release_id, cell_id, feature_version) DO UPDATE SET
        cafe_restaurant_400m = EXCLUDED.cafe_restaurant_400m,
        takeaway_food_400m   = EXCLUDED.takeaway_food_400m,
        bar_pub_400m         = EXCLUDED.bar_pub_400m,
        retail_400m          = EXCLUDED.retail_400m,
        complementary_400m   = EXCLUDED.complementary_400m,
        calculated_at        = now()
""")


@dataclass
class BusinessFeatureResult:
    release_id: int
    feature_version: str
    census_year: int
    catchment_metres: int
    cells_written: int


def _code_category_arrays(
    conn: Connection, taxonomy: IndustryTaxonomy, census_year: int
) -> tuple[list[str], list[str]]:
    """Resolve every distinct ANZSIC4 code present in the snapshot to a
    real category (dropping excluded/'other' codes — they are counted in
    no column). Returns parallel (codes, categories) arrays for SQL."""
    real_categories = set(taxonomy.category_names)
    codes = conn.execute(
        text(
            "SELECT DISTINCT industry_anzsic4_code FROM core.business_establishment "
            "WHERE census_year = :y AND industry_anzsic4_code IS NOT NULL"
        ),
        {"y": census_year},
    ).scalars()
    pairs = [(c, taxonomy.resolve(c)) for c in codes]
    mapped = [(c, cat) for c, cat in pairs if cat in real_categories]
    return [c for c, _ in mapped], [cat for _, cat in mapped]


def build_business_features(
    conn: Connection,
    feature_version: str = DEFAULT_FEATURE_VERSION,
    census_year: int | None = None,
) -> BusinessFeatureResult:
    """Compute business/competition features for the active release's
    grid. Runs inside the caller's transaction — must not commit."""
    release_id = conn.execute(_ACTIVE_RELEASE_SQL).scalar_one_or_none()
    if release_id is None:
        raise ValueError("No active grid release — run `cli build-grid` before building features.")

    if census_year is None:
        census_year = conn.execute(_MAX_CENSUS_YEAR_SQL).scalar_one()
        if census_year is None:
            raise ValueError("core.business_establishment is empty — load it first.")

    taxonomy = load_taxonomy()
    codes, cats = _code_category_arrays(conn, taxonomy, census_year)

    # Degrees for the bbox pre-filter. At Melbourne's latitude (~-37.8°)
    # a degree of longitude — the binding, smaller axis — is ~87.9 km, so
    # radius / 75_000 gives a square comfortably larger than the radius
    # circle in BOTH axes (never under-covers; the exact geography
    # ST_DWithin trims the surplus).
    bbox_deg = taxonomy.catchment_metres / 75_000.0

    conn.execute(
        _BUILD_SQL,
        {
            "codes": codes,
            "cats": cats,
            "feature_version": feature_version,
            "census_year": census_year,
            "radius": taxonomy.catchment_metres,
            "bbox_deg": bbox_deg,
            "release_id": release_id,
        },
    )

    cells_written = conn.execute(
        text(
            "SELECT count(*) FROM analytics.location_feature "
            "WHERE release_id = :r AND feature_version = :fv"
        ),
        {"r": release_id, "fv": feature_version},
    ).scalar_one()

    return BusinessFeatureResult(
        release_id=release_id,
        feature_version=feature_version,
        census_year=census_year,
        catchment_metres=taxonomy.catchment_metres,
        cells_written=cells_written,
    )
