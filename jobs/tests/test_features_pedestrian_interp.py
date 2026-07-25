"""Pedestrian interpolation loader, against a real PostGIS database.

Isolation: fixture sensors use fictional sensor_ids and their baselines a
fictional baseline_version ('test'), so the real 100 sensors / 1,224
'v1' baselines never contribute (the loader joins on baseline_version).
Sensors are placed at PRECISE geodesic distances from the target cell's
real centroid (ST_Project) so the distance-decay weighting and the
confidence bands are tested exactly.
"""

from __future__ import annotations

import datetime as dt
import json
import math

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.features.grid import build_grid
from retailscout_jobs.features.pedestrian_features import build_pedestrian_features
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
BV = "test"  # baseline_version sentinel — isolates from real 'v1' baselines
RES = 9
FIXTURE_BOUNDARY_WKT = (
    "MULTIPOLYGON(((144.95 -37.82, 144.97 -37.82, 144.97 -37.80, 144.95 -37.80, 144.95 -37.82)))"
)
TARGET = (144.96, -37.81)
DECAY = 250.0  # must match pedestrian_config.yaml interpolation.decay_distance_m


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


def _setup(db_conn, tmp_path):
    src = _fake_release(db_conn, tmp_path)
    db_conn.execute(text("DELETE FROM core.municipal_boundary"))
    db_conn.execute(
        text("""
            INSERT INTO core.municipal_boundary (id, name, geom, source_release_id)
            VALUES (999, 'Test', ST_SetSRID(ST_GeomFromText(:wkt), 4326), :src)
        """),
        {"wkt": FIXTURE_BOUNDARY_WKT, "src": src},
    )
    grid = build_grid(db_conn, resolution=RES)
    cid = db_conn.execute(
        text("""
            SELECT cell_id FROM analytics.analysis_cell
            WHERE release_id = :r AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
        """),
        {"r": grid.release_id, "lng": TARGET[0], "lat": TARGET[1]},
    ).scalar_one()
    return grid, src, cid


def _add_sensor_with_baseline(
    db_conn, grid_release, src, cid, sensor_id, metres, median, *, with_location=True
):
    """Place a sensor `metres` from the target cell centroid (optionally
    with NO location, to test that unlocated sensors are excluded), and
    give it a weekday/lunch baseline of `median` under baseline_version BV."""
    if with_location:
        db_conn.execute(
            text("""
                INSERT INTO core.pedestrian_sensor
                    (sensor_id, sensor_name, status, geom, source_release_id)
                SELECT :sid, :name, 'A',
                       ST_Project(ac.centroid::geography, :metres, radians(90))::geometry, :src
                FROM analytics.analysis_cell ac WHERE ac.release_id = :gr AND ac.cell_id = :cid
            """),
            {
                "sid": sensor_id,
                "name": f"s{sensor_id}",
                "metres": metres,
                "src": src,
                "gr": grid_release,
                "cid": cid,
            },
        )
    db_conn.execute(
        text("""
            INSERT INTO analytics.sensor_daypart_baseline
                (sensor_id, day_type, daypart, baseline_version, median_count,
                 n_observations, n_days, window_start, window_end, source_release_id)
            VALUES (:sid, 'weekday', 'lunch', :bv, :median, 100, 50,
                    DATE '2098-01-01', DATE '2099-01-01', :src)
        """),
        {"sid": sensor_id, "bv": BV, "median": median, "src": src},
    )


def _target(db_conn, release_id, cid):
    return db_conn.execute(
        text("""
            SELECT pedestrian_estimate, n_sensors, nearest_sensor_m, foot_traffic_confidence
            FROM analytics.cell_pedestrian_daypart
            WHERE release_id = :r AND cell_id = :cid
              AND day_type = 'weekday' AND daypart = 'lunch' AND baseline_version = :bv
        """),
        {"r": release_id, "cid": cid, "bv": BV},
    ).one_or_none()


def test_distance_decay_weighted_mean(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_sensor_with_baseline(db_conn, grid.release_id, src, cid, 900001, 0, 1000)
    _add_sensor_with_baseline(db_conn, grid.release_id, src, cid, 900002, 500, 200)
    build_pedestrian_features(db_conn, baseline_version=BV)

    w1, w2 = math.exp(0), math.exp(-500 / DECAY)
    expected = (w1 * 1000 + w2 * 200) / (w1 + w2)
    f = _target(db_conn, grid.release_id, cid)
    assert float(f.pedestrian_estimate) == pytest.approx(expected, abs=1.0)
    assert f.n_sensors == 2
    assert float(f.nearest_sensor_m) == pytest.approx(0, abs=1.0)


def test_confidence_high_needs_close_and_multiple(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    for i, m in enumerate((10, 50, 120)):  # 3 sensors, all within 200 m
        _add_sensor_with_baseline(db_conn, grid.release_id, src, cid, 900010 + i, m, 500)
    build_pedestrian_features(db_conn, baseline_version=BV)
    assert _target(db_conn, grid.release_id, cid).foot_traffic_confidence == "high"


def test_confidence_medium_when_close_but_few(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_sensor_with_baseline(db_conn, grid.release_id, src, cid, 900020, 300, 500)  # <=450, n=1
    build_pedestrian_features(db_conn, baseline_version=BV)
    assert _target(db_conn, grid.release_id, cid).foot_traffic_confidence == "medium"


def test_confidence_low_when_far(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_sensor_with_baseline(db_conn, grid.release_id, src, cid, 900030, 600, 500)  # 450<d<=650
    build_pedestrian_features(db_conn, baseline_version=BV)
    assert _target(db_conn, grid.release_id, cid).foot_traffic_confidence == "low"


def test_insufficient_beyond_max_distance_writes_no_row(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_sensor_with_baseline(db_conn, grid.release_id, src, cid, 900040, 2000, 500)  # > 650 m
    build_pedestrian_features(db_conn, baseline_version=BV)
    assert _target(db_conn, grid.release_id, cid) is None  # absent = insufficient


def test_unlocated_sensor_is_excluded(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_sensor_with_baseline(db_conn, grid.release_id, src, cid, 900050, 0, 1000)  # located
    _add_sensor_with_baseline(
        db_conn, grid.release_id, src, cid, 900051, 0, 9999, with_location=False
    )  # baseline but no geometry -> must not contribute
    build_pedestrian_features(db_conn, baseline_version=BV)
    f = _target(db_conn, grid.release_id, cid)
    assert f.n_sensors == 1
    assert float(f.pedestrian_estimate) == pytest.approx(1000, abs=1.0)


def test_raises_without_baselines(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)  # grid exists, but no 'test' baselines added
    # A different, real baseline_version may exist; force the no-baseline path explicitly.
    with pytest.raises(ValueError, match="No sensor baselines"):
        # Delete all baselines so the auto-detect finds none.
        db_conn.execute(text("DELETE FROM analytics.sensor_daypart_baseline"))
        build_pedestrian_features(db_conn)
