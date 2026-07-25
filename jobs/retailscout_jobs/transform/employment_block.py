"""Load core.employment_block from an employment_by_block raw snapshot.

Source shape (OpenDataSoft CSV export — semicolon-delimited with a UTF-8
BOM, this provider's undocumented format): one row per
(census_year, block_id), with clue_small_area, 20 ANZSIC-division job
counts, and total_jobs_in_block.

SUPPRESSION handling is the whole point (architecture.md invariant 4):
an EMPTY cell is a suppressed count → stored as NULL; "0" is an observed
zero → stored as 0. `_int_or_none` makes that distinction; the loader
never coalesces a suppressed value to 0, and never reconstructs a
suppressed total by summing the (also partially-suppressed) industry
columns.

Idempotent via upsert on the real natural key (census_year, block_id) —
13,519 distinct in the real file. The 20 industry counts go to
jobs_by_industry jsonb (JSON null vs 0 preserves suppression).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Fixed columns; everything between clue_small_area and total_jobs_in_block
# is an ANZSIC-division job count.
_LEADING = ("census_year", "block_id", "clue_small_area")
_TOTAL = "total_jobs_in_block"

_INSERT_SQL = text("""
    INSERT INTO core.employment_block
        (census_year, block_id, clue_small_area, total_jobs, jobs_by_industry, source_release_id)
    VALUES
        (:census_year, :block_id, :clue_small_area, :total_jobs,
         CAST(:jobs_by_industry AS jsonb), :release_id)
    ON CONFLICT (census_year, block_id) DO UPDATE SET
        clue_small_area  = EXCLUDED.clue_small_area,
        total_jobs       = EXCLUDED.total_jobs,
        jobs_by_industry = EXCLUDED.jobs_by_industry,
        source_release_id = EXCLUDED.source_release_id,
        loaded_at        = now()
""")


def _int_or_none(value: str) -> int | None:
    """Empty cell -> None (suppressed); otherwise int. '0' stays 0."""
    value = value.strip()
    return int(value) if value else None


def load(conn: Connection, snapshot_dir: Path, release_id: int) -> int:
    data_file = snapshot_dir / "data.csv"
    with open(data_file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        industry_cols = [c for c in reader.fieldnames if c not in _LEADING and c != _TOTAL]
        params = []
        for row in reader:
            params.append(
                {
                    "census_year": int(row["census_year"]),
                    "block_id": int(row["block_id"]),
                    "clue_small_area": row["clue_small_area"],
                    "total_jobs": _int_or_none(row[_TOTAL]),
                    "jobs_by_industry": json.dumps(
                        {c: _int_or_none(row[c]) for c in industry_cols}
                    ),
                    "release_id": release_id,
                }
            )

    if not params:
        raise ValueError(f"No records in {data_file}")

    conn.execute(_INSERT_SQL, params)
    return len(params)
