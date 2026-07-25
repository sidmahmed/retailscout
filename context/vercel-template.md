## Verdict

Link: https://github.com/vercel/examples/tree/main/services/nextjs-fastapi


**Yes, it is a good starting template for RetailScout’s MVP, but only as an application scaffold.** I would rate it about **7/10 for this project**.

It already matches the core application shape from the architecture document:

* Next.js frontend
* FastAPI backend
* TypeScript and Python
* Monorepo structure
* Same-domain routing between frontend and backend
* Simple Vercel deployment

The starter is intentionally minimal, containing little more than a sample Next.js route and FastAPI status endpoint. It does **not** provide the database, GIS, ingestion, scoring, authentication or mapping architecture RetailScout requires. ([GitHub][1])

## What fits well

| RetailScout requirement                   | Template fit |
| ----------------------------------------- | ------------ |
| Next.js frontend                          | Excellent    |
| FastAPI scoring API                       | Excellent    |
| Single monorepo                           | Excellent    |
| Independent frontend/backend dependencies | Good         |
| Same-domain API routing                   | Good         |
| Simple preview deployments                | Excellent    |
| PostGIS database                          | Missing      |
| MapLibre map                              | Missing      |
| Data ingestion worker                     | Missing      |
| Scheduled jobs                            | Missing      |
| Authentication and projects               | Missing      |
| OpenAPI-generated frontend client         | Missing      |
| Data-versioning and provenance            | Missing      |
| Production observability                  | Missing      |

Vercel Services lets the frontend and FastAPI backend be built independently while sharing one deployment and domain. That is convenient for an MVP and avoids dealing with CORS or separate frontend/backend URLs. ([Vercel][2])

## How I would modify it

Use the template, but expand it into this:

```text
retailscout/
├── frontend/
│   ├── app/
│   │   ├── explore/
│   │   ├── locations/[locationId]/
│   │   ├── compare/
│   │   └── methodology/
│   ├── components/
│   │   ├── map/
│   │   ├── scoring/
│   │   ├── charts/
│   │   └── locations/
│   ├── lib/
│   │   ├── api/
│   │   ├── map/
│   │   └── validation/
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── locations.py
│   │   │   ├── scores.py
│   │   │   ├── map_layers.py
│   │   │   ├── businesses.py
│   │   │   └── projects.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   └── security.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   │   ├── scoring.py
│   │   │   ├── catchments.py
│   │   │   └── explanations.py
│   │   └── sql/
│   ├── migrations/
│   ├── tests/
│   └── pyproject.toml
│
├── jobs/
│   ├── ingest/
│   │   ├── pedestrian_counts.py
│   │   ├── clue_businesses.py
│   │   ├── clue_employment.py
│   │   └── developments.py
│   ├── transform/
│   ├── features/
│   ├── scoring/
│   └── tests/
│
├── contracts/
│   └── generated/
│
├── infrastructure/
│   ├── docker-compose.yml
│   └── terraform/
│
├── scripts/
├── vercel.json
└── README.md
```

## The most important architectural separation

Do **not** place the ingestion pipelines inside the public FastAPI application.

You need two Python workloads:

### 1. Runtime API

Fast and relatively lightweight:

* Search or validate a location
* Retrieve precomputed scores
* Query nearby businesses
* Retrieve pedestrian patterns
* Compare locations
* Manage projects
* Generate vector tiles or GeoJSON
* Return score explanations

This can initially run as the FastAPI service in the Vercel template.

### 2. Data worker

Long-running and dependency-heavy:

* Download City of Melbourne datasets
* Store raw snapshots
* Run GeoPandas and spatial transformations
* Load PostGIS
* Create H3 or hexagonal cells
* Calculate walking catchments
* Aggregate pedestrian counts
* Recalculate features and scores
* Validate and publish data releases

Run this separately through:

* A scheduled container job
* GitHub Actions for the earliest prototype
* Azure Container Apps Jobs
* Google Cloud Run Jobs
* AWS ECS scheduled tasks
* Another managed Python container platform

This separation matters because Vercel deploys a FastAPI application as a Vercel Function. The normal Python deployment has a 500 MB uncompressed bundle limit, although Vercel now offers larger-function support in beta. Heavy geospatial packages and bundled datasets can make deployment and cold starts less predictable. ([Vercel][3])

## Dependencies to add

### Frontend

```json
{
  "dependencies": {
    "maplibre-gl": "latest",
    "react-map-gl": "latest",
    "@tanstack/react-query": "latest",
    "zod": "latest",
    "react-hook-form": "latest",
    "recharts": "latest"
  }
}
```

Potentially add:

* `deck.gl` only when you need dense visualisations
* `h3-js` for interacting with H3 cell IDs
* `nuqs` for URL-backed map filters
* A component library such as shadcn/ui

### Runtime backend

```toml
dependencies = [
    "fastapi",
    "pydantic",
    "pydantic-settings",
    "sqlalchemy",
    "alembic",
    "psycopg[binary,pool]",
    "geoalchemy2",
    "shapely",
    "httpx",
    "structlog"
]
```

Keep the runtime backend relatively lean. Most spatial calculations should happen in PostGIS or precomputation jobs.

### Data jobs

```toml
dependencies = [
    "polars",
    "pyarrow",
    "geopandas",
    "shapely",
    "pyproj",
    "httpx",
    "sqlalchemy",
    "psycopg",
    "h3",
    "pandera"
]
```

Keeping `jobs` separate prevents large analytical dependencies from being included in the FastAPI deployment bundle.

## Database setup

The template does not include a database. RetailScout should immediately add:

* Managed PostgreSQL
* PostGIS extension
* Connection pooling
* Alembic migrations
* Separate application and ingestion database roles

For local development:

```yaml
services:
  postgres:
    image: postgis/postgis:17-3.5
    environment:
      POSTGRES_DB: retailscout
      POSTGRES_USER: retailscout
      POSTGRES_PASSWORD: retailscout
    ports:
      - "5432:5432"
    volumes:
      - postgis_data:/var/lib/postgresql/data

volumes:
  postgis_data:
```

Your public API should use a restricted role that can read published feature tables and modify only user/project tables. The ingestion worker should use a separate role capable of loading staging tables and publishing data releases.

## Change the API routing

The template currently demonstrates a FastAPI path under `/svc/api`. ([Vercel][4])

For RetailScout, I would expose:

```text
/api/v1/locations/score
/api/v1/locations/nearby-businesses
/api/v1/locations/pedestrian-pattern
/api/v1/locations/compare
/api/v1/map/tiles/{z}/{x}/{y}.mvt
/api/v1/projects
/api/v1/data-sources
```

I would also remove the sample Next.js `/api/hello` route. Having some API routes in Next.js and others in FastAPI creates unnecessary ambiguity. Let FastAPI own the public application API.

An exception would be authentication callbacks that are more naturally handled inside Next.js.

## Add generated API types

The basic template does not provide type-safe communication between Python and TypeScript.

Add this workflow:

```text
Pydantic schemas
      ↓
FastAPI OpenAPI schema
      ↓
openapi-typescript or Orval
      ↓
Generated TypeScript client
      ↓
React Query hooks
```

For example:

```bash
curl http://localhost:8000/openapi.json \
  --output frontend/openapi.json

npx openapi-typescript frontend/openapi.json \
  --output frontend/lib/api/schema.ts
```

This is particularly valuable for the score response, which will contain nested metrics, confidence ratings, evidence, source dates and explanations.

## Map delivery

For the first prototype:

* MapLibre renders the map
* FastAPI returns a selected location’s supporting GeoJSON
* PostGIS stores all geometries
* A precomputed hex grid stores location features and scores

For the city-wide heatmap, avoid sending thousands of complete GeoJSON polygons. Use:

1. PostGIS `ST_AsMVT`
2. A FastAPI vector-tile route
3. CDN caching
4. MapLibre vector sources

A vector tile might be requested as:

```text
/api/v1/map/tiles/suitability/{z}/{x}/{y}.mvt
    ?profile=cafe
    &daypart=morning
    &score_version=v1
```

The FastAPI service should generate or retrieve tiles from already-published feature tables. It should not calculate all pedestrian, competition and employment features during the tile request.

## Recommended deployment

### Suitable initial setup

```text
Vercel
├── Next.js frontend
└── Lightweight FastAPI API

Managed PostgreSQL/PostGIS
├── Source-normalised data
├── Features and scores
└── User projects

Object storage
└── Immutable council-data snapshots

Scheduled container worker
├── Ingestion
├── Data validation
├── Geospatial feature generation
└── Score publication
```

This retains the template’s simple deployment experience without forcing the entire RetailScout platform into Vercel Functions.

## One caution about Vercel Services

Vercel Services is a relatively new part of the platform. The current template uses it to deploy the frontend and backend together, and Vercel’s current guide supports polyglot deployments such as Next.js plus FastAPI. ([Vercel][5])

Keep the applications independently deployable:

* No Vercel-specific imports in business logic
* Backend configurable through environment variables
* Standard FastAPI ASGI entry point
* Standard Next.js application
* Dockerfile available for the backend
* No reliance on Vercel’s filesystem for persistent data

That gives you an easy path to move FastAPI to a container platform later without rewriting the application.

## Final recommendation

**Start from this template**, but treat the first commit as scaffolding rather than architecture.

Before building product features, add these foundations:

1. Restructure the FastAPI code into routers, services, repositories and schemas.
2. Add PostgreSQL/PostGIS and Alembic.
3. Create a separate `jobs` package.
4. Add MapLibre.
5. Generate TypeScript types from FastAPI OpenAPI.
6. Add local Docker Compose for PostGIS.
7. Add data-release and score-version tables.
8. Configure tests and CI.
9. Keep heavy geospatial processing outside the Vercel API.
10. Replace `/svc/api` with a stable `/api/v1` contract.

With those changes, it becomes a strong base for the City of Melbourne RetailScout MVP.

[1]: https://github.com/vercel/examples/tree/main/services/nextjs-fastapi "examples/services/nextjs-fastapi at main · vercel/examples · GitHub"
[2]: https://vercel.com/kb/guide/vercel-services?utm_source=chatgpt.com "The Complete Guide to Vercel Services | Vercel Knowledge Base"
[3]: https://vercel.com/docs/functions/runtimes/python?utm_source=chatgpt.com "Using the Python Runtime with Vercel Functions"
[4]: https://vercel.com/templates/fast-api/next-js-fastapi-starter "Next.js + FastAPI Starter - Vercel"
[5]: https://vercel.com/docs/services?utm_source=chatgpt.com "Services"
