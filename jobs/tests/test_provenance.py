"""Provenance recording against a real PostGIS database.

Requires migration 0002 applied (see db/README.md). Skips cleanly if no
database is reachable, so `pytest` still works offline; CI always runs
these against a live postgis service (see .github/workflows/ci.yml).

Every test runs inside a transaction that is rolled back at the end —
none of this leaves rows behind in a real database.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import adopt_snapshot, write_snapshot

# Deliberately a fictional future date, not "today" — object_path is
# date-keyed, and a real date here would collide with genuine same-day
# CLI usage of these same registry sources against a shared dev
# database (transactions roll back, but ON CONFLICT still matches an
# already-committed real row and pollutes its ingestion_run history).
FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
FIXED_RETRIEVED_DATE = dt.date(2099, 1, 1)


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


def test_upsert_and_record_release_round_trip(db_conn, tmp_path):
    registry = load_registry()
    source = registry.get("pedestrian_sensor_locations")

    raw_root = tmp_path / "raw"
    data_file = tmp_path / "download.json"
    data_file.write_text('[{"a": 1}]')
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

    dataset_row = db_conn.execute(
        text("SELECT provider, status FROM source.dataset WHERE id = :id"),
        {"id": source.id},
    ).one()
    assert dataset_row.provider == "city_of_melbourne"
    assert dataset_row.status == "active"

    release_row = db_conn.execute(
        text(
            "SELECT dataset_id, retrieval_mode, file_count, total_size_bytes, object_path "
            "FROM source.dataset_release WHERE release_id = :id"
        ),
        {"id": release_id},
    ).one()
    assert release_row.dataset_id == source.id
    assert release_row.retrieval_mode == "api_export"
    assert release_row.file_count == 1
    assert release_row.object_path == (f"city_of_melbourne/{source.id}/retrieved_date=2099-01-01")

    files = db_conn.execute(
        text(
            "SELECT file_name, size_bytes FROM source.dataset_release_file WHERE release_id = :id"
        ),
        {"id": release_id},
    ).all()
    assert [f.file_name for f in files] == ["data.json"]

    # filter by release_id, not dataset_id: a dataset can have many
    # historical ingestion_run rows (that's the point of the table)
    run_row = db_conn.execute(
        text("SELECT outcome, release_id FROM source.ingestion_run WHERE release_id = :id"),
        {"id": release_id},
    ).one()
    assert run_row.outcome == "success"
    assert run_row.release_id == release_id


def test_rerun_same_day_upserts_release_not_duplicates(db_conn, tmp_path):
    """Re-ingesting the same day must produce ONE release row, not two —
    this is the DB-level mirror of write_snapshot's own overwrite
    semantics (architecture.md: raw snapshot layout is date-keyed)."""
    registry = load_registry()
    source = registry.get("pedestrian_sensor_locations")
    raw_root = tmp_path / "raw"

    def ingest_once(content: str) -> Path:
        data_file = tmp_path / f"download-{content}.json"
        data_file.write_text(content)
        return write_snapshot(
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

    snapshot_dir = ingest_once("[1]")
    upsert_dataset(db_conn, registry, source)
    first_id = record_release(db_conn, source, snapshot_dir, raw_root)

    snapshot_dir = ingest_once("[1, 2]")  # different content, same day
    second_id = record_release(db_conn, source, snapshot_dir, raw_root)

    assert first_id == second_id
    # Scope to THIS test's object_path, not "this dataset has only one
    # release ever" — a dataset legitimately accumulates many releases
    # over time (that's the point of the table); idempotency is keyed
    # on (dataset_id, object_path), which is what UNIQUE enforces.
    object_path = str(snapshot_dir.relative_to(raw_root))
    count = db_conn.execute(
        text(
            "SELECT count(*) FROM source.dataset_release "
            "WHERE dataset_id = :id AND object_path = :path"
        ),
        {"id": source.id, "path": object_path},
    ).scalar_one()
    assert count == 1


def test_manual_adopt_records_multiple_files(db_conn, tmp_path):
    registry = load_registry()
    source = registry.get("transport_activity")
    raw_root = tmp_path / "raw"

    zips = []
    for year in ("2023", "2024"):
        f = tmp_path / f"Archive_{year}.zip"
        f.write_bytes(f"year-{year}".encode())
        zips.append(f)

    snapshot_dir = adopt_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_files=zips,
        export_format=source.export_format,
        fields=source.fields_observed,
        note="test fixture",
        retrieved_date=FIXED_RETRIEVED_DATE,
        now=FIXED_NOW,
    )

    upsert_dataset(db_conn, registry, source)
    release_id = record_release(db_conn, source, snapshot_dir, raw_root)

    manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    assert manifest["retrieval_mode"] == "manual_adopt"

    file_count = db_conn.execute(
        text("SELECT file_count FROM source.dataset_release WHERE release_id = :id"),
        {"id": release_id},
    ).scalar_one()
    assert file_count == 2

    dataset_status = db_conn.execute(
        text("SELECT status FROM source.dataset WHERE id = :id"), {"id": source.id}
    ).scalar_one()
    assert dataset_status == "manual"
