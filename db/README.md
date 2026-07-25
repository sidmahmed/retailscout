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
   - `pedestrian_hourly.py` — the big one: 1,610,006 rows, streamed
     (never held fully in memory) and inserted in batches of 5,000
     multi-row `VALUES ... ON CONFLICT` statements (~19s end to end on
     a dev laptop — measured, not estimated). Confirmed against the
     FULL real file (not a sample): zero duplicate
     `(location_id, sensing_date, hourday)` keys, so
     `(sensor_id, observed_at)` is a safe PK; no nulls in any column
     the loader uses; no negative counts. `observed_at` is built by
     localizing `sensing_date`+`hourday` in `Australia/Melbourne` via
     `zoneinfo` then converting to UTC — checked against all 4 real
     DST transition dates in the file's range: spring-forward dates
     never emit the nonexistent local hour (source already omits it,
     zero collision risk), fall-back dates emit the ambiguous hour
     exactly once per sensor (source already collapsed it). Round-trip
     verified against a known real row (sensor 109,
     2025-01-21 14:00 local → 2025-01-21 03:00 UTC, count 214) and
     against three CONFIRMED orphan sensor_ids (28, 65, 78 — present in
     this data, absent from the current `pedestrian_sensor_locations`
     snapshot) which all loaded correctly precisely because there is
     no FK. Idempotent re-load of the full 1.6M rows confirmed. See
     `jobs/tests/test_transform_pedestrian_hourly.py`.
   - `business_establishment.py` — all 413,550 rows loaded. Confirmed
     against the FULL real file: NO stable natural key exists
     ((census_year, property_id, trading_name, industry_anzsic4_code)
     has 8,344 groups with >1 row out of 379,558), so this loader
     deletes rows by `source_release_id` then reinserts, rather than
     `ON CONFLICT` upsert — idempotent for re-running the SAME
     release, not for deduplicating an unchanged file re-ingested on a
     different day (that needs the entity-matching strategy already
     deferred for `valid_from`/`valid_to`). 4,785 rows (~1.2%) have no
     lon/lat; `geom` is left NULL for those, never a placeholder
     point. Hit and fixed a real SQLAlchemy/psycopg batching bug along
     the way: a bind parameter referenced twice inside a `CASE WHEN`
     expression in a batched multi-row INSERT does not scope correctly
     per row (`AmbiguousParameter`, then silently wrong values) — fixed
     by computing WKT in Python and relying on `ST_GeomFromText(NULL)`
     naturally returning NULL, removing the `CASE` entirely. See
     `jobs/tests/test_transform_business_establishment.py`.
   - `development_project.py` — all 1,438 rows loaded. Unlike
     business_establishments, `development_key` IS confirmed globally
     unique (0 duplicates) — a real natural key exists here — but this
     loader still uses delete-by-release + reinsert for consistency
     and because architecture.md's own refresh cadence for this source
     is "Monthly" full snapshot, which is what full-replace-on-load
     actually models. The ~30 numeric attribute columns (floor areas,
     dwelling/bed counts, car/bike spaces — all confirmed integer, no
     decimals anywhere in the real file) plus `data_format` and
     `town_planning_application` are stored in `raw_attributes jsonb`
     as real JSON numbers/strings, not stringified. See
     `jobs/tests/test_transform_development_project.py`.
   - `transport_stop.py` — the most structurally complex loader: the
     PTV GTFS archive is a zip of numbered mode-folders, each holding
     its own inner `google_transit.zip` with a standard `stops.txt`.
     Mode per folder number (`FOLDER_TO_MODE`) was determined by
     inspecting each bundle's real `routes.txt` `route_type` and route
     names (e.g. folder 2's routes include "Alamein - City" at
     `route_type=400` → metro train; folder 10 is "The Overland" at
     `route_type=102` → long-distance train) — documented per-folder
     in the module docstring, not guessed. Statewide GTFS has ~31,973
     stops; this loader filters to boardable stop/platform records
     (`location_type` `''`/`'0'`, excluding station/entrance/node
     rows) within `core.municipal_boundary` + 1km (a cheap Python
     bbox pre-filter, then a precise `ST_DWithin` prune in SQL),
     leaving 1,300 real stops. A stop_id CAN collide across mode
     bundles — confirmed empirically: all 60 real regional-train stops
     in range share identical stop_ids with metro-train stops at the
     same physical platforms (Flinders St, Southern Cross, etc.).
     `core.transport_stop` has one `mode` column, so collisions
     resolve deterministically by a fixed, documented processing order
     ending in `tram`/`metro_train` (the modes that define CBD access,
     this product's initial scope) — verified both against the real
     archive and with a dedicated collision test. Full-table-replace
     on every load, since this loader owns the whole table. See
     `jobs/tests/test_transform_transport_stop.py`.
   **All six core loaders are now implemented and verified against
   real data.** Cross-referencing: municipal boundary ← used by both
   the FR-02 boundary check tests and the transport_stop filter;
   pedestrian sensors ← all 134 confirmed inside the boundary;
   transport stops ← all 1,300 confirmed inside the boundary + 1km.
4. `0004` — `analytics` schema: `analysis_cell`, `location_feature`
   (PK `(cell_id, feature_version)`), `location_score`
   (PK `(cell_id, business_profile, score_version)`), plus the
   `data_release` / `active_release_id` pointer that makes releases
   atomic (architecture.md invariant 3).
5. `0005` — `app` schema: `project`, `saved_location`.
6. `0006` — `audit` schema: `score_request`, `data_quality_result`.
