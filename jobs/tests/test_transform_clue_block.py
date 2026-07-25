"""clue_block staging loader, against a real PostGIS database.

Same isolation pattern as test_transform_municipal_boundary.py: skips if
no DB, rolls back its own transaction, fictional sentinel date for
provenance.
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
from retailscout_jobs.transform.clue_block import load

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)


def _block(block_id: int, region: str, area: str, lon: float, lat: float) -> dict:
    """A record in the real clue_blocks export shape: a 0.01° square block
    around (lon, lat), with geo_point_2d as its centre."""
    d = 0.005
    return {
        "block_id": block_id,
        "region_name": region,
        "area_name": area,
        "geo_point_2d": {"lon": lon, "lat": lat},
        "geo_shape": {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [lon - d, lat - d],
                        [lon + d, lat - d],
                        [lon + d, lat + d],
                        [lon - d, lat + d],
                        [lon - d, lat - d],
                    ]
                ],
            },
        },
    }


FIXTURE_RECORDS = [
    _block(244, "Carlton", "Carlton", 144.9629, -37.8024),
    _block(501, "West Melbourne (Industrial)", "West Melbourne", 144.9350, -37.8100),
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


def _fake_release(db_conn, tmp_path, records=FIXTURE_RECORDS):
    registry = load_registry()
    source = registry.get("clue_blocks")
    raw_root = tmp_path / "raw"
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps(records))
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


def test_load_inserts_all_blocks_with_valid_polygon_geometry(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)

    count = load(db_conn, snapshot_dir, release_id)
    assert count == 2

    row = db_conn.execute(
        text("""
            SELECT region_name, area_name,
                   ST_GeometryType(geom) AS gtype, ST_IsValid(geom) AS valid,
                   ST_GeometryType(centroid) AS ctype, source_release_id
            FROM core.clue_block WHERE block_id = 244
        """)
    ).one()
    assert row.region_name == "Carlton"
    assert row.area_name == "Carlton"
    assert row.gtype == "ST_Polygon"
    assert row.valid is True
    assert row.ctype == "ST_Point"
    assert row.source_release_id == release_id


def test_centroid_matches_source_geo_point(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)

    lon, lat = db_conn.execute(
        text("SELECT ST_X(centroid), ST_Y(centroid) FROM core.clue_block WHERE block_id = 244")
    ).one()
    assert lon == pytest.approx(144.9629)
    assert lat == pytest.approx(-37.8024)


def test_load_is_idempotent_and_upserts(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)

    # Re-load with a changed label for block 244 — upsert must take effect.
    changed = [
        _block(244, "Carlton North", "Carlton", 144.9629, -37.8024),
        FIXTURE_RECORDS[1],
    ]
    release2, snapshot2 = _fake_release(db_conn, tmp_path, records=changed)
    load(db_conn, snapshot2, release2)

    # Scoped to the fixture blocks — the real 603-block snapshot may also
    # be loaded in the shared dev DB (visible in this transaction).
    count = db_conn.execute(
        text("SELECT count(*) FROM core.clue_block WHERE block_id IN (244, 501)")
    ).scalar_one()
    assert count == 2  # no duplicate rows
    region = db_conn.execute(
        text("SELECT region_name FROM core.clue_block WHERE block_id = 244")
    ).scalar_one()
    assert region == "Carlton North"  # the update actually took effect
