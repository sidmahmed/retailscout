"""Transport-access feature loader, against a real PostGIS database.

Same isolation as the other DB-backed tests (skip if no DB, rolled-back
transaction, fictional provenance date). core.transport_stop has no
census_year to key a sentinel off, so — like the transport_stop loader's
own test — this DELETEs the 1,300 real stops inside the rolled-back
transaction and inserts only fixtures.

Fixture stops are placed at PRECISE geodesic distances from the target
cell's real centroid (via ST_Project), so the 400 m (tram/bus) vs 800 m
(train) radius distinction is tested exactly, not approximately.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.features.grid import build_grid
from retailscout_jobs.features.transport_features import build_transport_features
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
RES = 9
FIXTURE_BOUNDARY_WKT = (
    "MULTIPOLYGON(((144.95 -37.82, 144.97 -37.82, 144.97 -37.80, 144.95 -37.80, 144.95 -37.82)))"
)
TARGET = (144.96, -37.81)  # lng, lat


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
    registry = load_registry()
    source = registry.get("municipal_boundary")
    raw_root = tmp_path / "raw"
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps([{"mccid_gis": 999, "name": "Test"}]))
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
    return record_release(db_conn, source, snapshot_dir, raw_root)


def _install_boundary(db_conn, release_id: int) -> None:
    db_conn.execute(text("DELETE FROM core.municipal_boundary"))
    db_conn.execute(
        text("""
            INSERT INTO core.municipal_boundary (id, name, geom, source_release_id)
            VALUES (999, 'Test Municipality',
                    ST_SetSRID(ST_GeomFromText(:wkt), 4326), :release_id)
        """),
        {"wkt": FIXTURE_BOUNDARY_WKT, "release_id": release_id},
    )


def _target_cell_id(db_conn, release_id: int) -> str:
    return db_conn.execute(
        text("""
            SELECT cell_id FROM analytics.analysis_cell
            WHERE release_id = :r
              AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
        """),
        {"r": release_id, "lng": TARGET[0], "lat": TARGET[1]},
    ).scalar_one()


def _add_stop_at_distance(
    db_conn,
    grid_release_id: int,
    source_release_id: int,
    cell_id: str,
    stop_id: str,
    mode: str,
    metres: float,
) -> None:
    """Insert a stop `metres` due east (geodesic) of the target cell's
    real centroid, so distance-to-centroid is exactly controlled.
    grid_release_id locates the cell (analytics.data_release); the stop's
    own source_release_id references source.dataset_release."""
    db_conn.execute(
        text("""
            INSERT INTO core.transport_stop (stop_id, stop_name, mode, geom, source_release_id)
            SELECT :sid, :sid, :mode,
                   ST_Project(ac.centroid::geography, :metres, radians(90))::geometry,
                   :source_release_id
            FROM analytics.analysis_cell ac
            WHERE ac.release_id = :grid_release_id AND ac.cell_id = :cid
        """),
        {
            "sid": stop_id,
            "mode": mode,
            "metres": metres,
            "source_release_id": source_release_id,
            "grid_release_id": grid_release_id,
            "cid": cell_id,
        },
    )


def _target_features(db_conn, release_id: int, cell_id: str):
    return db_conn.execute(
        text("""
            SELECT tram_stops_400m, bus_stops_400m, train_stops_800m
            FROM analytics.location_feature
            WHERE release_id = :r AND cell_id = :cid
        """),
        {"r": release_id, "cid": cell_id},
    ).one()


def _setup(db_conn, tmp_path):
    source_release_id = _fake_release(db_conn, tmp_path)
    _install_boundary(db_conn, source_release_id)
    grid = build_grid(db_conn, resolution=RES)
    db_conn.execute(text("DELETE FROM core.transport_stop"))
    return grid, source_release_id


def test_counts_respect_per_mode_radii(db_conn, tmp_path):
    grid, src = _setup(db_conn, tmp_path)
    cid = _target_cell_id(db_conn, grid.release_id)
    r = grid.release_id
    # At the centroid (0 m): all three modes are in range.
    _add_stop_at_distance(db_conn, r, src, cid, "tram_near", "tram", 0)
    _add_stop_at_distance(db_conn, r, src, cid, "bus_near", "bus", 0)
    _add_stop_at_distance(db_conn, r, src, cid, "train_near", "metro_train", 0)
    # At 600 m: outside the 400 m tram/bus radius, inside the 800 m train radius.
    _add_stop_at_distance(db_conn, r, src, cid, "tram_mid", "tram", 600)
    _add_stop_at_distance(db_conn, r, src, cid, "train_mid", "metro_train", 600)
    # At 2 km: out of range of everything.
    _add_stop_at_distance(db_conn, r, src, cid, "bus_far", "bus", 2000)

    build_transport_features(db_conn, feature_version="v1")
    f = _target_features(db_conn, r, cid)
    assert f.tram_stops_400m == 1  # only the 0 m tram (600 m one excluded)
    assert f.bus_stops_400m == 1  # only the 0 m bus (2 km one excluded)
    assert f.train_stops_800m == 2  # 0 m and 600 m trains both within 800 m


def test_cells_with_no_stops_get_zero_not_null(db_conn, tmp_path):
    grid, _ = _setup(db_conn, tmp_path)  # table emptied, no fixtures added
    build_transport_features(db_conn, feature_version="v1")
    nulls = db_conn.execute(
        text("""
            SELECT count(*) FROM analytics.location_feature
            WHERE release_id = :r AND tram_stops_400m IS NULL
        """),
        {"r": grid.release_id},
    ).scalar_one()
    assert nulls == 0


def test_is_idempotent(db_conn, tmp_path):
    grid, src = _setup(db_conn, tmp_path)
    cid = _target_cell_id(db_conn, grid.release_id)
    _add_stop_at_distance(db_conn, grid.release_id, src, cid, "t1", "tram", 0)
    build_transport_features(db_conn, feature_version="v1")
    build_transport_features(db_conn, feature_version="v1")
    f = _target_features(db_conn, grid.release_id, cid)
    assert f.tram_stops_400m == 1


def test_raises_without_active_release(db_conn, tmp_path):
    _fake_release(db_conn, tmp_path)
    db_conn.execute(text("DELETE FROM analytics.active_release"))
    with pytest.raises(ValueError, match="No active grid release"):
        build_transport_features(db_conn, feature_version="v1")
