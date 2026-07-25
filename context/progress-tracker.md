# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- Phase 2 (feature/scoring engine) is UNDERWAY. Phase 1 (data
  foundation) and the Phase 1→2 bridge (hex grid, `0004`) are complete.
  The first `location_feature` slice — business/competition features
  (`0005`) — is now live: `analytics.location_feature` exists and its
  business columns are computed for all 2,317 grid cells against real
  data. Remaining Phase 2 work: the other feature families (pedestrian
  demand, worker demand, development, transport, confidence), then the
  scoring engine (`location_score`) and golden-location evaluation.

## Current Goal

- Worker-demand features (CLUE jobs-by-block). The two core
  prerequisites are DONE: (a1) `core.clue_block` geometry (0007) and
  (a2) `core.employment_block` jobs (0008) — both live and verified.
  Next: (b) the worker-demand FEATURE — `ALTER location_feature ADD
  jobs_400m/jobs_800m` + a `worker_features` loader allocating latest-
  year block job totals to cells by POLYGON intersection (§9.3), joined
  into the build-features orchestrator. Must preserve suppression: a
  block with NULL total_jobs contributes unknown, not 0 (a cell whose
  catchment blocks are all suppressed should read NULL, not 0). After
  worker demand: pedestrian demand (§10, biggest unit), then the
  scoring engine.

## Completed

- Context files established (2026-07-25): `project-overview.md`,
  `architecture.md`, `ui-context.md`, `code-standards.md`,
  `ai-workflow-rules.md`, `progress-tracker.md`, synthesized from
  `retailscout-city-of-melbourne-architecture.md`,
  `vercel-template.md`, and `database-architecture.md`.
- Phase 0 data validation (2026-07-25): live-queried the City of
  Melbourne Explore v2.1 API (`/catalog/datasets/{id}` +
  `/records`) for all 12 datasets in the architecture doc's source
  table, plus follow-up catalog search for boundary/transport-stop
  datasets not given concrete IDs. Full raw metadata/sample JSON
  saved to scratch (not in repo) — see findings below. Now encoded as
  the committed source registry (`jobs/registry/sources.yaml`).
- Repository scaffold (2026-07-25), all pieces run-verified locally:
  - Monorepo layout per `architecture.md`; git initialized (no
    commits yet). Root `README.md` is the entry map; `Makefile` has
    all dev targets.
  - `infrastructure/docker-compose.yml`: PostGIS 17-3.5. NOTE: local
    image is `imresamu/postgis:17-3.5` (official `postgis/postgis`
    has no arm64 manifests → fails on Apple Silicon); CI uses the
    official image. Keep version pins in lockstep.
  - `db/`: Alembic wired (direct URL only); migration `0001` creates
    `postgis` + `pg_trgm` and the six schemas. **Applied and verified
    against the running container.** `db/README.md` contains the
    numbered migration roadmap (0002–0006) with reference DDL
    pointers.
  - `jobs/`: `sources.yaml` registry (17 sources, statuses
    active/blocked/unvalidated, observed field lists, fetch modes) +
    typed loader (`registry.py`), OpenDataSoft client with the
    confirmed limits as constants (`opendatasoft.py`), immutable
    snapshot writer with checksummed manifests (`snapshot.py`), CLI
    (`list|ingest|freshness`). 9 unit tests pass. **Real ingest
    verified**: `pedestrian_sensor_locations` downloaded and
    snapshotted with manifest; blocked `transport_activity` correctly
    refused (exit 2).
  - `backend/`: FastAPI app with routers→services→repositories→schemas
    layering, NullPool engine, CORS for local dev, `/api/v1/health`,
    and `/api/v1/locations/score` published as a 501 stub with the
    full `ScoreResponse` contract (§17.3) in OpenAPI. 4 tests pass;
    ruff clean.
  - `frontend/`: Next.js 15 + Tailwind v4; `globals.css` carries the
    ui-context design tokens (score vs confidence palettes separated);
    dev rewrite proxies `/api/v1/*` to FastAPI. Typecheck + production
    build pass.
  - `contracts/`: `make contracts` exports `openapi.json` and
    generates `frontend/lib/api/schema.ts` (openapi-typescript) —
    **generated and typechecked** with `ScoreResponse` present.
  - `tests/golden_locations/golden_locations.yaml`: 12 starter
    locations incl. low-activity controls and an outside-boundary
    FR-02 rejection case. `version: 0` — coordinates approximate,
    expectations qualitative; must be validated in Phase 2.
  - `.github/workflows/ci.yml`: backend/jobs (uv+ruff+pytest),
    frontend (npm ci+typecheck+build), and a migrations job against a
    real PostGIS service container.
  - First commit made 2026-07-25 (`9c3c5fb`), 64 files.
- Migration `0002` — source provenance (2026-07-25): `source.dataset`
  (registry mirror, upserted every run), `source.dataset_release`
  (`UNIQUE (dataset_id, object_path)` — same-day re-ingests upsert,
  never duplicate), `source.dataset_release_file` (per-file checksums;
  handles the multi-file manual-adopt case), `source.ingestion_run`.
  `jobs/retailscout_jobs/{db,provenance}.py` added; `cli.py
  ingest`/`adopt` now call `_record_provenance` after every successful
  snapshot. Deviates from the original single-table sketch in
  `database-architecture.md` to support multi-file manifests — see
  `db/README.md` roadmap entry for the full rationale.
  **Verified against live PostGIS, not just applied**: real
  `pedestrian_sensor_locations`, `transport_activity` (adopt), and
  `ptv_gtfs` snapshots all have `source.dataset_release` rows;
  idempotent re-ingest confirmed (same release_id, no duplicate rows,
  file rows replaced wholesale). `jobs/tests/test_provenance.py` adds
  4 DB-backed tests (16 total in jobs/, up from 13), each in a rolled-
  back transaction using a fictional sentinel date (2099-01-01) so
  tests never collide with real same-day CLI usage on a shared dev
  database — an actual collision during this work (test used "today"
  as its date and matched real rows via the `(dataset_id, object_path)`
  unique key) is why that pattern is now load-bearing, not decorative.
  CI: `jobs-worker` job gained its own postgres service + migration
  step so these tests run in CI, not just locally.
- Full bulk ingest (2026-07-25): every `status: active` source in
  the registry now has a real raw snapshot with recorded provenance —
  all 13 active sources plus the `manual`-status `transport_activity`
  archives (14 total `source.dataset_release` rows). Total ~720 MB
  across `data/raw/` (largest: `ptv_gtfs` 273 MB, `transport_activity`
  211 MB, `pedestrian_hourly` 117 MB, `business_establishments` 75 MB).
  Caught and fixed a gap in the process along the way:
  `pedestrian_hourly` — the largest and most important dataset — had
  only ever been sample-queried during Phase 0 validation, never
  actually ingested; it was missing from both the "done" and "still
  pending" lists in this file's previous revision. Cross-checked the
  full registry's `ingestable()` set against `source.dataset_release`
  after this run to confirm no other source was silently skipped.
- Migration `0003` — `core` schema + first loader (2026-07-25): all 6
  core tables created (`municipal_boundary`, `pedestrian_sensor`,
  `pedestrian_observation`, `business_establishment`,
  `development_project`, `transport_stop`); column types informed by
  inspecting the real raw snapshots, not guessed (e.g. confirmed
  `geo_shape` geometry is `MultiPolygon` before writing the DDL).
  Built and verified the first staging→core loader,
  `transform/municipal_boundary.py` (via PostGIS's
  `ST_GeomFromGeoJSON`, no geopandas/shapely needed for this one):
  loaded geometry has the correct real area (37.66 km² — matches the
  actual City of Melbourne), and `ST_Contains` correctly includes
  Bourke Street Mall and excludes the Richmond golden-location control
  point, i.e. **FR-02's boundary check is now backed by real, verified
  data**, not just a schema. `jobs/tests/test_transform_municipal_boundary.py`
  adds 3 tests (19 total in jobs/, up from 16); idempotent re-load
  confirmed both manually and by test.
  Discovered and documented in `jobs/registry/sources.yaml`: every CSV
  export from this provider is **semicolon-delimited with a UTF-8
  BOM** (not comma) — undocumented by OpenDataSoft, found by opening
  the actual files. Also documented for the next loader unit:
  `pedestrian_hourly`'s `id` column is a synthetic composite
  (location_id+hourday+date), not a stable key — must build
  `observed_at` from `sensing_date`+`hourday` instead.
  Remaining core loaders (`pedestrian_sensor_locations`,
  `pedestrian_hourly`, `business_establishments`,
  `development_activity`, GTFS `stops.txt`) are deliberately separate
  future units — see `db/README.md`'s roadmap entry for ordering and
  per-source gotchas.
- Loader: `pedestrian_sensor_locations` → `core.pedestrian_sensor`
  (2026-07-25): all 134 real sensors loaded and verified — nullable
  fields match the real data exactly (1 null `installed_at`, 34 null
  direction labels, confirmed by inspection before writing the loader,
  not discovered by trial and error), idempotent re-load confirmed,
  and a cross-table sanity check (`ST_Contains` against
  `core.municipal_boundary`) confirms **all 134 sensors fall inside
  the loaded boundary** — the two loaders built so far agree with each
  other, which is a stronger signal than either being independently
  plausible. Deliberately does not track sensor-location history
  (always upserts to the latest known position); a period/validity
  table for relocated sensors is scoped out until `pedestrian_hourly`
  makes that gap actually matter. 2 new tests (21 total in jobs/, up
  from 19), including one that proves upsert semantics by mutating a
  fixture's status between two loads and checking the change actually
  took effect (not just that the row count stayed put).
- Loader: `pedestrian_hourly` → `core.pedestrian_observation`
  (2026-07-25) — the biggest and riskiest core loader, fully loaded:
  all 1,610,006 rows, ~19s end to end (measured). Profiled the FULL
  file (not a sample) before writing any code: zero duplicate
  `(location_id, sensing_date, hourday)` keys (confirms the PK
  choice), no nulls or negatives in any column used, and — the most
  important finding — **3 real orphan sensor_ids (28, 65, 78)** appear
  in this data but not in the currently-loaded 134-sensor snapshot,
  empirically confirming (not just theoretically justifying) migration
  0003's decision to skip a FK from `pedestrian_observation` to
  `pedestrian_sensor`. Timezone handling (local `Australia/Melbourne`
  hour → UTC via `zoneinfo`) was checked against all 4 real DST
  transition dates in the file's range before trusting it: spring-
  forward dates never emit the nonexistent local hour (source already
  omits it), fall-back dates emit the ambiguous hour exactly once per
  sensor (source already collapsed it) — so the theoretical PK-
  collision risk from DST does not materialize in practice. Round-trip
  verified against a known real row (sensor 109, 2025-01-21 14:00
  local → 03:00 UTC, count 214) and orphan-sensor rows loaded
  correctly. Idempotent re-load of the full 1.6M rows confirmed. 4 new
  tests (25 total in jobs/, up from 21).
  All 3 foot-traffic-critical loaders (boundary, sensors, hourly
  observations) are now done and cross-verified — Phase 2's pedestrian
  demand methodology has real data to work against whenever it starts.
- Loaders: `business_establishments` → `core.business_establishment`
  and `development_activity` → `core.development_project`
  (2026-07-25) — all 413,550 and 1,438 real rows loaded respectively.
  Profiling before writing either loader confirmed a real difference
  between the two sources: `business_establishments` genuinely has NO
  stable natural key (8,344 candidate-key groups have >1 row), while
  `development_activity`'s `development_key` IS confirmed globally
  unique. Both loaders use delete-by-`source_release_id`-then-reinsert
  regardless (documented per-loader why — for developments it matches
  the source's own monthly full-refresh cadence rather than being a
  fallback). Hit and fixed a real bug while building the first of the
  two: SQLAlchemy's batched multi-row INSERT does not correctly scope
  a bind parameter referenced twice inside a `CASE WHEN` per row
  (`AmbiguousParameter`, then silently wrong values, discovered
  against the real 413k-row file, not a small fixture) — fixed by
  computing WKT geometry in Python and relying on
  `ST_GeomFromText(NULL) IS NULL` instead of branching in SQL; the
  fixed pattern was reused for `development_project` and future
  loaders should default to it rather than a SQL-side `CASE`.
  `development_project`'s ~30 wide numeric attribute columns are
  stored in `raw_attributes jsonb` as real JSON numbers, confirmed
  decimal-free across the whole file first. 8 new tests (32 total in
  jobs/, up from 25).
- Loader: PTV GTFS `stops.txt` → `core.transport_stop` (2026-07-25) —
  the last of the six core loaders, and the most structurally
  complex: the archive is a zip of numbered mode-folders, each holding
  its own inner `google_transit.zip`. Determined which folder is which
  transport mode by inspecting each real bundle's `routes.txt`
  `route_type` + actual route names (documented per-folder in the
  loader's docstring — e.g. folder 10 is "The Overland" at
  `route_type=102`), since `agency.txt` is uninformative (always just
  "Transport Victoria"). Filtered statewide's ~31,973 stops down to
  1,300 real stops: boardable stop/platform records only (excludes
  station/entrance/generic-node rows), within `core.municipal_boundary`
  + 1km (Python bbox pre-filter + precise `ST_DWithin` SQL prune — 0
  rows failed the precise check afterward, confirming the design).
  Found and explained a real, non-obvious empirical fact rather than
  guessing at it: a stop_id CAN repeat across mode bundles — ALL 60
  real regional-train stops in range share identical stop_ids with
  metro-train stops (same physical platforms at Flinders St, Southern
  Cross, etc.), which is why `regional_train` shows 0 rows in the
  final loaded set even though 220 candidate rows existed pre-filter —
  not a bug, a deterministic and now-tested consequence of the
  documented bundle-processing order (rail modes processed last, so
  they win any collision, matching this product's CBD-focused scope).
  5 new tests (37 total in jobs/, up from 32), including one that
  specifically proves the collision-resolution order.
  **All six core loaders defined in migration 0003 are now implemented
  and verified against real data.** Cross-checks hold across the whole
  set: 134 sensors and 1,300 transport stops both confirmed inside the
  loaded municipal boundary.
- Migration `0004` + hex analysis grid (2026-07-25) — the Phase 1→2
  bridge. Added the `analytics` schema's atomic-release machinery
  (`data_release`, singleton `active_release` pointer) and the
  precomputed hex grid (`analysis_cell`), plus the grid builder
  `jobs/retailscout_jobs/features/grid.py` (`build_grid`, wired via
  `cli.py build-grid` / `make build-grid`). First `features/` module —
  distinct from `transform/` (raw→core); it computes a derived
  analytics artifact from already-loaded `core.*` data and publishes it
  as a versioned release. Deliberately scoped 0004 to the grid +
  release pointer only, deferring `location_feature`/`location_score`
  to `0005` (with their Phase 2 loaders) rather than modelling them
  before the scoring methodology exists — same "don't speculatively
  model" discipline as 0003.
  **Resolution question (previously open) is settled empirically**: H3
  res 10, chosen by benchmarking every candidate against the REAL
  37.66 km² boundary — res 8→43 cells (~920m, too coarse), res 9→307
  (~350m), res 10→2,317 (~130m, block-face scale, lands in
  architecture.md's ~100-200m target), res 11→14,966 (~50m, needlessly
  fine). Resolution is a parameter recorded per `data_release`, so a
  future release can change it without a schema or code change.
  Verified against live PostGIS on the real municipality (not just a
  fixture): 2,317 cells, **100.00% boundary coverage** (union of hexes
  fully covers the boundary — no interior gap where an in-boundary
  click could hit no cell), 0 overlapping cell pairs (clean tiling), 0
  cells failing the precise `ST_Intersects` prune, and the CBD golden
  control (Bourke St Mall) maps to exactly one cell whose stored
  `cell_id` equals `h3.latlng_to_cell` for that point (DB geometry and
  H3 index agree — so the runtime API can map a click via `ST_Contains`
  and stay H3-dependency-free, ADR-002). Out-of-boundary control
  (Richmond) maps to zero cells, consistent with FR-02. Atomic release
  swap verified: a second `build-grid` flips `active_release`, marks
  the prior release `superseded`, and retains the old release's cells
  so rollback is lossless (invariant 3). h3 only enumerates candidate
  cells + yields geometry; ALL clipping is PostGIS, so
  shapely/geopandas are STILL not in `jobs/pyproject.toml` — only `h3`
  was added. 8 new tests (45 total in jobs/, up from 37). Note: the
  dev DB now holds two grid releases (#1 superseded, #2 active) from
  the manual verification runs — expected release-history state, not
  cruft to clean.
- Migration `0005` + first Phase 2 feature loader:
  business/competition features (2026-07-25). Created
  `analytics.location_feature` (per-cell feature vector, scoped to the
  business columns this loader fills — see db/README for the deviations
  from the doc's sketch) and
  `jobs/retailscout_jobs/features/business_features.py`, wired via
  `cli.py build-features` / `make build-features`. Profiled the real
  ANZSIC4 data FIRST and it changed the design in two concrete ways:
  (1) the current business snapshot is the LATEST `census_year` (2024,
  19,672 rows), NOT the full 413k all-years stack — counting all years
  would multiply-count a tenancy; (2) ANZSIC4 `4511` is a COMBINED
  "Cafes and Restaurants" group, so the doc's separate
  cafes/restaurants columns are impossible — the column is
  `cafe_restaurant_400m`. Also excludes `0000 Vacant Space` (5,335
  rows — not a business). Introduced the versioned industry taxonomy
  (`jobs/registry/industry_taxonomy.yaml` + typed
  `retailscout_jobs/taxonomy.py`, invariant 8): ANZSIC4→category mapping
  resolved in Python, SQL only joins a plain code→category mapping —
  never hard-coded in SQL. Verified against live PostGIS: Bourke St
  Mall CBD cell = 348 café/restaurants, 200 takeaway, 69 bars, 728
  retail, 641 complementary within 400m; `cafe_restaurant_400m` matched
  an independent direct spatial query exactly. Every cell gets a real
  count (0 where none in range, never NULL — invariant 4). Catchment is
  a geodesic `ST_DWithin` on geography (labelled approximate; §9.2's
  pedestrian-network distance deferred). Hit and fixed a real perf
  issue found by measuring, not guessing: the geography cast bypassed
  the geometry GiST index (22s); added an index-accelerated
  `&&`/`ST_Expand` bbox pre-filter before the exact geography check →
  3.6s, identical counts. First `features/` loader to touch `core.*` +
  `analytics.*` together. 11 new tests (6 pure taxonomy-resolver + 5 DB
  integration using a fictional `census_year=2099` sentinel to isolate
  from the real 413k rows without deleting them; 56 total in jobs/, up
  from 45).
- Migration `0006` + transport-access features (2026-07-25) — second
  Phase 2 feature family, and proof of the ALTER-per-family growth
  pattern promised in 0005. `ALTER TABLE analytics.location_feature ADD
  COLUMN tram_stops_400m / bus_stops_400m / train_stops_800m`, plus
  `jobs/retailscout_jobs/features/transport_features.py`. Counts
  `core.transport_stop` (1,300 GTFS stops) by mode within §9.2 radii:
  400 m local (tram/bus), 800 m wider (train — draws from further).
  Columns named `*_stops_*` honestly: these are GTFS platform-level
  boardable stops, not distinct stations (core.transport_stop dropped
  station-grouping rows); regional_coach/skybus (3 each, niche) not
  featured. `cli.py build-features` refactored into an ORCHESTRATOR:
  runs the business then transport loaders in ONE transaction, each
  upserting a disjoint column set on the shared
  `(release_id, cell_id, feature_version)` row, so they compose in any
  order and the whole feature vector for a release is built atomically.
  Verified against live PostGIS: Bourke St Mall cell = 19 tram / 5 bus
  within 400 m, 28 train within 800 m — matching an independent
  per-mode spatial count exactly, with the business columns preserved
  through the compose; every cell got a real 0-or-more count (never
  NULL). 4 new tests (60 total in jobs/, up from 56), which place
  fixture stops at EXACT geodesic distances from the real cell centroid
  (`ST_Project`) so the 400-vs-800 m radius split is tested precisely,
  not approximately. Caught and fixed a real test bug: initially passed
  the analytics `grid.release_id` as `transport_stop.source_release_id`
  (different sequences — FK violation); the fixture now threads the
  `source.dataset_release` id separately from the analytics
  `data_release` id.
- Migration `0007` + `core.clue_block` loader (2026-07-25) — first
  sub-unit of worker-demand: the CLUE block geometry dimension, a
  prerequisite because employment is reported per `block_id` with NO
  geometry of its own (can't place jobs in space without the block
  polygons). Loader `transform/clue_block.py` (GeoJSON→PostGIS via
  ST_GeomFromGeoJSON/ST_MakePoint, upsert on `block_id`), registered as
  `clue_blocks` in LOADERS. Profiled the real snapshot first (603
  records): all Polygon (never MultiPolygon), `block_id` a unique int
  natural key with no nulls, and confirmed ALL 603
  `employment_by_block` block_ids (23 census years 2002–2024) are a
  subset of clue_blocks — the next unit's join is safe. Verified
  against live PostGIS: 603 blocks, 0 invalid geometries. Investigated
  (not ignored) two anomalies, both benign: 1 centroid (block 501)
  14 m outside the boundary — an edge block whose polygon still
  intersects the boundary; 6 centroids 1–64 m outside their own
  polygon — concave/L-shaped blocks (a mathematical centroid isn't a
  point-on-surface). Recorded the consequence for the worker-demand
  feature: allocate jobs by polygon intersection, NOT by assuming a
  block centroid lies in its block or the boundary. 3 new tests (63
  total in jobs/, up from 60).
- Migration `0008` + `core.employment_block` loader (2026-07-25) —
  second worker-demand prerequisite: CLUE jobs per block per census
  year (the worker-demand fact). Loader `transform/employment_block.py`
  (registered `employment_by_block`), upsert on natural key
  `(census_year, block_id)`. Profiled first: 13,519 rows, PK unique,
  all values integers. THE point of the table is suppression: an empty
  cell = suppressed → NULL, "0" = observed zero → 0, never conflated
  (invariant 4) — and even `total_jobs` is suppressed for 133 of 603
  blocks in 2024, so it is nullable and the worker-demand feature must
  treat those as UNKNOWN not zero (and never reconstruct a suppressed
  total by summing the also-suppressed industry columns, per the
  registry note). The 20 ANZSIC-division counts live in
  `jobs_by_industry jsonb` (JSON null vs 0 preserves suppression — the
  development_project pattern), not 20 speculative columns. NO FK to
  `clue_block` (pedestrian_observation precedent). Verified against
  live PostGIS: 13,519 rows; 2024 `total_jobs` NULL=133 (matches the
  raw profile exactly) / =0 for 80 / >0 for 390; jsonb null-vs-0
  preserved (`jsonb_typeof` 'null' vs 'number'); all 603 2024 blocks
  join to `clue_block` with 520,544 known jobs. Both worker-demand core
  prerequisites (geometry + jobs) are now in place; the feature is next.
  3 new tests (66 total in jobs/, up from 63).

### Data validation findings

All 12 required dataset IDs from the architecture doc resolve
(HTTP 200) against
`https://data.melbourne.vic.gov.au/api/explore/v2.1/catalog/datasets/{id}`.
Key confirmations and discrepancies vs. the architecture doc:

- **Confirmed / better than documented**: pedestrian hourly counts
  (`pedestrian-counting-system-monthly-counts-per-hour`) actually
  contains `sensing_date` values through **2026-07-24** (yesterday) —
  the dataset's own `modified` metadata timestamp (2024-08-14) is
  stale and must not be used as a freshness signal; use `MAX(sensing_date)`
  from the data itself instead. 1,610,006 rows total.
- **Confirmed**: CLUE-derived datasets (business establishments,
  café seating, employment-by-block, establishments-per-block) all
  contain `census_year = "2024"` records as the max year, matching
  the doc's claim, despite their `modified` metadata also showing a
  stale 2021-11-02 timestamp — same caveat as above applies.
- **Confirmed**: employment-by-block-by-clue-industry genuinely
  distinguishes `null` (suppressed) from `0` (observed zero) per
  industry column in the raw API response — validates the
  "missing is not zero" invariant in `architecture.md` at the source
  level, not just as a design aspiration.
- **PARTIALLY RESOLVED — transport-activity-counts API is empty, but
  historical bulk archives are in hand**: the live API serves zero
  rows on every variant (records, exports, count(*)) and remains
  unusable for scheduled ingestion. However, operator-downloaded
  yearly bulk archives (TransportActivityCount_2023..2026.zip,
  retrieved 2026-05-11, ~3.4 GB CSV) cover 2023-01 through
  2026-05-11 and were adopted into the raw snapshot layout on
  2026-07-25 via the new `cli adopt` command (source status:
  `manual`). Profiled: 5-minute intervals, 14 road-user classes
  (pedestrian/cyclist/escooter/car/bus/…), lat/long per count
  location. Caveats encoded in `sources.yaml`: bulk CSV schema
  differs from the API metadata (no countin/countout, different
  casing, extra year/quarter); timestamps are **UTC** and must be
  converted to Australia/Melbourne before daypart derivation; the
  archive is frozen at 2026-05-11 so the "current activity" layer
  stays deferred, but historical multimodal features are unblocked.
- **RISK — pedestrian hourly counts has no licence set**: unlike
  every other dataset checked (all return `"license": "CC BY"`),
  `pedestrian-counting-system-monthly-counts-per-hour` returns
  `"license": null, "license_url": null`. This is RetailScout's most
  heavily used dataset (foot-traffic scoring). The architecture doc's
  blanket "all datasets are CC BY" claim (§19.3) does not hold for
  this one via the API — needs manual verification against the
  dataset's portal page before publishing an attribution/licence
  register.
- **Gap in the doc — dataset IDs not specified, now resolved**:
  - Municipal boundary (needed for FR-02): `municipal-boundary`
    (CC BY, 1 record, polygon geometry — confirms a usable boundary
    source exists).
  - "Various" bus/tram sources (§4.1, §14.2) resolve to:
    `bus-stops`, `tram-tracks`, `city-circle-tram-route`,
    `city-circle-tram-stops`.
- **API constraints confirmed (Explore v2.1)**: City of Melbourne
  directs integrators to the OpenDataSoft Explore v2.1 reference
  (https://help.opendatasoft.com/apis/ods-explore-v2/explore_v2.1.html).
  Empirically verified against the live API: the `/records` endpoint
  caps `limit` at **100** and `offset` at **<10000**
  (`InvalidRESTParameterError` past either) — so only ~10k rows are
  reachable via pagination. The `/exports/{json,csv}` endpoint is
  uncapped and is the required path for bulk-ingesting the large
  datasets (pedestrian hourly ~1.6M rows, business establishments
  ~413k rows). The source registry / ingestion jobs must therefore
  use `fetch_mode: export` for those, records-API pagination only for
  small dimension tables and incremental/metadata checks.

- PTV GTFS adopted as the transport source (2026-07-25):
  - Registry extended: `deferred` status, `http_file` fetch mode with
    per-source `provider`/`attribution`/`download_url` overrides,
    `http_header` freshness strategy (validated at the model level).
  - `ptv_gtfs` entry added (provider `transport_victoria`,
    `https://data.ptv.vic.gov.au/downloads/gtfs.zip`); the four
    council transport proxies marked `deferred` with supersession
    notes. 13 jobs tests pass.
  - **Real ingest verified**: 286 MB zip snapshotted to
    `data/raw/transport_victoria/ptv_gtfs/retrieved_date=2026-07-25/`
    (Last-Modified upstream: 2026-07-23 — actively maintained).
    Structure confirmed: nested numbered mode folders (2=metro train,
    3=metro tram, 4=metro bus, …) each containing `google_transit.zip`
    with standard GTFS files; stops carry lat/lon +
    `wheelchair_boarding`; `agency_timezone` is Australia/Melbourne.
  - Transform-stage notes encoded in `sources.yaml`: unpack two zip
    levels, filter stops to municipal boundary + ~1 km buffer, stream
    `stop_times.txt`, derive departures-by-daypart from
    stop_times × calendar.

## In Progress

- None yet.

## Next Up

Each item is one unit of work (ai-workflow-rules.md). In order:

1. Manually verify the remaining source blocker: pedestrian
   hourly-counts licence (portal page / council contact). Update
   `sources.yaml` when answered. (Transport archives: resolved via
   adopt; only the live-feed question remains open.) — deprioritized
   per user 2026-07-25, revisit before beta/attribution work.
2. ~~Generate the analysis hex grid~~ **DONE 2026-07-25** — migration
   0004 + `features/grid.py`, H3 res 10, 2,317 real cells published as
   an atomic `analytics.data_release` (see Completed).
3. ~~Start Phase 2 feature-building~~ **STARTED 2026-07-25** — migration
   0005 `analytics.location_feature` + `features/business_features.py`
   (business/competition columns, all 2,317 cells) + the versioned
   industry taxonomy (see Completed).
4. ~~Transport-access features~~ **DONE 2026-07-25** — migration 0006 +
   `features/transport_features.py`, build-features now orchestrates
   business + transport (see Completed).
5. Worker-demand features (CLUE jobs-by-block), continued:
   - ~~(a1) `core.clue_block` geometry~~ **DONE 2026-07-25** (0007).
   - ~~(a2) `core.employment_block` jobs~~ **DONE 2026-07-25** (0008).
   - (b) worker-demand feature columns (`jobs_400m`, `jobs_800m`)
     allocating latest-year block job totals to cells by POLYGON
     intersection (§9.3), joined into the build-features orchestrator.
     Preserve suppression: a NULL total contributes unknown, not 0.
   - Pedestrian demand (§10) — highest value, biggest unit: sensor
     daypart baselines from the 1.6M `core.pedestrian_observation`
     rows, then distance-decay interpolation to cells + a separate
     foot-traffic confidence value. Likely split across ≥2 units.
6. Scoring engine: `analytics.location_score` + versioned weighted
   scoring (§15) once enough feature families exist, then
   golden-location evaluation.

## Definition of Done for any unit (copy of ai-workflow-rules.md gate)

- Works end to end locally; relevant `make` target(s) pass:
  `api-lint api-test jobs-lint jobs-test fe-build`.
- No architecture.md invariant violated.
- This file updated.

## Open Questions

- Whether the `transport-activity-counts` **live feed** returns —
  historical 2023→2026-05 multimodal features are now unblocked via
  the adopted bulk archives, but the "current activity" layer needs a
  live feed. Re-check the API periodically (`cli freshness
  transport_activity`); if it revives, flip status `manual` → `active`
  and reconcile schema drift between the API and archive formats.
- Whether the missing licence on the pedestrian hourly-counts dataset
  is an API metadata gap (data is actually CC BY like its sibling
  sensor-locations dataset) or a genuine licensing difference —
  affects what the attribution footer can claim.
- ~~Exact hex-grid resolution~~ **RESOLVED 2026-07-25**: H3 res 10
  (~130m cell width, 2,317 cells over the real boundary) — the only
  resolution landing in the architecture doc's ~100-200m block-face
  target when benchmarked against the real municipality. Stored per
  `data_release`, so revisitable via a new release without a schema
  change.
- Whether to attempt network-distance (pedestrian-network) catchments
  in Phase 2 or start with geodesic buffers and label them approximate.
- ~~Whether PTV GTFS is brought in during the MVP or deferred~~
  **RESOLVED 2026-07-25**: PTV GTFS is in the MVP as the transport
  source (user decision). The four council transport datasets
  (`bus_stops`, `tram_tracks`, `city_circle_*`) are `deferred` in the
  registry — tram_tracks has no stops, city-circle is the tourist
  loop, and none cover trains. GTFS ingested and verified (see
  Completed).
- Hosting choice for the scheduled data-worker container (GitHub
  Actions for earliest prototype vs. a managed container-jobs
  platform) — deferred until Phase 1 begins.
- Final default profile weights (café/retail/food-truck/pop-up) are
  documented as starting hypotheses only and need golden-location
  validation before Phase 2 sign-off.

## Architecture Decisions

- ADR-001: PostgreSQL/PostGIS is the single system of record (no
  separate warehouse/search engine/GIS server) — see
  `architecture.md`.
- ADR-002: Score a precomputed hex grid; map arbitrary user points to
  a cell rather than scoring raw coordinates per request.
- ADR-003: Deterministic, versioned weighted scoring for the MVP — no
  ML until a defensible outcome label exists.
- ADR-004: Data releases are published and versioned independently
  from application deployments.
- ADR-005: Anonymous-first product; accounts required only to save/
  share projects.
- ADR-006: Council data is ingested and stored locally; the runtime
  API never depends on live council endpoints.
- Runtime API (`backend/`) and data worker (`jobs/`) are split into
  separate Python dependency trees/deploy targets to keep the Vercel
  Function bundle small and heavy geospatial libs out of request path.
- Database: Supabase Postgres + PostGIS, Sydney region, chosen over
  Neon for the MVP for its built-in auth/storage/backups reducing the
  number of separate services (see `database-architecture.md`).

## Session Notes

- Source documents (`retailscout-city-of-melbourne-architecture.md`,
  `vercel-template.md`, `database-architecture.md`) live alongside the
  other files in `context/` and are the authoritative research behind
  these context files; consult them directly for details not yet
  distilled into `architecture.md`/`project-overview.md` (e.g. full
  dataset table, detailed scoring formulas, ANZSIC taxonomy example,
  full API endpoint list).
- Raw metadata/sample JSON from the 2026-07-25 data-validation pass
  was written to a session scratchpad, not the repo — it was
  exploratory (live API calls to confirm feasibility), not the
  immutable raw-snapshot layout `architecture.md` specifies. The
  validated facts now live in `jobs/registry/sources.yaml`; proper
  snapshots go under `data/raw/` (gitignored) via `make ingest`.
- Machine facts: dev machine is Apple Silicon (hence the
  `imresamu/postgis` local image); Python 3.14 is what `uv` resolved
  locally (pyprojects require >=3.12); Node 20+/npm and Docker
  Desktop present.
- First commit made 2026-07-25 (`9c3c5fb`): full scaffold, 64 files.
  `data/`, venvs, and node_modules stay gitignored/untracked by
  design — raw snapshots belong in object storage, not git.
- The scaffold intentionally stops at 501 for `/locations/score`:
  the response contract is published and tested, but no scoring logic
  exists. Do not implement scoring in `backend/` — it reads
  `analytics.location_score` rows that `jobs/` will produce
  (Phases 1–2).
