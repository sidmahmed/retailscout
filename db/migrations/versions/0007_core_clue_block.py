"""Core: core.clue_block — CLUE block geometry (spatial dimension).

The block-level spatial dimension the block-keyed CLUE facts join to
(architecture.md §16.2 dim_clue_block). Added now because worker-demand
features (§12) need to place per-block job totals in space: employment
is reported per block_id with NO geometry of its own, so it is useless
for cell allocation until the block polygons exist. This table is the
prerequisite for the employment_by_block core loader and the
worker-demand feature that follows.

Shape from the real 2026-07-25 snapshot (603 records, profiled — not
guessed): every geo_shape is a GeoJSON Polygon (never MultiPolygon), so
geom is typed Polygon; block_id is a unique integer natural key (603
distinct, no nulls) and all 603 employment_by_block block_ids are a
subset of it (join verified). geo_point_2d gives a ready block centroid
— stored so worker-demand allocation has a stable per-block point
without recomputing from the polygon. region_name/area_name are the
CLUE geographic labels (13 and 15 distinct); both non-null in the real
data.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE core.clue_block (
            block_id           integer PRIMARY KEY,
            region_name        text NOT NULL,
            area_name          text NOT NULL,
            centroid           geometry(Point, 4326) NOT NULL,
            geom               geometry(Polygon, 4326) NOT NULL,
            source_release_id  bigint NOT NULL REFERENCES source.dataset_release(release_id),
            loaded_at          timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX clue_block_geom_idx ON core.clue_block USING GIST (geom)")
    op.execute("CREATE INDEX clue_block_centroid_idx ON core.clue_block USING GIST (centroid)")


def downgrade() -> None:
    op.execute("DROP TABLE core.clue_block")
