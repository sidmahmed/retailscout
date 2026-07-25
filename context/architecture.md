# Architecture Context

## Stack

| Layer                 | Technology                                             | Role                                                                 |
| ---------------------- | ------------------------------------------------------- | --------------------------------------------------------------------- |
| Frontend               | Next.js + TypeScript + React                            | Map/score UI, address search, comparison, projects                  |
| Map                    | MapLibre GL JS (+ deck.gl only if needed)                | Interactive suitability map, vector-tile layers                     |
| Runtime API             | FastAPI + Python + Pydantic                              | Public `/api/v1` — scores, evidence, tiles, projects (lean, no heavy geospatial deps) |
| Data worker             | Python (Polars/PyArrow, GeoPandas, Shapely, pyproj, H3, pandera) | Scheduled ingestion, transforms, catchments, scoring — runs outside Vercel Functions |
| Database                | PostgreSQL + PostGIS (Supabase, Sydney region)           | System of record: source, staging, core, analytics, app schemas     |
| ORM / query layer       | SQLAlchemy 2.x + GeoAlchemy2 + explicit SQL for spatial ops | Avoid hiding complex PostGIS operations behind the ORM              |
| Migrations               | Alembic                                                 | Version-controlled schema changes, run via direct (non-pooled) connection |
| Object storage           | S3-compatible bucket (or Supabase Storage)               | Immutable raw council-data snapshots, manifests, quarantine, exports |
| Cache/CDN                | CDN in front of static assets and public vector tiles     | Redis added later only if query volume demonstrates a need           |
| Contracts                 | FastAPI OpenAPI schema → openapi-typescript/Orval → generated TS client | Type-safe Python/TypeScript boundary                                |
| Deployment                | Vercel (Next.js + lightweight FastAPI Vercel Function) + scheduled container worker | Matches the `vercel/examples/services/nextjs-fastapi` scaffold, expanded |

## System Boundaries

Monorepo layout (adapted from the Vercel `nextjs-fastapi` template):

```text
retailscout/
├── frontend/           # Next.js app (app/, components/, lib/)
├── backend/             # Runtime FastAPI app (api/, core/, models/,
│                         # schemas/, repositories/, services/, sql/)
├── jobs/                # Data worker: ingest/, transform/, features/,
│                         # scoring/ — separate deps, never imported by backend/
├── contracts/generated/ # Generated TS client from backend OpenAPI schema
├── infrastructure/      # docker-compose.yml, terraform/
├── db/                  # Alembic migrations, sql/, seeds/
└── tests/               # integration/, golden_locations/
```

- `frontend/` — owns all UI, map rendering, client-side validation
  (zod), and React Query hooks generated against the FastAPI contract.
  Talks to the backend only through `/api/v1/*`. No direct database
  access except Supabase auth if used.
- `backend/` — owns the public runtime API only: candidate validation,
  score retrieval, evidence queries, project CRUD, vector-tile
  serving, admin score-version management. Must stay lightweight
  (Vercel Function size limits) — no GeoPandas/Polars/heavy geospatial
  libs here. Reads precomputed feature/score tables; does not run
  spatial joins or recomputation at request time.
- `jobs/` — owns everything heavy and dependency-rich: downloading
  City of Melbourne datasets, writing raw snapshots, GeoPandas/Shapely
  transforms, hex-grid generation, catchment calculation, pedestrian
  aggregation, feature/score computation, and atomic data-release
  publication. Runs as a scheduled container job, never as a Vercel
  Function.
- `db/` — owns schema migrations (Alembic) and seed data. Migrations
  run through the direct (non-pooled) connection, never the pooled
  runtime connection.

## Storage Model

- **PostgreSQL + PostGIS** (schemas: `source`, `staging`, `core`,
  `analytics`, `app`, `audit`): all structured and geospatial data —
  dataset registry/releases, cleaned council observations
  (`core.*`), the precomputed hex analysis grid and feature/score
  tables (`analytics.*`), and user-facing projects/saved locations
  (`app.*`). This is the system of record for everything the runtime
  API serves.
- **Object storage**: immutable raw CSV/JSON/GeoJSON/ZIP snapshots
  from City of Melbourne, one manifest per retrieval (timestamp,
  checksum, schema fingerprint, row count). Never queried at request
  time — only read by ingestion/reprocessing jobs.
- **CDN/cache**: public vector tiles and static frontend assets.
  Redis is optional and deferred until proven necessary.

## Auth and Access Model

- Anonymous-first: users can explore the map, score locations, and run
  comparisons without an account. Anonymous sessions use signed,
  expiring session identifiers.
- An account is required only to save a project or create a persistent
  share link. Prefer managed auth (Supabase Auth) with
  passwordless/email-link login.
- Every `app.project` has a single owner (`user_id`); only the owner
  (or an explicit collaborator, once added) can mutate its
  `saved_location` rows.
- The runtime API uses a restricted Postgres role that can read
  published `analytics.*`/`core.*` tables and read/write only
  `app.*` tables. The ingestion worker uses a separate role that can
  write `staging.*`/`core.*`/`analytics.*` and publish releases.
- Admin score-version publication and rollback require a role-gated
  admin path and are written to `audit.*`.

## Invariants

1. The runtime API never calls City of Melbourne (or any council)
   endpoints during a user request — all served data comes from
   locally ingested, validated PostGIS tables.
2. Every `location_score` row references an existing `data_release`
   and `score_version`; scores are never computed ad hoc against
   unversioned inputs.
3. A `data_release` is built and validated completely before an
   `active_release_id` pointer switches atomically — partial or
   failed releases are never exposed to users.
4. Missing source data is preserved as missing (not coerced to zero or
   silently dropped); suppressed CLUE cells stay distinguishable from
   zero.
5. Heavy geospatial processing (GeoPandas, catchment computation,
   score calculation) happens only in `jobs/`, never inside the
   `backend/` request path — the runtime API only reads precomputed
   features/scores/tiles.
6. Every score response exposes component scores, a confidence band,
   source dates, and top drivers — a bare overall number is never
   returned without this supporting evidence.
7. All candidate locations are validated against the City of Melbourne
   municipal boundary before scoring; out-of-boundary points are
   rejected or clearly flagged, never silently scored.
8. Source-specific mapping (dataset field names, ANZSIC taxonomy,
   council quirks) lives in ingestion adapters and versioned
   config/YAML, not hard-coded in core application or scoring logic —
   this keeps the door open for another municipality later.
