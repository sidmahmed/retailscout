"""Development-pipeline feature loader, against a real PostGIS database.

Same isolation as the other DB-backed tests (rolled-back transaction).
Fixture projects are inserted under the test's own fake source release
and the builder is called with that source_release_id explicitly, so the
real 1,438-row snapshot never contributes. Projects are placed at EXACT
geodesic distances from the target cell's real centroid via ST_Project,
making the decay math predictable, and the config is constructed
in-test with round numbers so tuning the registry's starting-hypothesis
factors never breaks these assertions.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.development_config import DevelopmentConfig, DistanceDecay
from retailscout_jobs.features.development_features import build_development_features
from retailscout_jobs.features.grid import build_grid
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
RES = 9
FIXTURE_BOUNDARY_WKT = (
    "MULTIPOLYGON(((144.95 -37.82, 144.97 -37.82, 144.97 -37.80, 144.95 -37.80, 144.95 -37.82)))"
)
TARGET = (144.96, -37.81)

# Round-number config: a 100-dwelling project at 400 m (half the radius)
# with status probability 0.5 contributes 100 × 2.0 × 0.5 × 0.5 = 50.
CONFIG = DevelopmentConfig(
    version="test",
    status_probability={"TEST_FIRM": 0.5, "TEST_SURE": 1.0, "COMPLETED": 1.0},
    completed_since_year=2050,
    people_equivalents={"resi_dwellings": 2.0, "office_flr": 0.1},
    distance_decay=DistanceDecay(radius_m=800),
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


def _install_boundary(db_conn, src: int) -> None:
    db_conn.execute(text("DELETE FROM core.municipal_boundary"))
    db_conn.execute(
        text("""
            INSERT INTO core.municipal_boundary (id, name, geom, source_release_id)
            VALUES (999, 'Test', ST_SetSRID(ST_GeomFromText(:wkt), 4326), :src)
        """),
        {"wkt": FIXTURE_BOUNDARY_WKT, "src": src},
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


def _add_project(
    db_conn,
    grid_release: int,
    src: int,
    cell_id: str,
    key: str,
    status: str,
    distance_m: float,
    attributes: dict,
    year_completed: int | None = None,
) -> None:
    """A project at an EXACT geodesic distance due east of the target
    cell's real centroid (ST_Project — same idiom as the transport
    tests)."""
    db_conn.execute(
        text("""
            INSERT INTO core.development_project
                (development_key, status, year_completed, geom, raw_attributes,
                 source_release_id)
            SELECT :key, :status, :year,
                   ST_Project(ac.centroid::geography, :dist, radians(90))::geometry,
                   CAST(:attrs AS jsonb), :src
            FROM analytics.analysis_cell ac
            WHERE ac.release_id = :gr AND ac.cell_id = :cid
        """),
        {
            "key": key,
            "status": status,
            "year": year_completed,
            "dist": distance_m,
            "attrs": json.dumps(attributes),
            "src": src,
            "gr": grid_release,
            "cid": cell_id,
        },
    )


def _target_dev(db_conn, release_id: int, cell_id: str):
    return db_conn.execute(
        text(
            "SELECT dev_pipeline_people_800m, dev_projects_800m "
            "FROM analytics.location_feature "
            "WHERE release_id = :r AND cell_id = :cid"
        ),
        {"r": release_id, "cid": cell_id},
    ).one()


def _setup(db_conn, tmp_path):
    src = _fake_release(db_conn, tmp_path)
    _install_boundary(db_conn, src)
    grid = build_grid(db_conn, resolution=RES)
    cid = _target_cell_id(db_conn, grid.release_id)
    return grid, src, cid


def _build(db_conn, src: int):
    build_development_features(db_conn, feature_version="v1", config=CONFIG, source_release_id=src)


def test_exact_weighting_math(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    # 100 dwellings × 2.0 people × prob 0.5 × decay (1 - 400/800) = 50.
    _add_project(
        db_conn, grid.release_id, src, cid, "T-1", "TEST_FIRM", 400, {"resi_dwellings": 100}
    )

    _build(db_conn, src)
    f = _target_dev(db_conn, grid.release_id, cid)
    assert float(f.dev_pipeline_people_800m) == pytest.approx(50.0, abs=0.2)
    assert f.dev_projects_800m == 1


def test_scale_fields_sum_and_out_of_range_excluded(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    # 50 dwellings + 3000 m² office = (50×2.0 + 3000×0.1) = 400 people,
    # prob 1.0, decay (1 - 200/800) = 0.75 → 300.
    _add_project(
        db_conn,
        grid.release_id,
        src,
        cid,
        "T-1",
        "TEST_SURE",
        200,
        {"resi_dwellings": 50, "office_flr": 3000},
    )
    # Beyond the 800 m radius: contributes nothing, counted nowhere.
    _add_project(
        db_conn, grid.release_id, src, cid, "T-2", "TEST_SURE", 900, {"resi_dwellings": 1000}
    )

    _build(db_conn, src)
    f = _target_dev(db_conn, grid.release_id, cid)
    assert float(f.dev_pipeline_people_800m) == pytest.approx(300.0, abs=1.0)
    assert f.dev_projects_800m == 1


def test_old_completions_are_stock_not_pipeline(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    # Completed before completed_since_year (2050): already in the
    # observed CLUE stock — must not count. Completed after: counts.
    _add_project(
        db_conn,
        grid.release_id,
        src,
        cid,
        "T-OLD",
        "COMPLETED",
        400,
        {"resi_dwellings": 100},
        year_completed=2049,
    )
    _add_project(
        db_conn,
        grid.release_id,
        src,
        cid,
        "T-NEW",
        "COMPLETED",
        400,
        {"resi_dwellings": 100},
        year_completed=2051,
    )

    _build(db_conn, src)
    f = _target_dev(db_conn, grid.release_id, cid)
    # Only T-NEW: 100 × 2.0 × 1.0 × 0.5 = 100.
    assert float(f.dev_pipeline_people_800m) == pytest.approx(100.0, abs=0.5)
    assert f.dev_projects_800m == 1


def test_no_pipeline_is_observed_zero_not_null(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)

    _build(db_conn, src)
    f = _target_dev(db_conn, grid.release_id, cid)
    # Complete unsuppressed dataset: empty catchment is a real 0
    # (migration 0013) — unlike jobs_800m, where NULL means unknown.
    assert float(f.dev_pipeline_people_800m) == 0
    assert f.dev_projects_800m == 0


def test_unknown_status_fails_loudly(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_project(
        db_conn, grid.release_id, src, cid, "T-1", "MYSTERY_STATUS", 400, {"resi_dwellings": 100}
    )

    with pytest.raises(ValueError, match="MYSTERY_STATUS"):
        _build(db_conn, src)


def test_raises_without_active_release(db_conn, tmp_path):
    src = _fake_release(db_conn, tmp_path)
    db_conn.execute(text("DELETE FROM analytics.active_release"))
    with pytest.raises(ValueError, match="No active grid release"):
        _build(db_conn, src)
