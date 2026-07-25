"""Analytics: add development-pipeline columns to analytics.location_feature.

Fourth feature family (§13 development opportunity). ALTER-per-family
growth, as established in 0006/0009.

dev_pipeline_people_800m is the status- and distance-weighted "people
equivalents" of the development pipeline within 800 m of the cell
centroid: each project's scale (dwellings, office/retail floor area,
hotel rooms, student beds — converted to expected people via
jobs/registry/development_config.yaml coefficients) × a status
probability factor (an APPLIED project is far less certain than one
UNDER CONSTRUCTION) × linear distance decay. All factors are
configuration, never hidden constants (§13).

dev_projects_800m is the plain count of contributing projects — the
evidence number shown next to the derived value (invariant 6).

NULL semantics differ from jobs_800m ON PURPOSE: the Development
Activity Monitor is a complete municipal dataset with geometry on every
row (verified in the 2026-07-25 snapshot — 0 of 1,438 rows lack
coordinates) and has no suppression, so every catchment is fully
observable. A cell with nothing in range gets a real 0 ("no pipeline
nearby"), and NULL only ever means "feature not computed for this cell"
(invariant 4).

numeric (not integer) for the weighted value: probability × decay
products are fractional and rounding to integers would erase small but
real differences between neighbouring cells.
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE analytics.location_feature "
        "ADD COLUMN dev_pipeline_people_800m numeric CHECK (dev_pipeline_people_800m >= 0)"
    )
    op.execute(
        "ALTER TABLE analytics.location_feature "
        "ADD COLUMN dev_projects_800m integer CHECK (dev_projects_800m >= 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE analytics.location_feature DROP COLUMN dev_projects_800m")
    op.execute("ALTER TABLE analytics.location_feature DROP COLUMN dev_pipeline_people_800m")
