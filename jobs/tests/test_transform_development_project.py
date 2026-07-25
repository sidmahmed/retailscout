"""development_project staging loader, against a real PostGIS database.

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
from retailscout_jobs.transform.development_project import load

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)

CSV_HEADER = (
    "data_format;development_key;status;year_completed;clue_small_area;clue_block;"
    "street_address;property_id;property_id_2;property_id_3;property_id_4;property_id_5;"
    "floors_above;resi_dwellings;studio_dwe;one_bdrm_dwe;two_bdrm_dwe;three_bdrm_dwe;"
    "student_apartments;student_beds;student_accommodation_units;institutional_accom_beds;"
    "hotel_rooms;serviced_apartments;hotels_serviced_apartments;hostel_beds;childcare_places;"
    "office_flr;retail_flr;industrial_flr;storage_flr;education_flr;hospital_flr;"
    "recreation_flr;publicdispaly_flr;community_flr;car_spaces;bike_spaces;"
    "town_planning_application;longitude;latitude;geopoint\n"
)
# 41 columns matching the real header exactly. Second row has no
# year_completed — mirrors the 317 real not-yet-completed projects.
FIXTURE_CSV = (
    CSV_HEADER + "Post Oct 2022;TEST001;COMPLETED;2024;Melbourne (CBD);401;1 Test St;"
    "100001;;;;;10;20;0;5;10;5;0;0;0;0;0;0;0;0;0;"
    "500;200;0;0;0;0;0;0;0;30;10;TP-2024-001;144.9630;-37.8150;-37.8150, 144.9630\n"
    + "Post Oct 2022;TEST002;UNDER CONSTRUCTION;;West Melbourne;402;2 Test St;"
    "100002;;;;;5;0;0;0;0;0;0;0;0;0;0;0;0;0;0;"
    "0;100;0;0;0;0;0;0;0;5;2;TP-2024-002;144.9450;-37.8060;-37.8060, 144.9450\n"
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
    source = registry.get("development_activity")
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


def test_load_inserts_rows_with_typed_and_jsonb_attributes(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)

    count = load(db_conn, snapshot_dir, release_id)
    assert count == 2

    row = db_conn.execute(
        text(
            "SELECT status, year_completed, clue_small_area, ST_X(geom) AS lon, "
            "ST_Y(geom) AS lat, raw_attributes, source_release_id "
            "FROM core.development_project WHERE development_key = 'TEST001'"
        )
    ).one()
    assert row.status == "COMPLETED"
    assert row.year_completed == 2024
    assert row.clue_small_area == "Melbourne (CBD)"
    assert row.lon == pytest.approx(144.9630)
    assert row.lat == pytest.approx(-37.8150)
    assert row.source_release_id == release_id

    attrs = (
        row.raw_attributes
        if isinstance(row.raw_attributes, dict)
        else json.loads(row.raw_attributes)
    )
    assert attrs["resi_dwellings"] == 20  # stored as a real int, not a string
    assert attrs["data_format"] == "Post Oct 2022"
    assert attrs["property_id_2"] is None  # blank source field -> JSON null


def test_load_handles_null_year_completed(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)

    year_completed = db_conn.execute(
        text(
            "SELECT year_completed FROM core.development_project WHERE development_key = 'TEST002'"
        )
    ).scalar_one()
    assert year_completed is None


def test_load_is_idempotent_via_delete_and_reinsert(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)
    load(db_conn, snapshot_dir, release_id)

    count = db_conn.execute(
        text("SELECT count(*) FROM core.development_project WHERE source_release_id = :id"),
        {"id": release_id},
    ).scalar_one()
    assert count == 2


def test_load_raises_on_empty_file(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path, csv_content=CSV_HEADER)
    with pytest.raises(ValueError, match="No rows"):
        load(db_conn, snapshot_dir, release_id)
