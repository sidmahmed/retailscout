# RetailScout

## Overview

RetailScout is a location-intelligence web application for the City of
Melbourne that helps a prospective operator — someone opening a café,
retail shop, food truck or pop-up — compare candidate locations. It
answers: "How suitable is this location for my type of business, what
evidence supports that result, and how reliable is the available
data?" The MVP uses a transparent, explainable weighted scoring model
(not machine learning) built entirely from local government open data
that RetailScout ingests, versions and republishes — it never queries
council APIs live during a user request.

## Goals

1. Let a user score any point inside the City of Melbourne municipal
   boundary for one of four business profiles and see an overall
   score, component scores, supporting evidence and a confidence
   rating.
2. Make every score explainable and reproducible — each result
   references a specific score-model version and a specific data
   snapshot ("data release"), and every metric shows its source and
   freshness.
3. Never overstate sparse or stale source data — pedestrian sensor
   interpolation, annual CLUE data, and indicative development
   pipelines must always be labelled with their real limitations and
   confidence bands.
4. Support comparing two to five candidate locations side by side
   within a saved project.
5. Ship a focused solo MVP in roughly 10–16 person-weeks by using a
   deterministic scoring model, a precomputed hex grid, and a modular
   monolith rather than microservices or ML.

## Core User Flow

1. User selects a business profile (café, retail shop, food truck,
   pop-up) and adjusts trading days/dayparts.
2. User searches an address or clicks a point on the city-wide
   suitability map.
3. RetailScout validates the point is inside the City of Melbourne
   boundary and maps it to a precomputed analysis-grid cell.
4. RetailScout returns an overall suitability score, component scores,
   confidence band, and supporting evidence (pedestrian patterns,
   nearby competitors/complementary businesses, worker demand, nearby
   developments, access/parking).
5. User saves the location to a project and repeats for up to five
   locations.
6. User compares saved locations side by side and can view/print a
   report.

## Features

### Explore

- City-wide suitability heatmap on a precomputed hex grid
- Filter by small area, score, or data confidence
- Business-profile and daypart controls that change weighting and
  displayed evidence

### Score a location

- Address search or map click, restricted to the City of Melbourne
  boundary
- Overall score, seven component scores, and a confidence band
- Top positive drivers and top risks/weaknesses
- Daypart/weekday-weekend pedestrian pattern chart
- Nearby competitor and complementary business breakdown
- Worker-demand estimate by walking catchment
- Nearby major developments with status and scale
- Walking/transport/parking access indicators
- Source, observation period, and last-refresh date per metric

### Compare and save

- Anonymous-first exploration; account only required to save/share
- Save candidate locations into a project
- Compare 2–5 locations' component scores, raw metrics, and trade-offs
- Printable/exportable report

### Admin

- Publish a new score-model version without redeploying the frontend
- Roll back to a previous data release
- Audit log for score/config publication

## Scope

### In Scope

- City of Melbourne municipality only (design should not hard-code
  Melbourne-specific concepts into the core domain model, so another
  LGA can be added later)
- Four business profiles: café, retail shop, food truck, pop-up
- Deterministic, weighted, versioned scoring using City of Melbourne
  Open Data (pedestrian counts, sensor locations, transport activity,
  business establishments, café seating, CLUE employment/blocks,
  development activity, pedestrian network, on-street parking)
- Precomputed hex-grid cells with vector-tile rendering via MapLibre
- Anonymous exploration plus optional accounts for saved projects
- Data-quality checks, versioned data releases, and score-version
  history

### Out of Scope

- Predicting sales, profit, rent, or business survival
- Commercial lease listings and asking rents; unit-level vacancy
- Planning-permit or food-business permit approval
- Detailed ABS Census demographic segmentation
- Mobile-phone movement data, card-spend/transaction data
- Commercial tourism-visitation data, real-time event attendance
- Nationwide coverage (single-municipality MVP)
- Automated investment advice
- Machine-learning scoring (deferred until a defensible outcome label
  exists, e.g. establishment persistence/closure data)

## Success Criteria

1. A user can search or click any eligible City of Melbourne location
   and receive a score for all four business profiles, each with
   component evidence, data dates, and a confidence band.
2. Sensor-based foot-traffic interpolation is never presented as
   observed storefront footfall.
3. A user can compare at least three saved locations.
4. The city-wide map renders smoothly at normal zoom levels
   (map-tile p95 < 500ms cached, point-score p95 < 800ms precomputed).
5. A source outage or failed ingestion never breaks the running app
   and never publishes a partial data release; admins can roll back to
   a previous release.
6. Golden-location and data-quality tests pass before each release,
   and City of Melbourne / map-provider attribution is always visible.
