"""business_establishment staging loader, against a real PostGIS database.

Same isolation pattern as the other transform/provenance tests: skips
if no DB is reachable, rolls back its own transaction, uses a
fictional sentinel date so it never collides with a real same-day
ingest of this source on a shared dev database.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot
from retailscout_jobs.transform.business_establishment import load

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)

CSV_HEADER = (
    "census_year;block_id;property_id;base_property_id;clue_small_area;"
    "trading_name;business_address;industry_anzsic4_code;"
    "industry_anzsic4_description;longitude;latitude;point\n"
)
# Second row has no lon/lat — mirrors the 4,785 real rows (~1.2%) missing
# geometry, which the loader must leave as NULL, not a placeholder point.
FIXTURE_CSV = (
    CSV_HEADER + "2024;44;597186;101146;Melbourne (CBD);Test Cafe;"
    "123 Test St MELBOURNE 3000;4511;Cafes and Restaurants;"
    "144.9630;-37.8150;-37.8150, 144.9630\n"
    + "2024;44;597187;101147;Melbourne (CBD);No Geometry Pty Ltd;"
    "125 Test St MELBOURNE 3000;4279;Other Store-Based Retailing n.e.c.;;;\n"
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
    source = registry.get("business_establishments")
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


def test_load_inserts_rows_with_and_without_geometry(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)

    count = load(db_conn, snapshot_dir, release_id)
    assert count == 2

    with_geom = db_conn.execute(
        text(
            "SELECT trading_name, ST_X(geom) AS lon, ST_Y(geom) AS lat, source_release_id "
            "FROM core.business_establishment WHERE trading_name = 'Test Cafe'"
        )
    ).one()
    assert with_geom.lon == pytest.approx(144.9630)
    assert with_geom.lat == pytest.approx(-37.8150)
    assert with_geom.source_release_id == release_id

    without_geom = db_conn.execute(
        text(
            "SELECT geom FROM core.business_establishment "
            "WHERE trading_name = 'No Geometry Pty Ltd'"
        )
    ).scalar_one()
    assert without_geom is None  # never a placeholder point


def test_load_is_idempotent_via_delete_and_reinsert(db_conn, tmp_path):
    """No stable natural key exists in this source (confirmed by
    profiling — see the loader's docstring), so idempotency works by
    deleting all rows for this release_id before reinserting, not by
    ON CONFLICT. Re-running must not accumulate duplicates."""
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)
    load(db_conn, snapshot_dir, release_id)

    count = db_conn.execute(
        text("SELECT count(*) FROM core.business_establishment WHERE source_release_id = :id"),
        {"id": release_id},
    ).scalar_one()
    assert count == 2  # not 4


def test_load_raises_on_empty_file(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path, csv_content=CSV_HEADER)
    with pytest.raises(ValueError, match="No rows"):
        load(db_conn, snapshot_dir, release_id)
