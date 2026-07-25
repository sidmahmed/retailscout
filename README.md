# RetailScout

Location-intelligence web app for the City of Melbourne: helps a
prospective operator (café, retail shop, food truck, pop-up) compare
candidate locations using council open data, with explainable versioned
scores and explicit data confidence.

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

## Deployment shape (target)

Vercel (Next.js + lean FastAPI) → Supabase Postgres/PostGIS (Sydney,
pooled port 6543 for runtime, direct 5432 for migrations/jobs) →
S3-compatible object storage for raw snapshots → scheduled container
(GitHub Actions initially) running `jobs/`.
