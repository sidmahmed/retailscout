"""transport_stop (PTV GTFS) staging loader, against a real PostGIS database.

Same isolation pattern as the other transform/provenance tests: skips
if no DB is reachable, rolls back its own transaction, uses a
fictional sentinel date for provenance so it never collides with a
real same-day ingest of this source on a shared dev database.

Unlike the other loaders, transport_stop.load() itself queries
core.municipal_boundary (for the bbox pre-filter and the precise
ST_DWithin prune) — so this test replaces whatever boundary is
currently in the table with its own small fixture square inside the
same rolled-back transaction, rather than depending on the real
municipality happening to be loaded. This mirrors the fixture square
used in test_transform_municipal_boundary.py for consistency.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot
from retailscout_jobs.transform.transport_stop import load

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)

# Small square fixture boundary (same shape as test_transform_municipal_boundary.py)
FIXTURE_BOUNDARY_WKT = (
    "MULTIPOLYGON(((144.95 -37.82, 144.97 -37.82, 144.97 -37.80, 144.95 -37.80, 144.95 -37.82)))"
)

STOPS_HEADER = [
    "stop_id",
    "stop_name",
    "stop_lat",
    "stop_lon",
    "stop_url",
    "location_type",
    "parent_station",
    "wheelchair_boarding",
    "level_id",
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


def _install_fixture_boundary(db_conn, release_id: int) -> None:
    """Replaces whatever is in core.municipal_boundary for the duration
    of this test's transaction (rolled back after) with a small fixture
    square, tagged with a release_id this same test already created —
    no dependency on any pre-existing row in the shared dev database."""
    db_conn.execute(text("DELETE FROM core.municipal_boundary"))
    db_conn.execute(
        text("""
            INSERT INTO core.municipal_boundary (id, name, geom, source_release_id)
            VALUES (999, 'Test Municipality',
                    ST_SetSRID(ST_GeomFromText(:wkt), 4326), :release_id)
        """),
        {"wkt": FIXTURE_BOUNDARY_WKT, "release_id": release_id},
    )


def _stops_csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=STOPS_HEADER)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _build_gtfs_zip(path: Path, bundles: dict[str, list[dict[str, str]]]) -> None:
    """bundles: {folder_number: [stop_row, ...]} -> nested zip matching
    the real PTV archive shape (outer zip / folder / google_transit.zip / stops.txt)."""
    with zipfile.ZipFile(path, "w") as outer:
        for folder, rows in bundles.items():
            inner_buf = io.BytesIO()
            with zipfile.ZipFile(inner_buf, "w") as inner:
                inner.writestr("stops.txt", _stops_csv(rows))
            outer.writestr(f"{folder}/google_transit.zip", inner_buf.getvalue())


def _stop_row(
    stop_id: str,
    name: str,
    lon: float,
    lat: float,
    location_type: str = "",
    wheelchair: str = "",
) -> dict[str, str]:
    return {
        "stop_id": stop_id,
        "stop_name": name,
        "stop_lat": str(lat),
        "stop_lon": str(lon),
        "stop_url": "",
        "location_type": location_type,
        "parent_station": "",
        "wheelchair_boarding": wheelchair,
        "level_id": "",
    }


def _fake_release(db_conn, tmp_path, bundles: dict[str, list[dict[str, str]]]):
    registry = load_registry()
    source = registry.get("ptv_gtfs")
    raw_root = tmp_path / "raw"
    data_file = tmp_path / "data.zip"
    _build_gtfs_zip(data_file, bundles)
    snapshot_dir = write_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_url="https://example.test/gtfs.zip",
        data_file=data_file,
        export_format="zip",
        fields=None,
        now=FIXED_NOW,
    )
    upsert_dataset(db_conn, registry, source)
    release_id = record_release(db_conn, source, snapshot_dir, raw_root)
    return release_id, snapshot_dir


def test_load_filters_by_boundary_and_location_type(db_conn, tmp_path):
    bundles = {
        "4": [  # bus
            _stop_row("B1", "Inside Stop", 144.96, -37.81),  # inside fixture square
            _stop_row("B2", "Far Away Stop", 145.50, -37.81),  # nowhere near it
            _stop_row("B3", "Station Row", 144.96, -37.81, location_type="1"),  # not boardable
        ],
    }
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path, bundles)
    _install_fixture_boundary(db_conn, release_id)

    count = load(db_conn, snapshot_dir, release_id)
    assert count == 1  # only B1

    stop_ids = {
        r[0] for r in db_conn.execute(text("SELECT stop_id FROM core.transport_stop")).all()
    }
    assert stop_ids == {"B1"}


def test_load_wheelchair_boarding_mapping(db_conn, tmp_path):
    bundles = {
        "4": [
            _stop_row("W1", "Yes", 144.96, -37.81, wheelchair="1"),
            _stop_row("W2", "No", 144.965, -37.815, wheelchair="2"),
            _stop_row("W3", "Unknown", 144.955, -37.805, wheelchair=""),
        ],
    }
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path, bundles)
    _install_fixture_boundary(db_conn, release_id)
    load(db_conn, snapshot_dir, release_id)

    rows = dict(
        db_conn.execute(text("SELECT stop_id, wheelchair_boarding FROM core.transport_stop")).all()
    )
    assert rows["W1"] is True
    assert rows["W2"] is False
    assert rows["W3"] is None


def test_load_deterministic_collision_resolution_by_processing_order(db_conn, tmp_path):
    """Same stop_id in two bundles -> the later-processed bundle wins
    (metro_train after bus, per _PROCESSING_ORDER) — not incidental."""
    bundles = {
        "4": [_stop_row("SHARED", "Shared Stop (bus)", 144.96, -37.81)],  # bus
        "2": [_stop_row("SHARED", "Shared Stop (train)", 144.96, -37.81)],  # metro_train
    }
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path, bundles)
    _install_fixture_boundary(db_conn, release_id)
    load(db_conn, snapshot_dir, release_id)

    mode = db_conn.execute(
        text("SELECT mode FROM core.transport_stop WHERE stop_id = 'SHARED'")
    ).scalar_one()
    assert mode == "metro_train"  # 2 (metro_train) processed after 4 (bus)


def test_load_is_idempotent_full_replace(db_conn, tmp_path):
    bundles = {"4": [_stop_row("R1", "Stop", 144.96, -37.81)]}
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path, bundles)
    _install_fixture_boundary(db_conn, release_id)
    load(db_conn, snapshot_dir, release_id)
    load(db_conn, snapshot_dir, release_id)

    count = db_conn.execute(text("SELECT count(*) FROM core.transport_stop")).scalar_one()
    assert count == 1


def test_load_raises_when_nothing_survives_the_filter(db_conn, tmp_path):
    bundles = {"4": [_stop_row("OUT", "Nowhere near it", 150.0, -30.0)]}
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path, bundles)
    _install_fixture_boundary(db_conn, release_id)
    with pytest.raises(ValueError, match="No stops found"):
        load(db_conn, snapshot_dir, release_id)
