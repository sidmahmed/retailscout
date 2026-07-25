"""Analytics: analytics.sensor_daypart_baseline — per-sensor foot-traffic baselines.

Step 1 of pedestrian demand (§10.1-10.2): robust per-sensor typical
hourly pedestrian counts, by day type (weekday/saturday/sunday) and
daypart (morning/lunch/afternoon/evening), over the trailing window.
These are the SENSOR-level baselines that the next unit interpolates to
grid cells (§10.3) — this table is deliberately NOT cell- or
grid-release-scoped; it depends only on sensor observations and the
versioned daypart config (jobs/registry/pedestrian_config.yaml), so
`baseline_version` (the config version) is its version axis.

Stores robust statistics (median is the headline; mean + p25/p75 give
spread) rather than a single number, plus n_observations and n_days so
the interpolation/confidence step (§10.4) has a sample-size signal. NOT
presented as observed storefront footfall anywhere downstream (§10.3).

NO foreign key to core.pedestrian_sensor — same precedent as
pedestrian_observation: some observed sensor_ids are not in the current
sensor-locations snapshot, and a hard FK would drop their baselines.
source_release_id traces to the pedestrian-observation release the
baselines were computed from.
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE analytics.sensor_daypart_baseline (
            sensor_id          integer NOT NULL,
            day_type           text NOT NULL,
            daypart            text NOT NULL,
            baseline_version   text NOT NULL,
            median_count       numeric,
            mean_count         numeric,
            p25_count          numeric,
            p75_count          numeric,
            n_observations     integer NOT NULL,
            n_days             integer NOT NULL,
            window_start       date NOT NULL,
            window_end         date NOT NULL,
            source_release_id  bigint NOT NULL REFERENCES source.dataset_release(release_id),
            calculated_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (sensor_id, day_type, daypart, baseline_version)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE analytics.sensor_daypart_baseline")
