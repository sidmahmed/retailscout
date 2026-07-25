"""municipal_boundary staging loader, against a real PostGIS database.

Same isolation pattern as test_provenance.py: skips if no DB is
reachable, runs inside a transaction that is always rolled back, and
uses a fictional sentinel date so it can never collide with a real
same-day ingest of this source on a shared dev database.
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
from retailscout_jobs.transform.municipal_boundary import load

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)

# A minimal but real-shaped fixture: a small square "municipality"
# around Melbourne's CBD, in the same OpenDataSoft record shape as the
# genuine municipal-boundary export (confirmed by inspecting the real
# 2026-07-25 snapshot — see db/migrations/versions/0003_core_schema.py).
FIXTURE_RECORDS = [
    {
        "mccid_gis": 999,
        "name": "Test Municipality",
        "geo_shape": {
            "type": "Feature",
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [
                            [144.95, -37.82],
                            [144.97, -37.82],
                            [144.97, -37.80],
                            [144.95, -37.80],
                            [144.95, -37.82],
                        ]
                    ]
                ],
            },
        },
    }
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


def _fake_release(db_conn, tmp_path) -> int:
    """Create a real source.dataset_release row to satisfy the FK,
    using the fictional sentinel date so it can't collide with a real
    ingest of this source."""
    registry = load_registry()
    source = registry.get("municipal_boundary")
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


def test_load_inserts_valid_geometry(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)

    count = load(db_conn, snapshot_dir, release_id)
    assert count == 1

    row = db_conn.execute(
        text(
            "SELECT name, ST_GeometryType(geom) AS geom_type, ST_IsValid(geom) AS valid, "
            "source_release_id FROM core.municipal_boundary WHERE id = 999"
        )
    ).one()
    assert row.name == "Test Municipality"
    assert row.geom_type == "ST_MultiPolygon"
    assert row.valid is True
    assert row.source_release_id == release_id


def test_load_boundary_check_matches_expected_containment(db_conn, tmp_path):
    """Proves the loaded geometry is actually usable for FR-02, not
    just present — a point inside the fixture square vs. one outside."""
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)

    inside = db_conn.execute(
        text(
            "SELECT ST_Contains(geom, ST_SetSRID(ST_MakePoint(144.96, -37.81), 4326)) "
            "FROM core.municipal_boundary WHERE id = 999"
        )
    ).scalar_one()
    outside = db_conn.execute(
        text(
            "SELECT ST_Contains(geom, ST_SetSRID(ST_MakePoint(145.10, -37.81), 4326)) "
            "FROM core.municipal_boundary WHERE id = 999"
        )
    ).scalar_one()
    assert inside is True
    assert outside is False


def test_load_is_idempotent(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)
    load(db_conn, snapshot_dir, release_id)

    count = db_conn.execute(
        text("SELECT count(*) FROM core.municipal_boundary WHERE id = 999")
    ).scalar_one()
    assert count == 1
