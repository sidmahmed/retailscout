## Yes. The strongest source is CLUE, but call it “historical business resilience”

City of Melbourne’s **Census of Land Use and Employment (CLUE)** contains annual business-establishment observations from **2002 to 2024**, including trading name, address, ANZSIC4 industry, coordinates, property identifiers, block and small-area classification. It represents business **locations**, rather than legal companies, which is exactly the geographic level RetailScout needs. ([CoM Open Data Portal][1])

You can use this to estimate whether similar businesses historically:

* Remained operating for one, three or five years
* Disappeared from a premises
* Were replaced by another business
* Expanded or contracted
* Clustered successfully in the surrounding area
* Experienced high establishment turnover

But you should **not label this as profitability or commercial success**. CLUE does not contain revenue, profit, rent, insolvency reason or owner returns.

A safer product name would be:

> **Historical Business Resilience**

---

# 1. Primary dataset: CLUE business establishments

The main dataset contains:

```text
census_year
block_id
property_id
base_property_id
clue_small_area
trading_name
business_address
industry_anzsic4_code
industry_anzsic4_description
longitude
latitude
```

The public dataset does **not** contain a permanent establishment identifier. ([Data Victoria][2])

Therefore, RetailScout must create its own longitudinal identity by matching annual observations using:

```text
Normalised trading name
+ property/base-property ID
+ standardised address
+ coordinates
+ ANZSIC4 category
```

For example:

```text
2018  Market Lane Coffee  109-111 Collins Street  Café
2019  Market Lane Coffee  109 Collins St          Café
2020  Market Lane Coffee  109 Collins Street      Café
```

These should probably be treated as the same observed establishment despite minor address differences.

## Important survey limitation

CLUE is updated annually, but City of Melbourne says commercial properties are physically surveyed at least once every two years. That means an apparent one-year disappearance should not automatically be classified as a closure without additional validation. ([CoM Open Data Portal][1])

I would use:

```text
Present in year T and T+1:
    continuing

Missing in T+1 but present again in T+2:
    observation gap

Missing for two consecutive annual releases:
    probable exit

Different business at the same property:
    premises turnover

Same business at a different property:
    possible relocation
```

These states should retain an entity-resolution confidence score.

---

# 3. Useful historical metrics

## A. Cohort survival

For businesses first observed in a particular period:

```text
One-year observed persistence
Three-year observed persistence
Five-year observed persistence
```

Conceptually:

```text
3-year persistence =
businesses still observed 3 years after first appearance
÷
businesses first observed in the cohort
```

Use establishment cohorts, for example:

```text
Cafés first observed in 2014–2019
within 500 metres of this location
```

Do not include very recent entrants in a five-year metric because they have not yet had enough time to survive five years.

## B. Median observed tenure

Estimate how long similar establishments typically remain visible in CLUE.

Use survival-analysis methods such as Kaplan–Meier rather than averaging only closed businesses. Businesses still open in 2024 are **right-censored**, not completed observations.

## C. Annual churn rate

```text
probable exits during year
÷
establishments operating at start of year
```

A high-churn area may indicate:

* Difficult economics
* High rents
* Heavy competition
* Tourism or event volatility
* Temporary retail formats
* Rapidly changing consumer demand

It does not automatically mean the area is bad.

## D. Premises turnover

Track how often a particular property changes occupant:

```text
22 Example Street

2013–2015   Café A
2016–2017   Café B
2018        Vacant or unobserved
2019–2022   Café C
2023–2024   Restaurant D
```

A site with four hospitality operators in ten years is a different risk from a nearby property occupied by one café for ten years.

## E. Category retention

Measure whether the **business category**, rather than the individual operator, persists at the premises.

Example:

```text
Café A closes
Café B immediately replaces it
Café B continues for six years
```

This could indicate the premises works for cafés even though the first operator did not persist.

## F. Net establishment growth

```text
new similar establishments
− probable exits
```

Calculate over three, five and ten-year windows.

## G. Capacity growth

For cafés and restaurants:

```text
Current dining seats
Seat growth over five years
Seats per establishment
Indoor/outdoor seat mix
```

## H. Local resilience relative to baseline

Compare the local result against:

* City of Melbourne overall
* Similar CLUE small areas
* Victoria-wide industry survival
* Locations with comparable pedestrian activity and worker population

For example:

```text
Local 3-year café persistence:       64%
City of Melbourne café persistence:  56%
Difference:                          +8 percentage points
```

This is more useful than showing 64% without context.

---

# 4. How to calculate it for a hexagon

A single 150–200 metre hexagon may contain very few historical businesses. A displayed rate such as “100% survived” could mean only one business existed.

Therefore, do not calculate the metric solely from businesses physically inside the cell.

Use the selected hexagon as the centre of a local catchment:

```text
Selected analysis hex
        +
businesses within 400 metres
        +
optional comparison at 800 metres
```

Prefer a walking-network catchment later, rather than a simple circular radius.

## Minimum samples

Suggested display rules:

```text
Fewer than 5 historical entrants:
    Insufficient evidence

5–14 entrants:
    Low confidence

15–29 entrants:
    Moderate confidence

30+ entrants:
    Higher confidence
```

Those thresholds can be adjusted after examining the actual distribution.

## Smoothing

For cells with small samples, shrink the observed rate towards the broader City of Melbourne industry rate.

Conceptually:

```text
adjusted local rate =
weighted combination of
local observed rate
and
City of Melbourne baseline
```

The smaller the local sample, the more weight the baseline receives.

This avoids:

```text
Hex A: 100% survival, based on 2 businesses
Hex B: 72% survival, based on 85 businesses
```

being interpreted as Hex A being safer.

---

# 5. Additional supporting datasets

## CLUE business size and employment

City of Melbourne also publishes historical establishment and employment counts by industry and business-size category for 2002–2024:

* Non-employing
* Small, 1–19 jobs
* Medium, 20–199 jobs
* Large, 200 or more jobs

The public small-area data is confidentialised, with low-count cells suppressed. City of Melbourne notes that non-confidentialised data may be available under a data-supply agreement. ([CoM Open Data Portal][4])

This could support indicators such as:

```text
Growth in hospitality employment
Share of small versus medium establishments
Whether surviving businesses appear to expand employment
Employment resilience following shocks
```

For a serious version of RetailScout, contacting the CLUE team about a data-supply agreement would be worthwhile.

## ABS business survival

The ABS publishes official entry, exit and survival data. Its survival cubes include industry subdivision, state and employment or turnover size. It also publishes industry business counts at SA2 and LGA level. ([Australian Bureau of Statistics][5])

Use it as a **benchmark**, not as the local hexagon outcome:

```text
Observed café resilience around the location
versus
Victorian accommodation and food-services benchmark
```

The ABS local SA2/LGA datasets can indicate growth in business counts, but the detailed survival tables are not available at individual-premises or hexagon level. ([Australian Bureau of Statistics][5])

## Victorian liquor licences

Victoria publishes monthly snapshots of active liquor licences with business name, licence type, address, trading hours and coordinates. Historical monthly resources are available, including snapshots from at least 2024 onward on the current portal. ([Data Victoria][6])

This can strengthen hospitality analysis:

* Licensed venue openings and disappearances
* Licence continuity at a property
* Licensed restaurant and bar density
* Growth or decline in late-night venues
* Patron-capacity trends where available

A licence disappearing does not necessarily mean business failure, but it is a useful corroborating event.

## ABN Lookup

ABN Lookup provides current and historical ABN status, entity names, GST status, business names and main business-location history. Its web services are free after registration. ([ABN Lookup][7])

However, it is a weak primary source for RetailScout because:

* It identifies legal entities, not necessarily individual outlets.
* Main business location is published only at state and postcode level.
* A hospitality business may operate multiple venues under one entity.
* A venue may close while the ABN remains active.
* A venue may remain open after ownership changes.

Use ABN data only where you can establish a high-confidence entity match.

---

# 6. Recommended data model

```sql
CREATE TABLE analytics.business_observation (
    observation_id          uuid PRIMARY KEY,
    census_year             integer NOT NULL,
    source_release_id       bigint NOT NULL,

    property_id             text,
    base_property_id        text,
    trading_name_raw        text,
    trading_name_normalised text,
    business_address        text,

    anzsic4_code             text,
    business_category       text,
    location                 geometry(Point, 4326),

    indoor_seats             integer,
    outdoor_seats            integer,

    source_record_hash       text NOT NULL
);
```

Create a generated longitudinal entity:

```sql
CREATE TABLE analytics.business_establishment_entity (
    establishment_entity_id uuid PRIMARY KEY,
    canonical_name          text,
    canonical_category      text,
    first_observed_year     integer,
    last_observed_year      integer,
    entity_match_confidence numeric,
    match_method            text
);
```

Link annual observations:

```sql
CREATE TABLE analytics.business_entity_observation (
    establishment_entity_id uuid NOT NULL,
    observation_id          uuid NOT NULL,
    match_confidence        numeric NOT NULL,
    PRIMARY KEY (
        establishment_entity_id,
        observation_id
    )
);
```

Store inferred lifecycle events separately:

```sql
CREATE TABLE analytics.business_lifecycle_event (
    event_id                 uuid PRIMARY KEY,
    establishment_entity_id uuid,
    property_id              text,
    event_type               text NOT NULL,
    event_year               integer NOT NULL,
    confidence               numeric NOT NULL,
    evidence                 jsonb NOT NULL
);
```

Possible event types:

```text
FIRST_OBSERVED
CONTINUED
OBSERVATION_GAP
PROBABLE_EXIT
REOPENED
RELOCATED
RENAMED
CATEGORY_CHANGED
REPLACED_AT_PREMISES
SEATING_EXPANDED
SEATING_REDUCED
```

---

# 7. Hexagon aggregate table

```sql
CREATE TABLE analytics.business_resilience_metric (
    cell_id                     text NOT NULL,
    business_profile            text NOT NULL,
    metric_version              text NOT NULL,
    catchment_metres            integer NOT NULL,
    cohort_start_year           integer NOT NULL,
    cohort_end_year             integer NOT NULL,

    entrant_count               integer,
    probable_exit_count         integer,

    persistence_1y              numeric,
    persistence_3y              numeric,
    persistence_5y              numeric,
    median_observed_tenure_years numeric,

    annual_churn_rate           numeric,
    premises_turnover_rate      numeric,
    net_establishment_growth    numeric,
    seat_capacity_growth        numeric,

    city_baseline_3y            numeric,
    adjusted_persistence_3y     numeric,

    sample_size                 integer NOT NULL,
    confidence_level            text NOT NULL,
    calculated_at               timestamptz NOT NULL,

    PRIMARY KEY (
        cell_id,
        business_profile,
        metric_version
    )
);
```

---

# 8. What the user should see

An illustrative location card could show:

```text
Historical café resilience                         Moderate

3-year observed persistence                        61%
City of Melbourne comparison                       +7 percentage points
Median observed tenure                             4.6 years
Probable exits during the past five years           9
New café establishments during the past five years 13
Net change                                          +4
Premises turnover                                   Moderate
Historical sample                                  31 cafés
Data period                                         2008–2024
```

Then include:

> This measures whether similar establishments remained observable in City of Melbourne census data. It does not measure profitability, revenue or the reason a business stopped operating.

## Better than one opaque “success score”

I would present three components:

```text
Business persistence
How long similar businesses remain observable

Category growth
Whether similar businesses are entering or leaving

Premises stability
How frequently nearby sites change operators
```

Then optionally combine them into a:

```text
Historical resilience index: 72/100
```

Keep the underlying metrics visible.

---

# 9. Agent integration

Add a deterministic tool:

```python
get_business_resilience(
    location_id: str,
    business_profile: str,
    catchment_metres: int = 500,
    comparison_period_years: int = 10,
) -> BusinessResilienceResult
```

Example conversation:

> **User:** How successful have cafés historically been here?

The tool returns:

```json
{
  "business_profile": "cafe",
  "sample_size": 31,
  "persistence_3y": 0.61,
  "city_baseline_3y": 0.54,
  "median_observed_tenure_years": 4.6,
  "entrant_count_5y": 13,
  "probable_exit_count_5y": 9,
  "confidence": "moderate",
  "limitations": [
    "Persistence does not measure profitability",
    "Historical establishments were probabilistically matched"
  ]
}
```

The LLM explains the result but does not calculate survival or infer closures itself.

---

## MVP recommendation

For the first City of Melbourne version:

1. Use CLUE establishments from 2002–2024.
2. Start with cafés/restaurants, retail shops and takeaway food.
3. Match businesses using property ID, normalised name, address and category.
4. Require two-year evidence before declaring a probable exit.
5. Calculate one, three and five-year observed persistence.
6. Calculate premises turnover and net category growth.
7. Use 400–500 metre catchments around each analysis hex.
8. Apply minimum sample sizes and statistical smoothing.
9. Show City-wide comparison benchmarks.
10. Label the feature **historical resilience**, not success probability.

This would be one of RetailScout’s strongest differentiators, because it tells users not only whether an area looks attractive today, but whether similar businesses have historically endured there.

[1]: https://data.melbourne.vic.gov.au/explore/dataset/business-establishments-with-address-and-industry-classification/?utm_source=chatgpt.com "Business establishments location and industry classification — CoM Open Data Portal"
[2]: https://discover.data.vic.gov.au/en_AU/dataset/business-establishments-location-and-industry-classification/resource/b8575bd0-16d4-452e-a4ec-db48330e6356 "Business establishments location and industry classification - Business establishments location and industry classification CSV - Victorian Government Data Vic"
[3]: https://data.melbourne.vic.gov.au/explore/dataset/cafes-and-restaurants-with-seating-capacity/information/ "Café, restaurant, bistro seats — CoM Open Data Portal"
[4]: https://data.melbourne.vic.gov.au/explore/dataset/business-establishments-and-jobs-data-by-business-size-and-clue-industry/?utm_source=chatgpt.com "Business establishments and jobs data by business size and CLUE industry in small areas — CoM Open Data Portal"
[5]: https://www.abs.gov.au/statistics/economy/business-indicators/counts-australian-businesses-including-entries-and-exits/latest-release "Counts of Australian Businesses, including Entries and Exits, July 2021 - June 2025 | Australian Bureau of Statistics"
[6]: https://discover.data.vic.gov.au/dataset/victorian-liquor-licences-by-location?utm_source=chatgpt.com "Victorian liquor licences by location - Dataset - Victorian Government Data Vic"
[7]: https://abr.business.gov.au/Documentation/WebServiceRegistration?utm_source=chatgpt.com "Web services registration | ABN Lookup"
