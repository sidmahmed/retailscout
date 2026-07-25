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
3. `0003` ✔ `core` schema — all 6 tables created:
   `municipal_boundary`, `pedestrian_sensor`, `pedestrian_observation`
   (PK `(sensor_id, observed_at)`, deliberately no FK to
   `pedestrian_sensor` — historical sensor_ids can predate the current
   sensor-locations snapshot), `business_establishment` (no
   `valid_from`/`valid_to` yet — needs a deliberate cross-year identity
   strategy first, see the migration file's docstring),
   `development_project` (wide/variable numeric attributes kept in a
   `raw_attributes jsonb` column rather than ~35 speculative typed
   columns), `transport_stop` (shaped for PTV GTFS `stops.txt`, not
   the deferred council datasets). Column types are informed by
   inspecting the real 2026-07-25 snapshots, not guessed — see the
   migration file's docstring for specifics per table.
   **Two loaders implemented so far**, both in
   `jobs/retailscout_jobs/transform/`, wired via `cli.py load
   <source_id>` and registered in `transform/__init__.py` `LOADERS`:
   - `municipal_boundary.py` — verified against live PostGIS: loaded
     geometry has the correct real-world area (37.66 km², matches the
     actual City of Melbourne), and `ST_Contains` correctly includes a
     CBD point and excludes an outside-boundary point (the
     golden-locations FR-02 control) — see
     `jobs/tests/test_transform_municipal_boundary.py`.
   - `pedestrian_sensor.py` — verified against live PostGIS: all 134
     real sensors loaded, nullable fields handled correctly (1 sensor
     with null `installed_at`, 34 with null direction labels — matches
     the real data exactly, not just the fixture), idempotent re-load
     confirmed, and a cross-table sanity check confirmed **all 134
     sensors fall inside the loaded municipal boundary** — the two
     loaders agree with each other, not just individually plausible.
     Deliberately does NOT track sensor-location history (always
     upserts to the latest known position) — architecture.md §4.2's
     concern about relocated sensors needs a period/validity table,
     scoped out until `pedestrian_hourly` is loaded and the gap
     actually matters. See
     `jobs/tests/test_transform_pedestrian_sensor.py`.
   **Remaining loaders are separate future units**, roughly in this
   order: `pedestrian_hourly` (1.6M rows — needs streaming CSV, not a
   full in-memory parse; CSV is semicolon-delimited with a UTF-8 BOM,
   see `jobs/registry/sources.yaml` header comment; `id` column is a
   synthetic composite of location_id+hourday+date, NOT a stable key —
   build `observed_at` from `sensing_date` + `hourday` instead and use
   `(sensor_id, observed_at)` as the real key), `business_establishments`,
   `development_activity`, then GTFS `stops.txt` (nested inside two
   zip levels — see `jobs/registry/sources.yaml`'s `ptv_gtfs` entry).
4. `0004` — `analytics` schema: `analysis_cell`, `location_feature`
   (PK `(cell_id, feature_version)`), `location_score`
   (PK `(cell_id, business_profile, score_version)`), plus the
   `data_release` / `active_release_id` pointer that makes releases
   atomic (architecture.md invariant 3).
5. `0005` — `app` schema: `project`, `saved_location`.
6. `0006` — `audit` schema: `score_request`, `data_quality_result`.
