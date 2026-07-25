"""Analytics: analytics.cell_pedestrian_daypart — interpolated foot traffic per cell.

Step 2 of pedestrian demand (§10.3-10.4): the per-cell MODELLED
pedestrian activity, by day type and daypart, produced by
distance-decay interpolation of the sensor baselines (0010) to grid
cells, plus a SEPARATE foot-traffic confidence band.

A narrow table (one row per cell × day_type × daypart), not wide columns
on location_feature: the interpolation output is inherently long, and
this keeps the daypart set config-driven rather than baked into a schema.
Release-scoped (FK to analysis_cell) because it is per grid cell;
baseline_version records which sensor baselines fed it.

pedestrian_estimate is deliberately named an ESTIMATE and is NEVER to be
presented as observed storefront footfall (§10.3) — it is a weighted mean
of nearby sensor medians. foot_traffic_confidence is exposed SEPARATELY
from the estimate (§10.4 / §15.3 "confidence should not be blended
invisibly into suitability"). A cell with NO sensor within the max
distance is 'insufficient' and simply has NO row here (absent = insufficient,
invariant 4) — with ~61% of the municipality beyond sensor range, most
cells legitimately have no estimate. n_sensors and nearest_sensor_m are
the raw confidence signals, kept so the banding can evolve.
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE analytics.cell_pedestrian_daypart (
            release_id              bigint NOT NULL,
            cell_id                 text NOT NULL,
            day_type                text NOT NULL,
            daypart                 text NOT NULL,
            baseline_version        text NOT NULL,
            pedestrian_estimate     numeric,
            n_sensors               integer NOT NULL,
            nearest_sensor_m        numeric NOT NULL,
            foot_traffic_confidence text NOT NULL
                CHECK (foot_traffic_confidence IN ('high', 'medium', 'low')),
            calculated_at           timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (release_id, cell_id, day_type, daypart, baseline_version),
            FOREIGN KEY (release_id, cell_id)
                REFERENCES analytics.analysis_cell (release_id, cell_id) ON DELETE CASCADE
        )
    """)
    op.execute(
        "CREATE INDEX cell_pedestrian_daypart_cell_idx "
        "ON analytics.cell_pedestrian_daypart (cell_id, day_type, daypart)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE analytics.cell_pedestrian_daypart")
