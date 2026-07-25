"""pedestrian_sensor staging loader, against a real PostGIS database.

Same isolation pattern as the other transform/provenance tests: skips
if no DB is reachable, rolls back its own transaction, uses a
fictional sentinel date so it never collides with a real same-day
ingest of this source on a shared dev database.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot
from retailscout_jobs.transform.pedestrian_sensor import load

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)

# Real-shaped fixture (matches the confirmed 2026-07-25 snapshot's
# fields exactly) covering both nullable-field cases actually observed
# in production: a sensor with a null installation_date and one with
# null direction labels.
FIXTURE_RECORDS = [
    {
        "location_id": 9001,
        "sensor_description": "Test Corner",
        "sensor_name": "Test001_T",
        "installation_date": "2020-01-15",
        "note": None,
        "location_type": "Outdoor",
        "status": "A",
        "direction_1": "North",
        "direction_2": "South",
        "latitude": -37.81,
        "longitude": 144.96,
        "location": {"lon": 144.96, "lat": -37.81},
    },
    {
        "location_id": 9002,
        "sensor_description": "Test Corner 2",
        "sensor_name": "Test002_T",
        "installation_date": None,
        "note": None,
        "location_type": "Indoor",
        "status": "A",
        "direction_1": None,
        "direction_2": None,
        "latitude": -37.82,
        "longitude": 144.97,
        "location": {"lon": 144.97, "lat": -37.82},
    },
]


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


def _fake_release(db_conn, tmp_path):
    registry = load_registry()
    source = registry.get("pedestrian_sensor_locations")
    raw_root = tmp_path / "raw"
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps(FIXTURE_RECORDS))
    snapshot_dir = write_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_url="https://example.test/exports/json",
        data_file=data_file,
        export_format="json",
        fields=source.fields_observed,
        now=FIXED_NOW,
    )
    upsert_dataset(db_conn, registry, source)
    release_id = record_release(db_conn, source, snapshot_dir, raw_root)
    return release_id, snapshot_dir


def test_load_inserts_expected_rows(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)

    count = load(db_conn, snapshot_dir, release_id)
    assert count == 2

    rows = db_conn.execute(
        text(
            "SELECT sensor_id, sensor_name, installed_at, direction_1_label, "
            "ST_X(geom) AS lon, ST_Y(geom) AS lat, source_release_id "
            "FROM core.pedestrian_sensor WHERE sensor_id IN (9001, 9002) ORDER BY sensor_id"
        )
    ).all()
    assert len(rows) == 2

    normal, nulls = rows
    assert normal.sensor_name == "Test001_T"
    assert normal.installed_at == dt.date(2020, 1, 15)
    assert normal.direction_1_label == "North"
    assert normal.lon == pytest.approx(144.96)
    assert normal.lat == pytest.approx(-37.81)
    assert normal.source_release_id == release_id

    # the null-field case, matching the real data (1 sensor with null
    # installed_at, 34 with null direction labels) — the loader must
    # not choke on or silently coerce these
    assert nulls.installed_at is None
    assert nulls.direction_1_label is None


def test_load_is_idempotent_and_upserts_changes(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)

    # simulate a status change on re-ingest (e.g. sensor decommissioned)
    data_file = snapshot_dir / "data.json"
    records = json.loads(data_file.read_text())
    records[0]["status"] = "D"
    data_file.write_text(json.dumps(records))

    load(db_conn, snapshot_dir, release_id)

    count = db_conn.execute(
        text("SELECT count(*) FROM core.pedestrian_sensor WHERE sensor_id IN (9001, 9002)")
    ).scalar_one()
    assert count == 2  # no duplicates

    status = db_conn.execute(
        text("SELECT status FROM core.pedestrian_sensor WHERE sensor_id = 9001")
    ).scalar_one()
    assert status == "D"  # the update actually took effect
