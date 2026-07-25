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
4. `0004` ✔ `analytics` schema — atomic-release machinery + the hex
   analysis grid. **Deliberately scoped to the grid**, not the full
   roadmap sketch below: the original plan grouped `analysis_cell`,
   `location_feature`, and `location_score` under one migration, but
   the feature/score table shapes depend on the Phase 2 scoring
   methodology (architecture.md §§10-14) that does not exist yet —
   modelling them now would be the speculative guessing the core schema
   (0003) avoided. They move to `0005` (see below), created with their
   loaders. Built now:
   - `analytics.data_release` — one row per published analytics
     generation (the grid now; its features/scores later). Distinct
     from `source.dataset_release` (0002): that tracks raw *downloads*,
     this tracks published *computed* artifacts the runtime serves.
     `grid_resolution` (the H3 resolution, uniform per release) and
     `boundary_source_release_id` (which raw boundary snapshot the grid
     was clipped against) live here, so a cell traces all the way back
     to the boundary bytes.
   - `analytics.active_release` — singleton pointer (boolean PK fixed
     to `true` ⇒ at most one row) naming the live release. Publishing
     is an atomic UPDATE of this one row (invariant 3); rollback is the
     same UPDATE back to a prior `release_id`. Verified against live
     PostGIS: a second `build-grid` flips the pointer, marks the prior
     release `superseded`, and **retains the old release's cells** so
     rollback is lossless.
   - `analytics.analysis_cell` — the precomputed hex grid, PK
     `(release_id, cell_id)` so each release OWNS its grid and is a
     self-contained atomically-swappable unit (ADR-004). `geom` is the
     full H3 hexagon (used at request time to map a click to its cell
     via `ST_Contains` — keeps the runtime API H3-dependency-free,
     ADR-002); `centroid` is H3's canonical cell centre, stored for
     Phase 2 catchment math.
   The grid builder is `jobs/retailscout_jobs/features/grid.py`
   (`build_grid`), invoked via `cli.py build-grid` / `make build-grid`.
   **Resolution = H3 res 10**, chosen by benchmarking every candidate
   resolution against the REAL boundary (not a lookup table): res 8 →
   43 cells (~920m, too coarse), res 9 → 307 (~350m), **res 10 → 2,317
   (~130m, block-face scale, matches architecture.md's ~100-200m
   target)**, res 11 → 14,966 (~50m, needlessly fine). Verified against
   live PostGIS on the real municipality: 2,317 cells, **100.00%
   boundary coverage** (no interior gaps — every in-boundary click maps
   to a cell), 0 overlapping cell pairs (clean tiling), 0 cells failing
   the precise `ST_Intersects` prune, and the CBD golden control
   (Bourke St Mall) maps to exactly one cell whose stored `cell_id`
   equals `h3.latlng_to_cell` for that point — so the DB geometry and
   the H3 index agree. h3 only enumerates candidate cells + yields their
   geometry; ALL clipping is PostGIS (`ST_Intersects`), so
   shapely/geopandas are still not needed. See
   `jobs/tests/test_features_grid.py` (8 tests).
5. `0005` ✔ `analytics.location_feature` — the per-cell feature vector
   the scorer reads (invariant 5: no request-time spatial joins).
   **Deviates deliberately** from database-architecture.md's sketch,
   driven by real data:
   - Keyed `(release_id, cell_id, feature_version)` with an FK to
     `analysis_cell(release_id, cell_id)`, not the doc's
     `(cell_id, feature_version)` — a release owns its grid AND its
     features, so a release stays a self-contained atomically-swappable
     bundle (ADR-004). `feature_version` is retained as the
     product-facing version axis.
   - Business columns match REAL ANZSIC4 granularity: ANZSIC4 4511 is
     the COMBINED "Cafes and Restaurants" group (source cannot split
     café from restaurant — profiled, not assumed), so the column is
     `cafe_restaurant_400m`, not the doc's speculative separate
     cafes/restaurants.
   - **Scoped to the business/competition columns only** — the slice
     the first feature loader computes. Pedestrian/worker/development/
     transport/confidence columns are added by later migrations WITH
     their loaders (same "don't model a column before its loader"
     discipline as 0003); `location_feature` grows by
     `ALTER TABLE ADD COLUMN` per feature family.
   All feature columns nullable: NULL = "not computed for this
   generation", distinct from 0 = a real observed count (invariant 4).
   First feature loader: `jobs/retailscout_jobs/features/
   business_features.py` (`build_business_features`), via `cli.py
   build-features` / `make build-features`. Counts establishments per
   RetailScout taxonomy category within a 400 m geodesic catchment of
   each cell centroid (§9.3), using only the latest `census_year`
   snapshot (19,672 current rows, not the 413k all-years stack) and the
   versioned taxonomy (`jobs/registry/industry_taxonomy.yaml` — invariant
   8, resolved in Python, SQL only joins a plain code→category mapping).
   Verified against live PostGIS: the Bourke St Mall CBD cell shows 348
   café/restaurants, 200 takeaway, 69 bars, 728 retail, 641
   complementary within 400 m, and `cafe_restaurant_400m` matches an
   independent direct spatial query exactly. Uses an index-accelerated
   `&&`/`ST_Expand` bbox pre-filter before the exact geography
   `ST_DWithin` (22 s → 3.6 s on the full grid). 11 new tests (6 pure
   taxonomy-resolver + 5 DB integration; 56 total in jobs/, up from 45).
6. `0006` ✔ transport-access columns on `analytics.location_feature`
   (`tram_stops_400m`, `bus_stops_400m`, `train_stops_800m`) — the
   promised ALTER-per-feature-family growth (§14.2). Radii per §9.2:
   400 m local (tram/bus), 800 m wider (train). Loader
   `jobs/retailscout_jobs/features/transport_features.py`
   (`build_transport_features`) counts `core.transport_stop` by mode
   within radius of each cell centroid; same index-accelerated
   `&&`/`ST_Expand` pre-filter as the business loader. Columns named
   `*_stops_*` honestly (GTFS platform-level boardable stops, not
   distinct stations); regional_coach/skybus (3 each) not featured.
   `cli.py build-features` is now an orchestrator running the business
   THEN transport loaders in ONE transaction, each upserting a disjoint
   column set on the shared `(release_id, cell_id, feature_version)`
   row (order-independent). Verified against live PostGIS: Bourke St
   Mall cell = 19 tram / 5 bus (400 m), 28 train (800 m), matching an
   independent per-mode spatial count, with the business columns
   preserved through the compose. 4 new tests (60 total in jobs/, up
   from 56), placing fixture stops at exact geodesic distances
   (`ST_Project`) so the 400-vs-800 m radius split is tested precisely.
7. `0007` ✔ `core.clue_block` — the CLUE block geometry dimension
   (§16.2), added mid-Phase-2 as the prerequisite for worker-demand
   features: employment is reported per `block_id` with NO geometry, so
   the block polygons must exist before per-block jobs can be placed in
   space. Loader `jobs/retailscout_jobs/transform/clue_block.py`
   (GeoJSON→PostGIS, upsert on `block_id`), registered as `clue_blocks`.
   Real-data facts (profiled, 603 records): every `geo_shape` is a
   Polygon (never MultiPolygon → typed Polygon); `block_id` is a unique
   int natural key with no nulls, and ALL 603 `employment_by_block`
   block_ids are a subset of it (join verified for the next unit).
   Stores the source `geo_point_2d` as `centroid`. Verified against
   live PostGIS: 603 blocks, 0 invalid geometries. Two benign anomalies
   investigated, not ignored: 1 block centroid (501, West Melbourne
   Industrial) sits 14 m outside the municipal boundary (edge block —
   its POLYGON still intersects the boundary), and 6 centroids fall
   1–64 m outside their own polygon (concave/L-shaped blocks — a
   mathematical centroid, not a point-on-surface). Consequence for the
   worker-demand FEATURE: allocate jobs via polygon intersection, not by
   assuming a block centroid lies inside its block or the boundary.
   3 new tests (63 total in jobs/, up from 60).
8. `0008` ✔ `core.employment_block` — CLUE jobs per block per census
   year (§16.3 fact_employment_block_snapshot), the worker-demand fact.
   Loader `jobs/retailscout_jobs/transform/employment_block.py`
   (registered as `employment_by_block`), upsert on the natural key
   `(census_year, block_id)`. THE POINT OF THIS TABLE IS SUPPRESSION
   (invariant 4): an empty CSV cell = a suppressed count → NULL; "0" =
   an observed zero → 0; never conflated, and a suppressed total is
   never reconstructed by summing the (also partially-suppressed)
   industry columns. `total_jobs` is nullable — 133 of 603 blocks have
   a suppressed total in 2024, so the worker-demand feature must treat
   those as UNKNOWN, not zero. The 20 ANZSIC-division counts live in
   `jobs_by_industry jsonb` (JSON null vs 0 preserves the distinction —
   the development_project pattern), not 20 speculative columns. NO FK
   to `clue_block` (pedestrian_observation precedent — a hard FK to a
   current-snapshot dimension would break loading historical rows);
   block_id is indexed instead. Verified against live PostGIS: 13,519
   rows; 2024 `total_jobs` NULL=133 / =0 for 80 / >0 for 390 (matches
   the raw profile exactly); jsonb null-vs-0 preserved
   (`jsonb_typeof` = 'null' vs 'number'); all 603 2024 blocks join to
   `clue_block` with 520,544 known jobs (plausible CBD employment).
   3 new tests (66 total in jobs/, up from 63).
9. `0009` ✔ worker-demand columns on `analytics.location_feature`
   (`jobs_400m`, `jobs_800m`) — third feature family (§12). Loader
   `jobs/retailscout_jobs/features/worker_features.py`
   (`build_worker_features`), joined into the `build-features`
   orchestrator (business → transport → worker, one transaction).
   AREA-WEIGHTED allocation (§9.3): each cell's jobs =
   Σ over overlapping CLUE blocks of `total_jobs × (overlap_area /
   block_area)` — chosen over whole-block/centroid counting because
   blocks (~250 m) are large vs. the catchment and block centroids are
   unreliable (some outside their own polygon, found in 0007). Area
   ratio computed in EPSG:4326 (lon/lat distortion cancels in the
   ratio). SUPPRESSION preserved (invariant 4): suppressed blocks (NULL
   total) contribute nothing, and a catchment with NO known-job block
   yields NULL (unknown), never 0 — SUM over an empty filtered set is
   NULL. Verified against live PostGIS: 0 cells with jobs_400m > jobs_800m
   (monotonic), 22 NULL jobs_400m (uncovered), CBD cell 64,110 jobs
   within 400 m / 199,106 within 800 m; jobs_800m recomputed
   independently matched to the unit (199,106), with 8 suppressed blocks
   in that catchment correctly excluded. 5 new tests (71 total in jobs/,
   up from 66), incl. fully-contained (fraction 1), partial
   area-weighting (~4× between radii), suppressed→NULL, observed 0→0.
10. `0010` ✔ `analytics.sensor_daypart_baseline` — per-sensor
    foot-traffic baselines (§10.1-10.2), step 1 of pedestrian demand.
    Robust typical hourly counts (median headline + mean + p25/p75) per
    sensor × day type (weekday/saturday/sunday) × daypart
    (morning/lunch/afternoon/evening) over the trailing 12 months, plus
    n_observations / n_days for the confidence step. Loader
    `jobs/retailscout_jobs/features/pedestrian_baseline.py`
    (`build_sensor_baselines`), via `cli.py build-pedestrian-baselines`
    / `make build-ped-baselines`. Dayparts/day-types come from the
    versioned config (`jobs/registry/pedestrian_config.yaml` + typed
    `pedestrian_config.py`, invariant 8), resolved in Python and joined
    into SQL as arrays — never hard-coded. observed_at is UTC; dayparts
    are derived in LOCAL time (`AT TIME ZONE`), hours in no daypart
    (10:00, overnight) excluded. Standalone aggregate keyed by
    `baseline_version` (config version), NOT grid-release-scoped; NO FK
    to pedestrian_sensor (orphan sensor_ids exist — same precedent as
    pedestrian_observation). Verified against live PostGIS: 1,224 rows
    (102 sensors × 3 × 4); 0 percentile-ordering violations; the busiest
    weekday-lunch sensor is Swanston St (median 3,101/hr — the real
    busiest CBD corridor), with a realistic weekday-lunch vs.
    Saturday-afternoon peak and complete coverage (~259 weekdays / ~51
    weekend days). 7 new tests (78 total in jobs/, up from 71). NEXT
    (step 2): distance-decay interpolation of these baselines to grid
    cells + a separate foot-traffic confidence value (§10.3-10.4).
11. `0011` ✔ `analytics.cell_pedestrian_daypart` — interpolated foot
    traffic per cell (§10.3-10.4), step 2 of pedestrian demand. Narrow
    table (row per release × cell × day_type × daypart), release-scoped
    (FK to analysis_cell). Loader
    `jobs/retailscout_jobs/features/pedestrian_features.py`
    (`build_pedestrian_features`), via `cli.py build-pedestrian-features`
    / `make build-ped-features` (needs `build-pedestrian-baselines`
    first). Distance-decay weighted mean of nearby sensor baseline
    medians: `weight = exp(-dist/decay)`, geodesic distance (network
    distance deferred → labelled modelled/approximate, NEVER observed
    footfall). Interpolation params + confidence thresholds in the
    versioned config (`pedestrian_config.yaml`). Foot-traffic confidence
    (§10.4) stored SEPARATELY from the estimate: no sensor in range →
    'insufficient' (no row); else high/medium/low by nearest-sensor
    distance + count. Verified against live PostGIS: 9,948 rows across
    829 cells (the other ~1,488 legitimately insufficient — the sensor
    net is CBD-focused, ~61% of the municipality is beyond 650 m of any
    sensor); weekday-lunch confidence high 320 / medium 311 / low 198;
    Bourke St Mall weekday-lunch estimate 1,410/hr (high confidence,
    nearest sensor 30 m), correctly a distance-weighted blend inside the
    nearby sensors' [31, 3101] median range. 7 new tests (85 total in
    jobs/, up from 78): exact decay weighting, each confidence band,
    insufficient→no row, unlocated-sensor exclusion.
12. `0012` ✔ `analytics.location_score` — the scoring engine's output
    (§15), deterministic and versioned (ADR-003, no ML). Keyed
    `(release_id, cell_id, business_profile, score_version)` with an FK
    to `analysis_cell` (established deviation from the doc's
    `(cell_id, business_profile, score_version)` — a release owns its
    scores too, ADR-004). Stores every component score
    (`foot_traffic`/`worker_demand`/`competition`/`transport`/
    `development`), `total_score`, and a `confidence_score` kept
    SEPARATE from suitability (§15.3), plus an API-shaped `explanation`
    jsonb matching §17.3's response contract (component key/score/
    weight/evidence + confidence band/reasons) so the runtime API
    serves evidence with zero recomputation (invariant 5, 6).
    `development_score` was always NULL at v1 (no growth-pipeline
    feature yet, reweighted out of every score, invariant 4) — live
    since `0013`/score_version v2.

    Method, in `jobs/retailscout_jobs/scoring/score.py`
    (`build_scores`), via `cli.py build-scores` / `make build-scores`
    (needs grid + all feature loaders + pedestrian baselines/features
    run first): one raw metric per component (weekday pedestrian
    estimate; `jobs_800m`; café+takeaway competitor count; total transit
    stops), each normalised to a robust WITHIN-CITY 0-100 percentile via
    `percent_rank()` (§15.2) — competition is INVERTED (fewer nearby
    competitors scores higher; a v1 simplification, §11.2's
    cluster-strength nuance deferred). Weighted per business profile
    (`jobs/registry/score_profiles.yaml`, invariant 8 — 4 profiles,
    weights sum to 100, starting hypotheses per §15.4, not yet
    golden-location-validated) and averaged over PRESENT components
    only: a missing component (development always; foot_traffic where
    pedestrian data is insufficient) is reweighted out of numerator AND
    denominator (§15.5), never treated as 0 — verified directly (see
    below), this is the single most important correctness property of
    the engine. Confidence score comes from the cell's weekday/lunch
    foot-traffic confidence band via a versioned lookup
    (`confidence_scores` in the same config).

    Verified against live PostGIS: 9,268 rows (2,317 cells × 4
    profiles), 0 out-of-[0,100] scores. Cross-checked against every
    `tests/golden_locations/golden_locations.yaml` control point — ranks
    correctly end to end: Bourke St Mall/Degraves St/Flinders St
    (expect very_high) scored 77.6/76.6/74.6; QVM/Southbank (expect
    high) 65.9/74.6; Lygon St/Parkville (expect medium) 55.7/49.7; Royal
    Botanic edge/West Melbourne residential (expect low) 38.1/46.6; the
    outside-boundary control correctly has NO containing cell. Bourke St
    Mall's own breakdown demonstrates the model working as intended, not
    just producing a plausible number: foot traffic 99.6, workers 99.6,
    transport 98.4, but competition 0.0 (548 café/takeaway competitors
    within 400 m — the most saturated market in the city), for a total
    of 77.2 — high but not maximal, correctly reflecting real saturation
    risk rather than only rewarding raw activity. Hit and fixed the same
    Postgres typing gotcha as 0011 (`round(double precision, n)` doesn't
    exist; cast to `::numeric`). 9 new tests (94 total in jobs/, up from
    85): a hand-built 4-cell synthetic release with exact expected
    percentiles proves the reweighting-not-zeroing property precisely,
    confirms competition inversion, per-profile weight divergence, and
    the API-shaped explanation structure.
13. `0013` ✔ development-pipeline columns on
    `analytics.location_feature` (§13): `dev_pipeline_people_800m`
    (status- and distance-weighted "people equivalents" of the pipeline
    within 800 m of the cell centroid) + `dev_projects_800m` (plain
    project count, the evidence number). Every §13 factor —
    status-probability (APPLIED 0.3 → COMPLETED 1.0), people-equivalent
    coefficients (dwellings/office m²/retail m²/hotel rooms/student
    beds), 800 m linear decay, and `completed_since_year` — lives in
    `jobs/registry/development_config.yaml` (invariant 8, "factors must
    be configuration, not hidden constants"), typed-loaded by
    `development_config.py`. COMPLETED projects only count if finished
    after the CLUE census year (2024): older completions are already in
    the observed stock (their workers in `employment_block`) — counting
    them again would double-count the present as the future. NULL
    semantics deliberately differ from `jobs_800m`: the source has no
    suppression and full geometry (0 of 1,438 rows lack coordinates), so
    an empty catchment is a real 0, and NULL only means "not computed".
    An unknown status in the data fails the build loudly rather than
    silently zeroing pipeline.

    Method in `features/development_features.py` (part of
    `make build-features`); scoring wired in as score_version v2 —
    development percentile joins the weighted mean, and the explanation
    carries `pipeline_people_800m`/`pipeline_projects_800m` evidence.
    Verified against live PostGIS: 2,317 cells, 350 fringe cells at an
    observed 0, max ≈18k people-equivalents (Southbank/CBD north);
    Bourke St Mall café total moved 77.2 → 78.8 with development 93.4
    (10,662 people-equiv across 75 projects); golden-location ordering
    unchanged. 10 new tests (104 total in jobs/): exact ST_Project
    decay/status math, multi-field scale sums, old-completions-are-stock,
    observed-zero-not-NULL, unknown-status failure; the 4-cell synthetic
    scoring test now exercises §15.5 reweighting for development (cell C
    has NULL dev) alongside foot traffic.
14. `0014` — `app` schema: `project`, `saved_location`.
15. `0015` — `audit` schema: `score_request`, `data_quality_result`.
