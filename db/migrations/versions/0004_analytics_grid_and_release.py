"""Analytics schema: atomic data-release machinery + the hex analysis grid.

Implements the first slice of the `analytics` schema (architecture.md
ADR-002/ADR-004, invariant 3). SCOPE IS DELIBERATELY the release
pointer + the precomputed hex grid only — NOT location_feature /
location_score. The db/README.md roadmap originally grouped all four
under 0004, but the feature/score table shapes depend on the scoring
methodology (architecture.md §§10-14), which does not exist yet;
modelling them now would be speculative in exactly the way the core
schema (0003) avoided. They get their own migration when their
Phase 2 loaders exist and can be verified against real computed values.
The atomic-release machinery is still built now because the grid is
the first real analytics artifact to publish — it exercises the
release/rollback path end-to-end before Phase 2 depends on it.

    analytics.data_release   one row per published analytics generation
                             (a bundle: this grid now, its features and
                             scores later). Distinct from
                             source.dataset_release (migration 0002),
                             which tracks raw *downloads*; this tracks
                             published *computed* artifacts the runtime
                             API serves. grid_resolution is the H3
                             resolution the release's analysis_cell rows
                             were built at (stored here, not per-cell —
                             it is uniform within a release).
                             boundary_source_release_id records which
                             raw municipal-boundary snapshot the grid was
                             clipped against, so a cell traces all the
                             way back to the boundary bytes.

    analytics.active_release singleton pointer (one row, enforced by a
                             boolean PK fixed to true) naming the
                             currently-live data_release. Publishing is
                             an atomic UPDATE of this one row (invariant
                             3); rollback is the same UPDATE back to a
                             prior release_id. Old releases' rows are
                             left intact so rollback is instant and
                             lossless.

    analytics.analysis_cell  the precomputed hex grid (H3). PK is
                             (release_id, cell_id): a release OWNS its
                             grid, so a release is a self-contained,
                             atomically-swappable unit (ADR-004). H3
                             cell_ids are globally stable, so the same
                             geography yields the same cell_id across
                             releases at the same resolution — the ~2.3k
                             rows are duplicated per release, which is
                             negligible storage and buys full release
                             isolation. `geom` is the full H3 hexagon
                             (used at request time to map a click to its
                             cell via ST_Contains — keeps the runtime
                             API H3-dependency-free, ADR-002); `centroid`
                             is H3's canonical cell centre, stored so
                             Phase 2 catchment math has a stable point
                             per cell without recomputing from cell_id.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE analytics.data_release (
            release_id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            status                      text NOT NULL DEFAULT 'building'
                CHECK (status IN ('building', 'published', 'superseded')),
            grid_resolution             integer NOT NULL,
            boundary_source_release_id  bigint NOT NULL
                REFERENCES source.dataset_release(release_id),
            notes                       text,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            published_at                timestamptz
        )
    """)

    # Singleton pointer: the boolean PK fixed to TRUE means at most one
    # row can ever exist, so the "which release is live" answer is a
    # single row updated atomically — never a race between multiple rows.
    op.execute("""
        CREATE TABLE analytics.active_release (
            only_one    boolean PRIMARY KEY DEFAULT true CHECK (only_one),
            release_id  bigint NOT NULL REFERENCES analytics.data_release(release_id),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE analytics.analysis_cell (
            release_id  bigint NOT NULL REFERENCES analytics.data_release(release_id)
                ON DELETE CASCADE,
            cell_id     text NOT NULL,
            geom        geometry(Polygon, 4326) NOT NULL,
            centroid    geometry(Point, 4326) NOT NULL,
            PRIMARY KEY (release_id, cell_id)
        )
    """)
    op.execute(
        "CREATE INDEX analysis_cell_geom_idx ON analytics.analysis_cell USING GIST (geom)"
    )
    op.execute(
        "CREATE INDEX analysis_cell_centroid_idx "
        "ON analytics.analysis_cell USING GIST (centroid)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE analytics.analysis_cell")
    op.execute("DROP TABLE analytics.active_release")
    op.execute("DROP TABLE analytics.data_release")
