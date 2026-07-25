# db/ — migrations and SQL

Alembic migrations, written by hand (no ORM autogenerate — PostGIS DDL
and multi-schema layouts do not autogenerate well). Run with
`make db-migrate` from the repo root; it uses `DATABASE_DIRECT_URL`
(direct connection). **Never** run migrations through the pooled URL.

## Conventions

- One migration = one reviewable concern. Never edit an applied
  migration; add a new one.
- Filenames: `NNNN_short_slug.py` with a zero-padded numeric revision
  (`revision = "0002"`, `down_revision = "0001"`).
- Every `core.*`/`analytics.*` table that holds ingested data carries a
  `source_release_id` referencing `source.dataset_release(release_id)`
  so any row traces back to the raw snapshot that produced it. (This
  does not apply to the `source.*` tables themselves — they define
  what a release *is*, per migration 0002.)
- Spatial columns are `geometry(<Type>, 4326)` with a GiST index named
  `<table>_<column>_idx`.
- Nullable means "source did not report it" (e.g. suppressed CLUE
  cells). Never backfill nulls with zero.

## Migration roadmap (implement in order, one per unit of work)

1. `0001` ✔ extensions (`postgis`, `pg_trgm`) + the six schemas.
2. `0002` ✔ `source` schema: `source.dataset` (mirrors
   `jobs/registry/sources.yaml`, upserted on every ingest/adopt run),
   `source.dataset_release` (one row per raw snapshot directory —
   `UNIQUE (dataset_id, object_path)` makes same-day re-ingests
   idempotent), `source.dataset_release_file` (per-file checksums;
   most releases have one file, manually-adopted sources can have
   several), `source.ingestion_run` (one row per successful ingest,
   linking dataset → release). Wired into `jobs/retailscout_jobs/cli.py`
   via `provenance.py`; see `jobs/tests/test_provenance.py` for the
   round-trip proof. `row_count` is nullable, filled in by the staging
   loader in 0003 — the raw-snapshot step does not parse file contents.
   Deviates from the original `database-architecture.md` sketch (single
   `sha256`/`row_count` columns on one table) to accommodate multi-file
   manual-adopt snapshots; the intent (every release is traceable,
   checksummed, and reproducible) is unchanged.
3. `0003` — `core` schema: `pedestrian_sensor`,
   `pedestrian_observation` (PK `(sensor_id, observed_at)`),
   `business_establishment` (with `valid_from`/`valid_to`),
   `development_project`, `transport_stop`.
   Reference DDL: `database-architecture.md` §"Core tables".
   Use the **actual** council field names documented in
   `jobs/registry/sources.yaml` when mapping.
4. `0004` — `analytics` schema: `analysis_cell`, `location_feature`
   (PK `(cell_id, feature_version)`), `location_score`
   (PK `(cell_id, business_profile, score_version)`), plus the
   `data_release` / `active_release_id` pointer that makes releases
   atomic (architecture.md invariant 3).
5. `0005` — `app` schema: `project`, `saved_location`.
6. `0006` — `audit` schema: `score_request`, `data_quality_result`.
