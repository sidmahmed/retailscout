"""Extensions and schemas.

The six-schema layout comes from database-architecture.md:

  source     — dataset registry, releases, ingestion runs (provenance)
  staging    — close-to-source loads; disposable, rebuilt each ingest
  core       — cleaned, standardised council data
  analytics  — precomputed cells, features, scores served to users
  app        — users, projects, saved locations
  audit      — score requests, data-quality results, admin actions

Supabase note: CREATE EXTENSION works on Supabase but installs into the
`extensions` schema by default; that is fine — code must never assume
the extension's schema, and search_path is set per-role at deploy time.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("source", "staging", "core", "analytics", "app", "audit")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    # Extensions are left installed on purpose: other databases/tools may
    # rely on them, and dropping postgis destroys spatial_ref_sys.
