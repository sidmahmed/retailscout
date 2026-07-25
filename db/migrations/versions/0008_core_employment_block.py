"""Core: core.employment_block — CLUE jobs per block per census year.

The worker-demand fact (§12 / §16.3 fact_employment_block_snapshot):
job counts by block, joined to core.clue_block geometry (migration 0007)
on block_id to place worker demand in space. Feeds the worker-demand
feature columns (jobs_400m/jobs_800m) that follow.

Shape from the real 2026-07-25 snapshot (13,519 rows, profiled — not
guessed):
- PK (census_year, block_id) is unique (23 census years 2002–2024 ×
  ~603 blocks). census_year is a real int here (unlike some CLUE
  sources' text years).
- SUPPRESSION IS THE POINT OF THIS TABLE: an empty CSV cell means the
  count was SUPPRESSED (small-cell confidentiality) and is stored as
  NULL; "0" means an OBSERVED zero and is stored as 0. These are never
  conflated (architecture.md invariant 4). Even total_jobs is
  suppressed for 133 of 603 blocks in 2024 — so total_jobs is nullable,
  and the worker-demand feature must treat a suppressed total as
  UNKNOWN, not zero. Per the registry note, a suppressed total is NOT
  reconstructed by summing the (also partially-suppressed) industry
  columns.
- NO foreign key to core.clue_block, matching the pedestrian_observation
  precedent: clue_block is a current-snapshot geometry dimension, and a
  hard FK would break loading historical rows if a future block snapshot
  ever drops a block_id. All 603 current employment block_ids ARE in the
  current clue_block snapshot (verified), but that is not enforced as a
  constraint. block_id is indexed for the join.
- The 20 ANZSIC-division industry counts are preserved losslessly in
  jobs_by_industry jsonb (JSON null vs 0 keeps the suppression
  distinction), the same pattern development_project uses for its wide
  attribute set — they are not first-class columns until an industry-mix
  consumer needs to query them individually.

All numeric values in the real file are integers (no decimals or
negatives) — confirmed before choosing integer typing.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE core.employment_block (
            census_year        integer NOT NULL,
            block_id           integer NOT NULL,
            clue_small_area    text NOT NULL,
            total_jobs         integer CHECK (total_jobs >= 0),
            jobs_by_industry   jsonb NOT NULL,
            source_release_id  bigint NOT NULL REFERENCES source.dataset_release(release_id),
            loaded_at          timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (census_year, block_id)
        )
    """)
    op.execute("CREATE INDEX employment_block_block_id_idx ON core.employment_block (block_id)")


def downgrade() -> None:
    op.execute("DROP TABLE core.employment_block")
