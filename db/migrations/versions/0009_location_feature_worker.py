"""Analytics: add worker-demand columns to analytics.location_feature.

Third feature family (§12 worker demand). ALTER-per-family growth, as
established in 0006.

jobs_400m / jobs_800m are the estimated number of jobs within a 400 m /
800 m catchment of the cell centroid (§9.2 local vs. wider). They are
AREA-WEIGHTED allocations of core.employment_block.total_jobs across the
CLUE blocks the catchment overlaps (§9.3 "allocate block totals to
intersecting cells"): a block contributes total_jobs × (overlap area /
block area). Whole-block or centroid counting would be crude here — CLUE
blocks (~250 m) are large relative to the catchment.

Suppression is preserved (invariant 4): suppressed blocks (NULL
total_jobs — 133 of 603 in 2024) contribute nothing to the sum, and if a
catchment overlaps NO block with a known total, the column is NULL
(unknown), never 0. So 0 means "known blocks, ~no jobs", NULL means "no
known job data in range" — a real distinction. (A finer partial-coverage
confidence metric belongs to the later confidence model, not this raw
feature.)

Nullable, CHECK >= 0 — see above for the NULL semantics.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_COLUMNS = ["jobs_400m", "jobs_800m"]


def upgrade() -> None:
    for col in _COLUMNS:
        op.execute(
            f"ALTER TABLE analytics.location_feature "
            f"ADD COLUMN {col} integer CHECK ({col} >= 0)"
        )


def downgrade() -> None:
    for col in _COLUMNS:
        op.execute(f"ALTER TABLE analytics.location_feature DROP COLUMN {col}")
