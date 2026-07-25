# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- Phase 1 (data foundation) underway. Source-provenance tracking
  (migration `0002`) is live end to end; every raw snapshot is now
  traceable in the database, not just on disk.

## Current Goal

- Migration `0003` — `core` schema tables, then the first staging→core
  loader (start with `municipal_boundary`, since everything spatial
  depends on it).

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
   adopt; only the live-feed question remains open.)
2. Run `make ingest` for every remaining `status: active` source to
   produce a full local raw snapshot set with provenance recorded
   (`pedestrian_sensor_locations`, `transport_activity`, `ptv_gtfs`
   already done — `business_establishments`, `cafe_seats`,
   `employment_by_block`, `establishments_per_block`, `clue_blocks`,
   `development_activity`, `pedestrian_network`, `parking_bays`,
   `parking_bay_sensors`, `municipal_boundary` still pending).
3. Migration `0003` — `core` tables; first staging→core loader
   (start: `municipal_boundary`, then `pedestrian_sensor_locations` +
   `pedestrian_hourly`).
4. Generate the analysis hex grid clipped to the municipal boundary
   (resolution decision — open question below — must be settled
   first).

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
- Exact hex-grid resolution (architecture doc suggests ~100–200m;
  needs benchmarking against block-face scale before locking in).
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
