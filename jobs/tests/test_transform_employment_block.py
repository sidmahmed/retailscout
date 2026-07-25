"""employment_block staging loader, against a real PostGIS database.

Same isolation pattern as the other transform tests. Uses a fictional
census_year (2099) sentinel so fixtures never collide with the real
13,519 rows on a shared dev database, and asserts the load-bearing
property of this table: a SUPPRESSED cell (empty) stays NULL, an
observed "0" stays 0 — never conflated (invariant 4).
"""

from __future__ import annotations

import csv
import datetime as dt
import io

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot
from retailscout_jobs.transform.employment_block import load

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
YEAR = 2099  # sentinel — no real row uses it

HEADER = [
    "census_year",
    "block_id",
    "clue_small_area",
    "accommodation",
    "retail_trade",
    "manufacturing",
    "total_jobs_in_block",
]

# block 244: total suppressed, retail suppressed, manufacturing observed 0
# block 501: total observed 12, accommodation observed 0, manufacturing suppressed
ROWS = [
    [YEAR, 244, "Carlton", "5", "", "0", ""],
    [YEAR, 501, "West Melbourne", "0", "12", "", "12"],
]


def _csv_bytes(header, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


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


def _fake_release(db_conn, tmp_path, rows=ROWS):
    registry = load_registry()
    source = registry.get("employment_by_block")
    raw_root = tmp_path / "raw"
    data_file = tmp_path / "data.csv"
    data_file.write_text(_csv_bytes(HEADER, rows), encoding="utf-8-sig")
    snapshot_dir = write_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_url="https://example.test/exports/csv",
        data_file=data_file,
        export_format="csv",
        fields=source.fields_observed,
        now=FIXED_NOW,
    )
    upsert_dataset(db_conn, registry, source)
    release_id = record_release(db_conn, source, snapshot_dir, raw_root)
    return release_id, snapshot_dir


def _row(db_conn, block_id: int):
    return db_conn.execute(
        text("""
            SELECT clue_small_area, total_jobs,
                   jobs_by_industry->>'accommodation' AS acc,
                   jobs_by_industry->>'retail_trade'   AS retail,
                   jobs_by_industry->>'manufacturing'  AS manuf
            FROM core.employment_block WHERE census_year = :y AND block_id = :b
        """),
        {"y": YEAR, "b": block_id},
    ).one()


def test_load_preserves_suppression_vs_observed_zero(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    count = load(db_conn, snapshot_dir, release_id)
    assert count == 2

    b244 = _row(db_conn, 244)
    assert b244.total_jobs is None  # empty total -> suppressed -> NULL
    assert b244.retail is None  # empty -> suppressed
    assert b244.manuf == "0"  # observed zero, NOT null
    assert b244.acc == "5"

    b501 = _row(db_conn, 501)
    assert b501.total_jobs == 12
    assert b501.acc == "0"  # observed zero
    assert b501.manuf is None  # suppressed


def test_jobs_by_industry_is_real_json_numbers(db_conn, tmp_path):
    """0 and 5 are JSON numbers (not strings), and suppressed keys are
    JSON null — both queryable as the real distinction."""
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)
    typed = db_conn.execute(
        text("""
            SELECT jsonb_typeof(jobs_by_industry->'manufacturing') AS manuf_type,
                   jsonb_typeof(jobs_by_industry->'retail_trade')  AS retail_type
            FROM core.employment_block WHERE census_year = :y AND block_id = 244
        """),
        {"y": YEAR},
    ).one()
    assert typed.manuf_type == "number"  # observed 0
    assert typed.retail_type == "null"  # suppressed


def test_load_is_idempotent_and_upserts(db_conn, tmp_path):
    release_id, snapshot_dir = _fake_release(db_conn, tmp_path)
    load(db_conn, snapshot_dir, release_id)

    # Re-load with block 244's total now observed as 99 — upsert must apply.
    changed = [[YEAR, 244, "Carlton", "5", "", "0", "99"], ROWS[1]]
    release2, snapshot2 = _fake_release(db_conn, tmp_path, rows=changed)
    load(db_conn, snapshot2, release2)

    count = db_conn.execute(
        text("SELECT count(*) FROM core.employment_block WHERE census_year = :y"),
        {"y": YEAR},
    ).scalar_one()
    assert count == 2  # no duplicate rows
    assert _row(db_conn, 244).total_jobs == 99  # update took effect
