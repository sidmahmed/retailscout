"""Core schema: cleaned, standardised council data.

Scope per db/README.md roadmap. Every table carries `source_release_id`
(FK to source.dataset_release from migration 0002) so any row traces
back to the exact raw snapshot it came from.

Column choices are informed by the ACTUAL field types/values in the
real snapshots ingested 2026-07-25 (see jobs/registry/sources.yaml
fields_observed), not guessed from the architecture docs alone:

- core.municipal_boundary: source geo_shape is a GeoJSON MultiPolygon
  (confirmed by inspection, not assumed) — geometry column is typed
  accordingly, not the generic `geometry(Geometry, 4326)`.
- core.pedestrian_observation: deliberately has NO foreign key to
  core.pedestrian_sensor. architecture.md §4.2 warns sensor locations
  change and historical location_ids may not appear in the current
  sensor-locations snapshot (which only lists currently-known sensors).
  A hard FK would break loading historical rows for decommissioned
  sensors. sensor_id is indexed but unconstrained by design.
  pedestrian_count is NOT NULL: per the dataset's own description
  ("where no pedestrians have passed ... a count of zero will be
  shown"), zero is a real observed value here, unlike CLUE's null
  suppression. True missingness is the ABSENCE of a row for an
  expected (sensor, hour), which this table does not attempt to
  represent — that is an application-level concern once a canonical
  expected-observations calendar exists.
- core.business_establishment: no valid_from/valid_to yet. The source
  has no stable identity key across census years (property_id +
  trading_name + industry code is not guaranteed unique), and
  architecture.md explicitly says to "treat business identity matching
  cautiously" — that requires a deliberate entity-matching strategy,
  which is future work, not something to bolt onto raw loading.
- core.development_project: only identifying/status/geometry fields
  are first-class columns. The source has ~35 numeric attribute
  columns (floor areas by use, dwelling/bed counts by type) that no
  consumer needs to query individually yet — they are preserved
  losslessly in `raw_attributes jsonb` (the same pattern
  database-architecture.md already uses for location_score.explanation)
  rather than speculatively modelling every column before the
  development-opportunity scoring methodology (architecture.md §13)
  says which ones actually matter.
- core.transport_stop: shaped for PTV GTFS stops.txt (architecture.md
  §14.2's recommended source), not the deferred council datasets.
  `mode` is derived from the GTFS numbered folder (train/tram/bus),
  not a native GTFS column. `routes` stays nullable until a
  routes/trips loader exists.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE core.municipal_boundary (
            id                 integer PRIMARY KEY,
            name               text NOT NULL,
            geom               geometry(MultiPolygon, 4326) NOT NULL,
            source_release_id  bigint NOT NULL REFERENCES source.dataset_release(release_id),
            loaded_at          timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX municipal_boundary_geom_idx ON core.municipal_boundary USING GIST (geom)"
    )

    op.execute("""
        CREATE TABLE core.pedestrian_sensor (
            sensor_id           integer PRIMARY KEY,
            sensor_name         text NOT NULL,
            sensor_description  text,
            location_type       text,
            status              text NOT NULL,
            installed_at        date,
            direction_1_label   text,
            direction_2_label   text,
            geom                geometry(Point, 4326) NOT NULL,
            source_release_id   bigint NOT NULL REFERENCES source.dataset_release(release_id),
            loaded_at           timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX pedestrian_sensor_geom_idx ON core.pedestrian_sensor USING GIST (geom)"
    )

    op.execute("""
        CREATE TABLE core.pedestrian_observation (
            sensor_id          integer NOT NULL,
            observed_at        timestamptz NOT NULL,
            pedestrian_count   integer NOT NULL CHECK (pedestrian_count >= 0),
            direction_1_count  integer CHECK (direction_1_count >= 0),
            direction_2_count  integer CHECK (direction_2_count >= 0),
            source_release_id  bigint NOT NULL REFERENCES source.dataset_release(release_id),
            loaded_at          timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (sensor_id, observed_at)
        )
    """)

    op.execute("""
        CREATE TABLE core.business_establishment (
            business_id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            census_year                   integer NOT NULL,
            block_id                      integer,
            property_id                   bigint,
            base_property_id              bigint,
            clue_small_area               text,
            trading_name                  text,
            business_address              text,
            industry_anzsic4_code         text,
            industry_anzsic4_description  text,
            geom                          geometry(Point, 4326),
            source_release_id             bigint NOT NULL REFERENCES source.dataset_release(release_id),
            loaded_at                     timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX business_establishment_geom_idx "
        "ON core.business_establishment USING GIST (geom)"
    )
    op.execute(
        "CREATE INDEX business_establishment_census_year_idx "
        "ON core.business_establishment (census_year)"
    )

    op.execute("""
        CREATE TABLE core.development_project (
            development_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            development_key     text NOT NULL,
            status               text,
            year_completed       integer,
            clue_small_area      text,
            clue_block           text,
            street_address       text,
            geom                 geometry(Point, 4326),
            raw_attributes       jsonb NOT NULL,
            source_release_id    bigint NOT NULL REFERENCES source.dataset_release(release_id),
            loaded_at            timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX development_project_geom_idx "
        "ON core.development_project USING GIST (geom)"
    )

    op.execute("""
        CREATE TABLE core.transport_stop (
            stop_id              text PRIMARY KEY,
            stop_name            text NOT NULL,
            mode                 text NOT NULL,
            routes               text[],
            wheelchair_boarding  boolean,
            geom                 geometry(Point, 4326) NOT NULL,
            source_release_id    bigint NOT NULL REFERENCES source.dataset_release(release_id),
            loaded_at            timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX transport_stop_geom_idx ON core.transport_stop USING GIST (geom)")


def downgrade() -> None:
    op.execute("DROP TABLE core.transport_stop")
    op.execute("DROP TABLE core.development_project")
    op.execute("DROP TABLE core.business_establishment")
    op.execute("DROP TABLE core.pedestrian_observation")
    op.execute("DROP TABLE core.pedestrian_sensor")
    op.execute("DROP TABLE core.municipal_boundary")
