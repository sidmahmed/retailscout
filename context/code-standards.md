# Code Standards

## General

- Keep `backend/` (runtime API) and `jobs/` (data worker) strictly
  separate dependency trees — never import GeoPandas/Polars/heavy
  geospatial libs into `backend/`, and never import FastAPI routing
  into `jobs/`. This boundary exists to keep the Vercel Function
  bundle small and cold starts predictable.
- Fix root causes, do not layer workarounds. If a score looks wrong,
  trace it back through `feature_version`/`score_version` rather than
  patching the displayed number.
- Do not mix unrelated concerns in one component, route, or job step
  (e.g. do not compute scores inside an ingestion transform step, do
  not fetch evidence inside a tile-rendering route).
- Prefer explicit, typed contracts (Pydantic ↔ generated TS) over
  ad hoc JSON shapes anywhere data crosses the frontend/backend
  boundary.

## TypeScript

- Strict mode required throughout `frontend/`.
- Avoid `any` — use the generated OpenAPI types
  (`frontend/lib/api/schema.ts`) for all API response shapes; add
  narrow interfaces only for UI-only state.
- Validate all external input (URL params, form input, map-click
  coordinates) with `zod` at the boundary before it reaches
  components or API calls.
- Use React Query (`@tanstack/react-query`) for all server-state
  fetching — no ad hoc `useEffect` fetch calls.

## Next.js

- Default to server components; add `"use client"` only where map
  interactivity, drawers, or form state require it.
- Let FastAPI own the public application API (`/api/v1/*`). Next.js
  API routes are reserved for auth callbacks only — do not split
  business logic across both.
- Keep route handlers/pages focused: data fetching via generated
  client + React Query hooks, presentation in components.

## Python (backend — runtime API)

- FastAPI + Pydantic v2 for all request/response models; every public
  endpoint has an explicit `response_model`.
- Structure as routers → services → repositories → schemas
  (`backend/app/api`, `services`, `repositories`, `schemas`) — no
  business logic directly in route handlers.
- The runtime API only reads precomputed `analytics.*` tables; it must
  not run GeoPandas transforms, catchment computation, or score
  calculation inline. If a request seems to need that, the
  precomputation is missing from `jobs/`, not something to patch here.
- Use SQLAlchemy 2.x + GeoAlchemy2 for typed queries, but drop to
  explicit SQL for non-trivial PostGIS operations (`ST_DWithin`,
  `ST_AsMVT`, etc.) rather than hiding them behind the ORM.
- Use the pooled Supabase connection (`DATABASE_URL`, port 6543,
  `NullPool`) for all request-time queries; never the direct URL.

## Python (jobs — data worker)

- One responsibility per job stage: `ingest/` (download + raw
  snapshot), `transform/` (staging → core), `features/` (catchments,
  aggregates), `scoring/` (score calculation + release publication).
- Every ingestion job writes an immutable raw snapshot with a manifest
  (retrieval timestamp, source URL, checksum, row count, schema
  fingerprint) before any transformation runs.
- Never mutate `analytics.*`/`core.*` tables row by row for an active
  release. Build the full new release in staging, validate it, then
  atomically flip `active_release_id`.
- Preserve missingness and suppression explicitly (nullable columns +
  a flag, not sentinel zeros) — this is a hard product requirement,
  not a style preference.
- Use `pandera` schemas (or equivalent) to validate staging data
  before it is promoted to `core`/`analytics`.

## Styling

- Use the CSS custom-property tokens defined in `ui-context.md` — no
  hardcoded hex values in components.
- Score and confidence colors must use the dedicated
  `--score-*`/`--confidence-*` tokens, never the generic
  `--state-error`/`--state-success` tokens, so the two concepts never
  visually collide.
- Follow the border-radius scale defined in `ui-context.md`.

## API Routes

- Validate and parse all request input (including lat/lon) with
  Pydantic before any logic runs; reject or flag points outside the
  City of Melbourne boundary explicitly (FR-02) rather than silently
  scoring them.
- Every score/evidence response must include `score_version`,
  `data_release`, and a confidence object — never return a bare
  number.
- Rate-limit geocoding, score, and export endpoints.
- Return consistent, predictable response shapes matching the OpenAPI
  contract exactly — the generated TS client depends on this.

## Data and Storage

- Metadata, processed observations, features, and scores belong in
  PostgreSQL/PostGIS (`core`, `analytics` schemas).
- Raw CSV/JSON/GeoJSON/ZIP source files belong in object storage,
  never in Postgres.
- Every processed row traces back to a `source_release_id`; never load
  transformed data without recording which raw release produced it.
- Partition or aggregate high-volume time-series tables (e.g.
  `core.pedestrian_observation`) rather than querying raw rows on
  every map interaction — serve from precomputed aggregates.

## File Organization

- `frontend/` — Next.js app, UI components, client-side API/map/
  validation libs.
- `backend/` — runtime FastAPI app only (routers, services,
  repositories, schemas, core config/db/security).
- `jobs/` — ingestion, transform, feature, and scoring pipelines;
  separate `pyproject.toml` and dependency set from `backend/`.
- `contracts/generated/` — generated TypeScript client; never hand-
  edited, always regenerated from the FastAPI OpenAPI schema.
- `db/` — Alembic migrations, raw SQL, seed data.
- `tests/` — `integration/` and `golden_locations/` (fixed set of
  known locations re-scored on every release to catch regressions).
