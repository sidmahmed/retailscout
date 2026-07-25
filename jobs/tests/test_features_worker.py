"""Worker-demand feature loader, against a real PostGIS database.

Same isolation as the other DB-backed tests. Fixture CLUE blocks +
employment rows use a fictional census_year (2099) sentinel and a
fictional block_id range, so the real 603 clue_blocks / 13,519
employment rows never contribute: real blocks overlapping the fixture
catchments have no census_year=2099 employment row, so they LEFT JOIN to
NULL and are excluded.

Fixture blocks are built around the target cell's REAL centroid (via
ST_Expand) so the area-weighting outcome is predictable: a block small
enough to sit fully inside the catchment contributes its whole total
(overlap fraction = 1); a block larger than the catchment contributes a
strict fraction.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.features.grid import build_grid
from retailscout_jobs.features.worker_features import build_worker_features
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
YEAR = 2099
RES = 9
FIXTURE_BOUNDARY_WKT = (
    "MULTIPOLYGON(((144.95 -37.82, 144.97 -37.82, 144.97 -37.80, 144.95 -37.80, 144.95 -37.82)))"
)
TARGET = (144.96, -37.81)
SMALL_DEG = 0.0005  # ~90 m block — fully inside the 400 m catchment
BIG_DEG = 0.02  # ~3 km block — larger than the 800 m catchment


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


def _add_block_around_centroid(
    db_conn, grid_release: int, src: int, cell_id: str, block_id: int, deg: float
) -> None:
    """A square CLUE block centred on the target cell's real centroid."""
    db_conn.execute(
        text("""
            INSERT INTO core.clue_block
                (block_id, region_name, area_name, centroid, geom, source_release_id)
            SELECT :bid, 'Test', 'Test', ac.centroid, ST_Expand(ac.centroid, :deg), :src
            FROM analytics.analysis_cell ac
            WHERE ac.release_id = :gr AND ac.cell_id = :cid
        """),
        {"bid": block_id, "deg": deg, "src": src, "gr": grid_release, "cid": cell_id},
    )


def _add_employment(db_conn, src: int, block_id: int, total_jobs: int | None) -> None:
    db_conn.execute(
        text("""
            INSERT INTO core.employment_block
                (census_year, block_id, clue_small_area, total_jobs, jobs_by_industry,
                 source_release_id)
            VALUES (:y, :bid, 'Test', :total, '{}'::jsonb, :src)
        """),
        {"y": YEAR, "bid": block_id, "total": total_jobs, "src": src},
    )


def _target_jobs(db_conn, release_id: int, cell_id: str):
    return db_conn.execute(
        text(
            "SELECT jobs_400m, jobs_800m FROM analytics.location_feature "
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


def test_fully_contained_block_allocates_its_whole_total(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_block_around_centroid(db_conn, grid.release_id, src, cid, 900001, SMALL_DEG)
    _add_employment(db_conn, src, 900001, 1000)

    build_worker_features(db_conn, feature_version="v1", census_year=YEAR)
    f = _target_jobs(db_conn, grid.release_id, cid)
    assert f.jobs_400m == 1000  # block fully inside the 400 m catchment -> fraction 1
    assert f.jobs_800m == 1000  # and inside the 800 m catchment too


def test_suppressed_block_yields_null_not_zero(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_block_around_centroid(db_conn, grid.release_id, src, cid, 900001, SMALL_DEG)
    _add_employment(db_conn, src, 900001, None)  # suppressed total

    build_worker_features(db_conn, feature_version="v1", census_year=YEAR)
    f = _target_jobs(db_conn, grid.release_id, cid)
    assert f.jobs_400m is None  # no known-job block in range -> unknown, not 0
    assert f.jobs_800m is None


def test_observed_zero_is_zero_not_null(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    _add_block_around_centroid(db_conn, grid.release_id, src, cid, 900001, SMALL_DEG)
    _add_employment(db_conn, src, 900001, 0)  # observed zero jobs

    build_worker_features(db_conn, feature_version="v1", census_year=YEAR)
    f = _target_jobs(db_conn, grid.release_id, cid)
    assert f.jobs_400m == 0  # observed zero, distinct from suppressed NULL
    assert f.jobs_800m == 0


def test_partial_overlap_is_area_weighted(db_conn, tmp_path):
    grid, src, cid = _setup(db_conn, tmp_path)
    # Block far larger than either catchment, centred on the cell: each
    # catchment captures only its circular slice of the block's jobs.
    _add_block_around_centroid(db_conn, grid.release_id, src, cid, 900002, BIG_DEG)
    _add_employment(db_conn, src, 900002, 10000)

    build_worker_features(db_conn, feature_version="v1", census_year=YEAR)
    f = _target_jobs(db_conn, grid.release_id, cid)
    assert 0 < f.jobs_400m < f.jobs_800m < 10000  # weighted, monotonic, sub-total
    # 800 m circle is 4x the 400 m circle's area -> ~4x the allocated jobs.
    assert f.jobs_800m == pytest.approx(f.jobs_400m * 4, rel=0.15)


def test_raises_without_active_release(db_conn, tmp_path):
    _fake_release(db_conn, tmp_path)
    db_conn.execute(text("DELETE FROM analytics.active_release"))
    with pytest.raises(ValueError, match="No active grid release"):
        build_worker_features(db_conn, feature_version="v1", census_year=YEAR)
