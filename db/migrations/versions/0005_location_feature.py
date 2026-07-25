"""Analytics: analytics.location_feature — the per-cell feature vector.

The precomputed feature vector ADR-002's scoring reads (one row per grid
cell per feature generation), so the runtime API never runs spatial
joins at request time (invariant 5). Shape follows
database-architecture.md's location_feature sketch, with two deliberate,
real-data-driven changes and one scope decision:

- Keyed (release_id, cell_id, feature_version) with an FK to
  analytics.analysis_cell(release_id, cell_id), NOT the doc's
  (cell_id, feature_version). A release OWNS its grid (migration 0004),
  so its features hang off the same (release_id, cell_id) key — a
  release stays a self-contained, atomically-swappable bundle (ADR-004,
  invariant 3). feature_version is retained as the product-facing
  version axis (score responses expose it; code-standards.md traces
  issues through it).

- Business columns are named to REAL ANZSIC4 granularity, not the doc's
  speculative cafes_400m/restaurants_400m split: ANZSIC4 4511 is
  "Cafes AND Restaurants" as one combined group — the source cannot
  separate them (profiled against the 2024 snapshot). So the column is
  cafe_restaurant_400m. Categories come from the versioned taxonomy
  (jobs/registry/industry_taxonomy.yaml), not hard-coded here
  (invariant 8).

- SCOPE: this migration creates only the business/competition columns —
  the slice the first feature loader (features/business_features.py)
  computes and has profiled. Pedestrian, worker, development, transport,
  and confidence columns are added by later migrations WITH their own
  loaders (same "don't model a column before its loader" discipline as
  the core schema, 0003). location_feature therefore grows by
  ALTER TABLE ADD COLUMN per feature family — cheap and non-breaking.

All feature columns are nullable: NULL means "not computed for this
generation" (a row written by a different feature family), distinct
from 0, which is a real observed count ("no cafés within 400m")
— architecture.md invariant 4.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE analytics.location_feature (
            release_id            bigint NOT NULL,
            cell_id               text   NOT NULL,
            feature_version       text   NOT NULL,

            -- Business / competition counts within the taxonomy's
            -- geodesic catchment (400 m; see industry_taxonomy.yaml).
            cafe_restaurant_400m  integer CHECK (cafe_restaurant_400m >= 0),
            takeaway_food_400m    integer CHECK (takeaway_food_400m   >= 0),
            bar_pub_400m          integer CHECK (bar_pub_400m         >= 0),
            retail_400m           integer CHECK (retail_400m          >= 0),
            complementary_400m    integer CHECK (complementary_400m   >= 0),

            calculated_at         timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (release_id, cell_id, feature_version),
            FOREIGN KEY (release_id, cell_id)
                REFERENCES analytics.analysis_cell (release_id, cell_id)
                ON DELETE CASCADE
        )
    """)
    # Lookup by cell across a generation (the API resolves the active
    # release_id, then reads its cells' features) — §9.4 idx_feature_lookup.
    op.execute(
        "CREATE INDEX location_feature_cell_idx "
        "ON analytics.location_feature (cell_id, feature_version)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE analytics.location_feature")
