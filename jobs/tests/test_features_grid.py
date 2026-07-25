"""Hex analysis-grid builder, against a real PostGIS database.

Same isolation pattern as the transform tests: skips if no DB is
reachable, rolls back its own transaction, and uses a fictional
sentinel date for provenance so it never collides with a real same-day
ingest on a shared dev database.

build_grid() reads core.municipal_boundary (union of all its rows) and
flips the singleton analytics.active_release pointer, so each test
first replaces whatever boundary is loaded with its own small fixture
square inside the rolled-back transaction — it must not depend on the
real municipality being present, and its active_release changes are
discarded on rollback. A modest resolution (RES) keeps cell counts
small and the tests fast; correctness is resolution-independent.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.features.grid import DEFAULT_RESOLUTION, build_grid
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)

# Coarser than the production default (10) so the fixture square yields
# only a few dozen cells — fast, and correctness does not depend on it.
RES = 9

# Small square "municipality" around the CBD (same shape as
# test_transform_municipal_boundary.py's fixture).
FIXTURE_BOUNDARY_WKT = (
    "MULTIPOLYGON(((144.95 -37.82, 144.97 -37.82, 144.97 -37.80, 144.95 -37.80, 144.95 -37.82)))"
)
INSIDE_POINT = (144.96, -37.81)  # lng, lat — inside the square
OUTSIDE_POINT = (145.10, -37.81)  # well outside it


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


def _fake_boundary_release(db_conn, tmp_path) -> int:
    """A real source.dataset_release for municipal_boundary to satisfy
    the FK chain (core.municipal_boundary and analytics.data_release
    both reference it), keyed on the fictional sentinel date."""
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


def _install_fixture_boundary(db_conn, release_id: int) -> None:
    """Replace whatever is in core.municipal_boundary (rolled back after)
    with a single small fixture square tagged with a release this test
    created — so build_grid's ST_Union sees only this square."""
    db_conn.execute(text("DELETE FROM core.municipal_boundary"))
    db_conn.execute(
        text("""
            INSERT INTO core.municipal_boundary (id, name, geom, source_release_id)
            VALUES (999, 'Test Municipality',
                    ST_SetSRID(ST_GeomFromText(:wkt), 4326), :release_id)
        """),
        {"wkt": FIXTURE_BOUNDARY_WKT, "release_id": release_id},
    )


def _setup(db_conn, tmp_path) -> int:
    release_id = _fake_boundary_release(db_conn, tmp_path)
    _install_fixture_boundary(db_conn, release_id)
    return release_id


def test_build_creates_published_activated_release(db_conn, tmp_path):
    _setup(db_conn, tmp_path)
    result = build_grid(db_conn, resolution=RES)

    assert result.cell_count > 0
    assert result.resolution == RES
    assert result.activated is True

    row = db_conn.execute(
        text(
            "SELECT status, grid_resolution, published_at FROM analytics.data_release "
            "WHERE release_id = :r"
        ),
        {"r": result.release_id},
    ).one()
    assert row.status == "published"
    assert row.grid_resolution == RES
    assert row.published_at is not None

    active = db_conn.execute(
        text("SELECT release_id FROM analytics.active_release WHERE only_one")
    ).scalar_one()
    assert active == result.release_id


def test_uses_default_resolution_when_unspecified(db_conn, tmp_path):
    _setup(db_conn, tmp_path)
    result = build_grid(db_conn)
    assert result.resolution == DEFAULT_RESOLUTION


def test_all_cells_intersect_the_boundary(db_conn, tmp_path):
    _setup(db_conn, tmp_path)
    result = build_grid(db_conn, resolution=RES)

    not_touching = db_conn.execute(
        text("""
            SELECT count(*) FROM analytics.analysis_cell ac
            WHERE ac.release_id = :r
              AND NOT EXISTS (
                  SELECT 1 FROM core.municipal_boundary b
                  WHERE ST_Intersects(b.geom, ac.geom))
        """),
        {"r": result.release_id},
    ).scalar_one()
    assert not_touching == 0


def test_grid_fully_covers_the_boundary(db_conn, tmp_path):
    """No interior gaps: every point inside the boundary is inside some
    cell, so a valid in-boundary click can never fall into no cell."""
    _setup(db_conn, tmp_path)
    result = build_grid(db_conn, resolution=RES)

    cov = db_conn.execute(
        text("""
            SELECT ST_Area(b.geom) AS boundary,
                   ST_Area(ST_Intersection(ST_Union(ac.geom), b.geom)) AS covered
            FROM analytics.analysis_cell ac, core.municipal_boundary b
            WHERE ac.release_id = :r
            GROUP BY b.geom
        """),
        {"r": result.release_id},
    ).one()
    assert cov.covered / cov.boundary > 0.9999


def test_point_maps_to_exactly_one_cell(db_conn, tmp_path):
    """ADR-002: a valid point maps to exactly one grid cell; an
    out-of-boundary point maps to none (the grid is clipped)."""
    _setup(db_conn, tmp_path)
    result = build_grid(db_conn, resolution=RES)

    inside = db_conn.execute(
        text("""
            SELECT count(*) FROM analytics.analysis_cell
            WHERE release_id = :r
              AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
        """),
        {"r": result.release_id, "lng": INSIDE_POINT[0], "lat": INSIDE_POINT[1]},
    ).scalar_one()
    outside = db_conn.execute(
        text("""
            SELECT count(*) FROM analytics.analysis_cell
            WHERE release_id = :r
              AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
        """),
        {"r": result.release_id, "lng": OUTSIDE_POINT[0], "lat": OUTSIDE_POINT[1]},
    ).scalar_one()
    assert inside == 1
    assert outside == 0


def test_second_build_flips_active_and_supersedes_previous(db_conn, tmp_path):
    """Atomic release swap (invariant 3): the new build becomes active,
    the previous one is marked superseded, and its cells are retained so
    rollback is lossless."""
    _setup(db_conn, tmp_path)
    first = build_grid(db_conn, resolution=RES)
    second = build_grid(db_conn, resolution=RES)

    active = db_conn.execute(
        text("SELECT release_id FROM analytics.active_release WHERE only_one")
    ).scalar_one()
    assert active == second.release_id

    statuses = dict(
        db_conn.execute(
            text(
                "SELECT release_id, status FROM analytics.data_release WHERE release_id IN (:a, :b)"
            ),
            {"a": first.release_id, "b": second.release_id},
        ).all()
    )
    assert statuses[first.release_id] == "superseded"
    assert statuses[second.release_id] == "published"

    first_cells = db_conn.execute(
        text("SELECT count(*) FROM analytics.analysis_cell WHERE release_id = :r"),
        {"r": first.release_id},
    ).scalar_one()
    assert first_cells == first.cell_count  # old release's cells kept


def test_no_activate_leaves_active_pointer_untouched(db_conn, tmp_path):
    _setup(db_conn, tmp_path)
    baseline = build_grid(db_conn, resolution=RES)  # this one is active
    result = build_grid(db_conn, resolution=RES, activate=False)
    assert result.activated is False

    active = db_conn.execute(
        text("SELECT release_id FROM analytics.active_release WHERE only_one")
    ).scalar_one()
    assert active == baseline.release_id  # unchanged — not flipped to the new one

    status = db_conn.execute(
        text("SELECT status FROM analytics.data_release WHERE release_id = :r"),
        {"r": result.release_id},
    ).scalar_one()
    assert status == "published"  # built and published, just not made live


def test_raises_when_boundary_is_empty(db_conn, tmp_path):
    _fake_boundary_release(db_conn, tmp_path)
    db_conn.execute(text("DELETE FROM core.municipal_boundary"))
    with pytest.raises(ValueError, match="core.municipal_boundary is empty"):
        build_grid(db_conn, resolution=RES)
