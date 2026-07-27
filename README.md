# RetailScout

Location-intelligence web app for the City of Melbourne: helps a
prospective operator (café, retail shop, food truck, pop-up) compare
candidate locations using council open data, with explainable versioned
scores and explicit data confidence. test

> **Start here:** read `CLAUDE.md`, then the six files under
> [`context/`](context/) **in order**. They are the product/architecture
> spec and the workflow rules. Do not implement anything that
> contradicts them. `context/progress-tracker.md` tells you what to do
> next.

## Repository map

| Path | What it is | Owns |
|---|---|---|
| `frontend/` | Next.js 15 + TypeScript app | All UI, MapLibre map, React Query hooks |
| `backend/` | FastAPI runtime API (**lean** — deployable as a Vercel Function) | `/api/v1/*` only: score retrieval, evidence, projects, tiles |
| `jobs/` | Data worker (separate dependency tree — **never** imported by `backend/`) | Ingestion, transforms, features, scoring, release publication |
| `jobs/registry/sources.yaml` | **Source registry** — the validated list of council datasets | Dataset IDs, fetch modes, cadences, caveats |
| `db/` | Alembic migrations + SQL | Schema: `source`, `staging`, `core`, `analytics`, `app`, `audit` |
| `contracts/` | Generated TypeScript client from the FastAPI OpenAPI schema | Never hand-edited |
| `infrastructure/` | Docker Compose (local PostGIS), deployment notes | |
| `tests/golden_locations/` | Fixed reference locations re-scored every release | Regression guard for score changes |
| `context/` | **The spec.** Product, architecture, UI, standards, workflow, progress | |

## Quick start (local)

```bash
# 1. Database (PostGIS 17)
make db-up

# 2. Apply migrations (creates extensions + schemas)
make db-migrate

# 3. Runtime API (http://localhost:8000, docs at /docs)
make api-dev

# 4. Frontend (http://localhost:3000)
make fe-dev

# 5. Ingest one source into data/raw/ (proof-of-life)
make ingest SOURCE=pedestrian_sensor_locations
```

Prerequisites: Docker, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+.
Copy `.env.example` to `.env` first.

## Non-negotiable invariants (from `context/architecture.md`)

1. The runtime API **never** calls council endpoints during a user
   request — it only reads locally ingested PostGIS tables.
2. Heavy geospatial deps (GeoPandas/Polars/H3) live **only** in
   `jobs/`. `backend/` must stay small enough for a Vercel Function.
3. Missing source data stays missing — never coerce `null` to `0`
   (CLUE suppression is real; verified against the live API).
4. Data releases publish atomically via an `active_release_id`
   pointer — never row-by-row updates of live tables.
5. Every score response carries `score_version`, `data_release`, and
   a confidence object. No bare numbers.

## Council API — hard facts (verified 2026-07-25)

- Base: `https://data.melbourne.vic.gov.au/api/explore/v2.1/catalog/datasets/{id}`
- `/records` is capped at `limit=100`, `offset<10000` (~10k rows max
  via pagination). **Bulk ingestion must use `/exports/{csv,json}`**
  (uncapped). Constants are encoded in
  `jobs/retailscout_jobs/opendatasoft.py`.
- Dataset `metas.default.modified` is unreliable — derive freshness
  from the data itself (e.g. `MAX(sensing_date)`).
- `transport-activity-counts` is currently **empty** (blocked — see
  `sources.yaml`). Pedestrian hourly counts has **no licence in API
  metadata** (verify before beta).

## Deployment

One Vercel project, two [Services](https://vercel.com/docs/services)
under a single domain — `frontend/` (Next.js) and `backend/` (FastAPI,
entrypoint `app.main:app`) — routed by the root `vercel.json`
(`/api/*` → backend, everything else → frontend). Same-origin in
production, so no CORS is needed there; `cors_origins` in
`backend/app/core/config.py` only matters for local dev
(`localhost:3000` → `localhost:8000`).

Database is Supabase Postgres/PostGIS (Sydney): the pooled Supavisor
connection (port 6543) is `DATABASE_URL` for the deployed API —
`backend/app/core/database.py`'s `NullPool` is deliberate, matching
this pooler — and the direct connection (port 5432) is
`DATABASE_DIRECT_URL`, used only for Alembic migrations and `jobs/`.

`jobs/` (the data worker — GeoPandas/H3/ingestion) is **not** part of
the Vercel deployment; it stays a separate process pointed at the same
Supabase instance. For now it runs manually from a local machine
against `DATABASE_DIRECT_URL`/`DATABASE_URL` set to Supabase; scheduled
automation (GitHub Actions cron → ingest → rebuild → atomic release
swap) is tracked as its own backlog item, not required for a first
deploy.

Runbook for a first deploy:

1. Create the Supabase project (Sydney region). Grab both connection
   strings (direct `:5432`, pooled Supavisor `:6543`).
2. `make db-migrate` locally with `DATABASE_DIRECT_URL` pointed at
   Supabase's direct string, to bring it to head (0001–0013). If
   migration `0001`'s `CREATE EXTENSION IF NOT EXISTS postgis` lacks
   permission, enable PostGIS via Supabase's dashboard
   (Database → Extensions) first.
3. Seed one real data release against Supabase using the existing
   `make` targets (`ingest` → `build-grid` → `build-features` →
   `build-ped-baselines` → `build-ped-features` → `build-scores`), then
   run `jobs/tests/test_golden_locations.py`'s DB-backed test against
   it as the go/no-go gate.
4. `vercel link` at the repo root so the project picks up `vercel.json`
   and builds both services together.
5. Set `DATABASE_URL` (Supabase pooled string) and
   `NEXT_PUBLIC_GEOCODER_URL` as Vercel environment variables
   (Production + Preview).
6. Deploy (`vercel --prod` or push to `main`), then verify
   `/api/v1/health`, `/api/v1/coverage`, a real score lookup, and the
   map loading with no CORS errors.
