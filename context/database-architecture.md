## Database recommendation

Use **PostgreSQL with PostGIS**. A conventional document database such as MongoDB would be a poor primary database because RetailScout depends heavily on spatial joins, radius searches, polygon intersections, distance calculations, time-series aggregation and relational data.

For your MVP, I recommend:

> **Supabase Postgres with PostGIS, hosted in Sydney**

Supabase provides a full managed Postgres database, supports PostGIS, offers a Sydney region, and can also provide authentication and object storage later. It integrates with Vercel through the Vercel Marketplace. ([Supabase][1])

## Recommended deployment

```text
Next.js on Vercel
        │
        │ HTTPS / JSON
        ▼
FastAPI on Vercel
        │
        │ pooled PostgreSQL connection
        ▼
Supabase PostgreSQL + PostGIS
        │
        ├── Application data
        ├── Published council data
        ├── Geospatial features
        ├── Precomputed scores
        └── User projects

Scheduled ingestion worker
        │
        ├── Downloads council datasets
        ├── Writes raw files to object storage
        ├── Loads staging tables
        └── Publishes transformed data to PostGIS
```

The frontend should not directly query your analytical tables. Use:

```text
Next.js → FastAPI → Postgres
```

You may use Supabase directly from Next.js for authentication, but location scoring, business searches and data access should go through FastAPI.

## Why PostGIS is central

PostGIS gives you indexed geographic types such as points, lines and polygons. It supports operations you will need constantly:

```sql
-- Businesses within 500 metres
ST_DWithin(b.location, candidate.location, 500)

-- Development projects intersecting a catchment
ST_Intersects(d.geometry, catchment.geometry)

-- Distance to the nearest tram stop
ST_Distance(candidate.location, stop.location)

-- Businesses visible in the current map
business.geometry && map_viewport

-- Generate a walking-area approximation
ST_Buffer(candidate.location, 800)
```

PostGIS spatial columns can use GiST indexes, avoiding full-table scans for most geographic searches. ([Supabase][1])

## Database schemas

Avoid placing everything in `public`. I would use these schemas:

```text
retailscout
├── app
│   ├── users
│   ├── projects
│   ├── saved_locations
│   └── score_preferences
│
├── source
│   ├── dataset
│   ├── dataset_release
│   └── ingestion_run
│
├── staging
│   ├── pedestrian_counts
│   ├── clue_businesses
│   ├── clue_employment
│   ├── developments
│   └── transport_stops
│
├── core
│   ├── pedestrian_sensor
│   ├── pedestrian_observation
│   ├── business_establishment
│   ├── employment_area
│   ├── development_project
│   ├── transport_stop
│   └── road_or_pedestrian_segment
│
├── analytics
│   ├── analysis_cell
│   ├── location_feature
│   ├── location_score
│   ├── pedestrian_profile
│   └── business_mix_summary
│
└── audit
    ├── score_request
    └── data_quality_result
```

### What each layer means

`staging` contains data close to the source format. It can be deleted and recreated.

`core` contains cleaned, standardised council data.

`analytics` contains precomputed features and scores served to users.

`app` contains projects, saved locations and user preferences.

`source` tracks exactly which council release generated each result.

## Core tables

### Pedestrian sensors

```sql
CREATE TABLE core.pedestrian_sensor (
    sensor_id          text PRIMARY KEY,
    sensor_name        text NOT NULL,
    status             text,
    installed_at       date,
    location           geometry(Point, 4326) NOT NULL,
    source_release_id  bigint NOT NULL
);

CREATE INDEX pedestrian_sensor_location_idx
ON core.pedestrian_sensor
USING GIST (location);
```

### Pedestrian observations

```sql
CREATE TABLE core.pedestrian_observation (
    sensor_id       text NOT NULL,
    observed_at     timestamptz NOT NULL,
    pedestrian_count integer NOT NULL,
    source_release_id bigint NOT NULL,
    PRIMARY KEY (sensor_id, observed_at)
);
```

This table will become one of the larger tables, so partition it by year or month once the volume justifies it.

Do not query raw observations for every map interaction. Create aggregates such as:

```text
sensor × day of week × hour
sensor × month
sensor × weekday/weekend
sensor × morning/lunch/evening/night
```

### Business establishments

```sql
CREATE TABLE core.business_establishment (
    business_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clue_id            text,
    trading_name       text,
    industry_code      text,
    industry_group     text,
    establishment_type text,
    address            text,
    location           geometry(Point, 4326),
    valid_from         date,
    valid_to           date,
    source_release_id  bigint NOT NULL
);

CREATE INDEX business_establishment_location_idx
ON core.business_establishment
USING GIST (location);

CREATE INDEX business_establishment_industry_idx
ON core.business_establishment (industry_group);
```

Keep closed or historical businesses by using `valid_from` and `valid_to`. That allows you to analyse whether an area is growing or declining rather than only showing its current state.

### Developments

```sql
CREATE TABLE core.development_project (
    development_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id          text,
    project_name       text,
    project_status     text,
    development_type   text,
    estimated_value    numeric,
    dwelling_count     integer,
    floor_area_m2      numeric,
    expected_completion_date date,
    geometry           geometry(Geometry, 4326),
    source_release_id  bigint NOT NULL
);

CREATE INDEX development_project_geometry_idx
ON core.development_project
USING GIST (geometry);
```

### Transport

```sql
CREATE TABLE core.transport_stop (
    stop_id          text PRIMARY KEY,
    stop_name        text,
    mode             text,
    routes           text[],
    location         geometry(Point, 4326),
    source_release_id bigint NOT NULL
);

CREATE INDEX transport_stop_location_idx
ON core.transport_stop
USING GIST (location);
```

## The analysis grid

Do not score arbitrary coordinates from scratch every time someone moves the map.

Create a standard analysis grid across the City of Melbourne. H3 hexagons are convenient, but ordinary PostGIS-generated square or hexagonal cells also work.

```sql
CREATE TABLE analytics.analysis_cell (
    cell_id        text PRIMARY KEY,
    resolution     smallint NOT NULL,
    centroid       geometry(Point, 4326) NOT NULL,
    boundary       geometry(Polygon, 4326) NOT NULL,
    suburb_name    text,
    council_area   text
);

CREATE INDEX analysis_cell_boundary_idx
ON analytics.analysis_cell
USING GIST (boundary);
```

A cell size of approximately **100–200 metres** is reasonable for an initial city exploration heatmap.

Each cell receives precomputed features:

```sql
CREATE TABLE analytics.location_feature (
    cell_id                    text NOT NULL,
    feature_version            text NOT NULL,

    pedestrian_weekday_avg     numeric,
    pedestrian_weekend_avg     numeric,
    pedestrian_morning_avg     numeric,
    pedestrian_lunch_avg       numeric,
    pedestrian_evening_avg     numeric,

    jobs_400m                  integer,
    jobs_800m                  integer,

    cafes_400m                 integer,
    restaurants_400m           integer,
    retail_businesses_400m     integer,
    complementary_businesses_400m integer,

    tram_stops_400m            integer,
    train_stations_800m        integer,
    bus_stops_400m             integer,

    developments_800m          integer,
    development_value_800m     numeric,

    data_confidence            numeric,
    calculated_at              timestamptz NOT NULL,

    PRIMARY KEY (cell_id, feature_version)
);
```

The map can then load a score for thousands of cells without rerunning expensive spatial joins.

## Score storage

Store both the score and its inputs. Never save only a final number.

```sql
CREATE TABLE analytics.location_score (
    cell_id               text NOT NULL,
    business_profile      text NOT NULL,
    score_version         text NOT NULL,
    feature_version       text NOT NULL,

    total_score           numeric NOT NULL,
    foot_traffic_score    numeric,
    worker_demand_score   numeric,
    competition_score     numeric,
    transport_score       numeric,
    development_score     numeric,
    confidence_score      numeric,

    explanation           jsonb,
    calculated_at         timestamptz NOT NULL,

    PRIMARY KEY (
        cell_id,
        business_profile,
        score_version
    )
);
```

Example profiles:

```text
cafe
restaurant
convenience_store
specialty_retail
food_truck
pop_up
```

A café and a food truck should not use identical weights.

The `explanation` JSON could contain:

```json
{
  "strengths": [
    "High weekday morning pedestrian activity",
    "Large worker population within 800 metres",
    "Two tram stops within 400 metres"
  ],
  "risks": [
    "High café density within 400 metres",
    "Limited weekend foot traffic"
  ],
  "source_dates": {
    "pedestrian_counts": "2026-06-30",
    "business_establishments": "2025-12-31"
  }
}
```

## User-facing tables

```sql
CREATE TABLE app.project (
    project_id       uuid PRIMARY KEY,
    user_id          uuid NOT NULL,
    project_name     text NOT NULL,
    business_profile text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.saved_location (
    saved_location_id uuid PRIMARY KEY,
    project_id        uuid NOT NULL REFERENCES app.project(project_id),
    label             text,
    address           text,
    location          geometry(Point, 4326) NOT NULL,
    selected_cell_id  text REFERENCES analytics.analysis_cell(cell_id),
    notes             text,
    created_at        timestamptz NOT NULL DEFAULT now()
);
```

Later you can add:

```text
project collaborators
custom score weights
location comparisons
uploaded candidate premises
generated reports
comments and annotations
```

## Raw files should not live in Postgres

Store original downloaded CSV, GeoJSON or ZIP files in object storage:

```text
raw/
  city-of-melbourne/
    pedestrian-counts/
      2026-07-01/
        source.csv
        metadata.json
    clue-businesses/
      2025-release/
        source.csv
        metadata.json
```

The database should store metadata:

```sql
CREATE TABLE source.dataset_release (
    release_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_key      text NOT NULL,
    source_url       text NOT NULL,
    downloaded_at    timestamptz NOT NULL,
    source_updated_at timestamptz,
    object_path      text NOT NULL,
    checksum_sha256  text NOT NULL,
    row_count        bigint,
    schema_signature text,
    status           text NOT NULL
);
```

This gives you reproducibility and lets you rerun processing after changing the scoring methodology.

## Connections from Vercel

A serverless application can create many short-lived database connections, so use a pooled connection for FastAPI.

For Supabase, the current guidance for serverless and auto-scaling applications is the transaction-mode pooler on port `6543`. With SQLAlchemy, Supabase recommends `NullPool` because the external Supavisor service performs the pooling. ([Supabase][2])

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

engine = create_engine(
    settings.database_url,
    poolclass=NullPool,
    pool_pre_ping=True,
)
```

Use two URLs:

```bash
# FastAPI running on Vercel
DATABASE_URL=postgresql+psycopg://...pooler...:6543/postgres

# Alembic migrations and batch jobs
DATABASE_DIRECT_URL=postgresql+psycopg://...:5432/postgres
```

Use the pooled URL for:

* FastAPI request handling
* Short transactions
* Normal reads and writes

Use the direct URL for:

* Alembic migrations
* Bulk ingestion
* Index creation
* Materialized-view refreshes
* Administrative scripts

## Local development

Run the official PostGIS image locally:

```yaml
services:
  database:
    image: postgis/postgis:17-3.5
    environment:
      POSTGRES_DB: retailscout
      POSTGRES_USER: retailscout
      POSTGRES_PASSWORD: local-development-only
    ports:
      - "5432:5432"
    volumes:
      - retailscout_postgres:/var/lib/postgresql/data
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "pg_isready -U retailscout -d retailscout"
        ]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  retailscout_postgres:
```

Then initialise extensions through Alembic:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

`pg_trgm` will help with fuzzy address, suburb and business-name searches.

## Supabase versus Neon

| Requirement                   |                    Supabase |                                 Neon |
| ----------------------------- | --------------------------: | -----------------------------------: |
| PostgreSQL                    |                         Yes |                                  Yes |
| PostGIS                       |                         Yes |                                  Yes |
| Vercel integration            |                         Yes |                            Excellent |
| Sydney region                 |                         Yes | Check availability when provisioning |
| Built-in authentication       |                      Strong |          Available, but less central |
| Object storage                |                    Built in |              Separate service needed |
| Database branching            | Available through workflows |                            Excellent |
| Serverless connection pooling |                         Yes |                            Excellent |
| Best fit                      |        Complete MVP backend |        Database-focused architecture |

Neon supports PostGIS, pooled serverless connections and direct Vercel Marketplace provisioning. Vercel itself no longer sells a first-party Postgres product; new projects choose a provider such as Neon or Supabase through its Marketplace. ([Neon][3])

My choice for **your current MVP** would still be:

```text
Supabase Sydney
├── PostgreSQL
├── PostGIS
├── Auth
├── Object storage
└── Backups

FastAPI
├── SQLAlchemy
├── GeoAlchemy2
├── Alembic
└── psycopg
```

Supabase reduces the number of separate services you need while retaining standard PostgreSQL, so you are not locked into a proprietary database API. Keep normal SQL migrations and standard connection strings, and you can move to another Postgres provider later.

[1]: https://supabase.com/docs/guides/database/extensions/postgis?utm_source=chatgpt.com "PostGIS: Geo queries | Supabase Docs"
[2]: https://supabase.com/docs/guides/troubleshooting/using-sqlalchemy-with-supabase-FUqebT?utm_source=chatgpt.com "Supabase Docs | Troubleshooting | Using SQLAlchemy with Supabase"
[3]: https://neon.com/use-cases/serverless-apps?utm_source=chatgpt.com "Postgres and backend platform for serverless apps — Neon"
