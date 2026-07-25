"""Business/competition feature loader, against a real PostGIS database.

Same isolation as the other DB-backed tests: skips if no DB, rolls back
its own transaction. Two sentinels keep it from colliding with real data
on a shared dev database:
  - a fictional provenance date (FIXED_NOW, 2099) for the source release;
  - a fictional census_year (2099) for the fixture businesses, passed to
    build_business_features, so the real ~413k core.business_establishment
    rows (census_year <= 2024) are excluded by the year filter without
    deleting anything.

The loader integrates the whole analytics chain, so the test builds it
for real: fixture boundary -> build_grid (grid + active release) ->
fixture businesses -> build_business_features, then asserts counts on the
cell that actually contains a known point.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.features.business_features import build_business_features
from retailscout_jobs.features.grid import build_grid
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
FIXTURE_CENSUS_YEAR = 2099  # no real row uses this — clean isolation from the 413k real rows

RES = 9  # coarse grid over the fixture square keeps the test fast
FIXTURE_BOUNDARY_WKT = (
    "MULTIPOLYGON(((144.95 -37.82, 144.97 -37.82, 144.97 -37.80, 144.95 -37.80, 144.95 -37.82)))"
)
TARGET = (144.96, -37.81)  # lng, lat — near the centre of the fixture square
FAR = (144.969, -37.801)  # opposite corner, > 400 m from the target cell centroid


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


def _add_business(db_conn, release_id: int, code: str, lng: float, lat: float) -> None:
    db_conn.execute(
        text("""
            INSERT INTO core.business_establishment
                (census_year, industry_anzsic4_code, geom, source_release_id)
            VALUES (:year, :code,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :release_id)
        """),
        {
            "year": FIXTURE_CENSUS_YEAR,
            "code": code,
            "lng": lng,
            "lat": lat,
            "release_id": release_id,
        },
    )


def _target_cell_features(db_conn, release_id: int):
    return db_conn.execute(
        text("""
            SELECT cafe_restaurant_400m, takeaway_food_400m, bar_pub_400m,
                   retail_400m, complementary_400m
            FROM analytics.location_feature lf
            JOIN analytics.analysis_cell ac USING (release_id, cell_id)
            WHERE lf.release_id = :r
              AND ST_Contains(ac.geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
        """),
        {"r": release_id, "lng": TARGET[0], "lat": TARGET[1]},
    ).one()


def _setup_grid_and_businesses(db_conn, tmp_path):
    release_id = _fake_release(db_conn, tmp_path)
    _install_boundary(db_conn, release_id)
    grid = build_grid(db_conn, resolution=RES)
    # Competitor mix AT the target point (all within the containing cell,
    # hence within 400 m of its centroid): 2 café/restaurant, 1 takeaway,
    # 1 bar, 1 retail, 1 complementary; plus a vacant and an unmapped code
    # that must be counted nowhere.
    for code in ["4511", "4511", "4512", "4520", "4251", "6931", "0000", "9511"]:
        _add_business(db_conn, release_id, code, TARGET[0], TARGET[1])
    return grid


def test_counts_match_the_known_competitor_mix(db_conn, tmp_path):
    grid = _setup_grid_and_businesses(db_conn, tmp_path)
    result = build_business_features(db_conn, feature_version="v1", census_year=FIXTURE_CENSUS_YEAR)
    assert result.release_id == grid.release_id
    assert result.cells_written == grid.cell_count  # every cell gets a row

    f = _target_cell_features(db_conn, grid.release_id)
    assert f.cafe_restaurant_400m == 2
    assert f.takeaway_food_400m == 1
    assert f.bar_pub_400m == 1
    assert f.retail_400m == 1
    assert f.complementary_400m == 1  # 0000 (vacant) and 9511 (unmapped) counted nowhere


def test_far_business_is_excluded_from_the_target_cell(db_conn, tmp_path):
    release_id = _fake_release(db_conn, tmp_path)
    _install_boundary(db_conn, release_id)
    grid = build_grid(db_conn, resolution=RES)
    _add_business(db_conn, release_id, "4511", TARGET[0], TARGET[1])  # in range
    _add_business(db_conn, release_id, "4511", FAR[0], FAR[1])  # out of range of target cell
    build_business_features(db_conn, feature_version="v1", census_year=FIXTURE_CENSUS_YEAR)

    f = _target_cell_features(db_conn, grid.release_id)
    assert f.cafe_restaurant_400m == 1  # only the near one


def test_cells_with_no_businesses_get_zero_not_null(db_conn, tmp_path):
    release_id = _fake_release(db_conn, tmp_path)
    _install_boundary(db_conn, release_id)
    grid = build_grid(db_conn, resolution=RES)
    # no businesses at all for FIXTURE_CENSUS_YEAR
    build_business_features(db_conn, feature_version="v1", census_year=FIXTURE_CENSUS_YEAR)

    nulls = db_conn.execute(
        text("""
            SELECT count(*) FROM analytics.location_feature
            WHERE release_id = :r AND cafe_restaurant_400m IS NULL
        """),
        {"r": grid.release_id},
    ).scalar_one()
    assert nulls == 0  # 0 is observed ("none in range"), never NULL


def test_is_idempotent(db_conn, tmp_path):
    grid = _setup_grid_and_businesses(db_conn, tmp_path)
    build_business_features(db_conn, feature_version="v1", census_year=FIXTURE_CENSUS_YEAR)
    build_business_features(db_conn, feature_version="v1", census_year=FIXTURE_CENSUS_YEAR)

    f = _target_cell_features(db_conn, grid.release_id)
    assert f.cafe_restaurant_400m == 2  # unchanged by re-running
    n_rows = db_conn.execute(
        text(
            "SELECT count(*) FROM analytics.location_feature "
            "WHERE release_id = :r AND feature_version = 'v1'"
        ),
        {"r": grid.release_id},
    ).scalar_one()
    assert n_rows == grid.cell_count  # no duplicate rows


def test_raises_without_active_release(db_conn, tmp_path):
    # A fake release exists but no grid was built, so active_release is empty.
    _fake_release(db_conn, tmp_path)
    db_conn.execute(text("DELETE FROM analytics.active_release"))
    with pytest.raises(ValueError, match="No active grid release"):
        build_business_features(db_conn, feature_version="v1", census_year=FIXTURE_CENSUS_YEAR)
