"""pedestrian_hourly staging loader, against a real PostGIS database.

Same isolation pattern as the other transform/provenance tests: skips
if no DB is reachable, rolls back its own transaction, uses a
fictional sentinel date for provenance so it never collides with a
real same-day ingest of this source on a shared dev database.

Fixture data intentionally mimics the REAL export format exactly
(semicolon delimiter, UTF-8 BOM) — that format was only discovered by
opening the actual downloaded file, so a test using a plain comma CSV
would not have caught it.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot
from retailscout_jobs.transform.pedestrian_hourly import load

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
MELBOURNE = ZoneInfo("Australia/Melbourne")

CSV_HEADER = (
    "id;location_id;sensing_date;hourday;direction_1;direction_2;"
    "pedestriancount;sensor_name;location\n"
)
FIXTURE_CSV = (
    CSV_HEADER
    + "1;9101;2025-06-15;14;10;20;30;Test Sensor;-37.81, 144.96\n"
    # sensor_id with no matching core.pedestrian_sensor row — proves
    # the loader has no FK dependency on that table (architecture.md
    # §4.2 / the real orphan-sensor case found in production data)
    + "2;9999;2025-06-15;9;5;5;10;Orphan Sensor;-37.82, 144.97\n"
)


@pytest.fixture
def db_conn():
    engine = get_engine()
    try:
        conn = engine.connect()
    except OperationalError:
        pytest.skip("no database reachable — start it with `make db-up && make db-migrate`")
    trans = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()
        engine.dispose()


def _fake_release(db_conn, tmp_path, csv_content: str = FIXTURE_CSV):
    registry = load_registry()
    source = registry.get("pedestrian_hourly")
    raw_root = tmp_path / "raw"
    data_file = tmp_path / "data.csv"
    data_file.write_text(csv_content, encoding="utf-8-sig")
    snapshot_dir = write_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_url="https://example.test/exports/csv",
        data_file=data_file,
        export_format="csv",
        fields=source.fields_observed,
        now=FIXED_NOW,
    )
    upsert_dataset(db_conn, registry, source)
    release_id = record_release(db_conn, source, snapshot_dir, raw_root)
    return release_id, snapshot_dir


def test_load_parses_semicolon_bom_csv_and_converts_timezone(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)

    count = load(db_conn, snapshot_dir, release_id)
    assert count == 2

    row = db_conn.execute(
        text(
            "SELECT observed_at, pedestrian_count, direction_1_count, direction_2_count, "
            "source_release_id FROM core.pedestrian_observation "
            "WHERE sensor_id = 9101"
        )
    ).one()

    # independently computed expected UTC instant, not reusing the
    # loader's own _observed_at helper — actually exercises whether the
    # SQL round-trip through Postgres produced the right timestamptz
    expected_utc = dt.datetime(2025, 6, 15, 14, tzinfo=MELBOURNE).astimezone(dt.UTC)
    assert row.observed_at == expected_utc
    assert row.pedestrian_count == 30
    assert row.direction_1_count == 10
    assert row.direction_2_count == 20
    assert row.source_release_id == release_id


def test_load_accepts_sensor_id_with_no_matching_sensor_row(db_conn, tmp_path):
    """No FK to core.pedestrian_sensor by design — real orphan sensor_ids
    (28, 65, 78) exist in production and must not fail to load."""
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)

    exists = db_conn.execute(
        text("SELECT count(*) FROM core.pedestrian_observation WHERE sensor_id = 9999")
    ).scalar_one()
    assert exists == 1

    sensor_row_exists = db_conn.execute(
        text("SELECT count(*) FROM core.pedestrian_sensor WHERE sensor_id = 9999")
    ).scalar_one()
    assert sensor_row_exists == 0  # confirms this really is an orphan, not an accident


def test_load_is_idempotent_and_upserts_changes(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)

    changed_csv = FIXTURE_CSV.replace(
        "1;9101;2025-06-15;14;10;20;30;Test Sensor;-37.81, 144.96",
        "1;9101;2025-06-15;14;10;20;99;Test Sensor;-37.81, 144.96",
    )
    (snapshot_dir / "data.csv").write_text(changed_csv, encoding="utf-8-sig")
    load(db_conn, snapshot_dir, release_id)

    count = db_conn.execute(
        text("SELECT count(*) FROM core.pedestrian_observation WHERE sensor_id IN (9101, 9999)")
    ).scalar_one()
    assert count == 2  # no duplicates from the second load

    updated_count = db_conn.execute(
        text("SELECT pedestrian_count FROM core.pedestrian_observation WHERE sensor_id = 9101")
    ).scalar_one()
    assert updated_count == 99  # the update actually took effect


def test_load_raises_on_empty_file(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path, csv_content=CSV_HEADER)
    with pytest.raises(ValueError, match="No rows"):
        load(db_conn, snapshot_dir, release_id)
