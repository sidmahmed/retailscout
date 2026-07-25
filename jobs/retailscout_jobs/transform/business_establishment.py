"""Load core.business_establishment from a business_establishments raw snapshot.

Source shape (confirmed by profiling the FULL real 2026-07-25 snapshot,
413,550 rows — not a sample): CSV, semicolon-delimited with a UTF-8 BOM
(see jobs/registry/sources.yaml). Columns:
census_year;block_id;property_id;base_property_id;clue_small_area;
trading_name;business_address;industry_anzsic4_code;
industry_anzsic4_description;longitude;latitude;point

Full-file profiling findings that shaped this loader:
- census_year/block_id/property_id/base_property_id are never null and
  always parse as integers.
- 4,785 rows (~1.2%) have no longitude/latitude — geom is NULL for
  those, matching the schema's nullable geometry column. Never invent
  a placeholder point.
- trading_name is null for 127 rows, business_address for 1 — both
  already nullable columns.
- NO STABLE NATURAL KEY: jobs/registry/sources.yaml already flagged
  this as a risk to verify, and profiling confirms it —
  (census_year, property_id, trading_name, industry_anzsic4_code)
  has 8,344 groups with more than one row out of 379,558 distinct
  groups. There is no reliable ON CONFLICT target.

IDEMPOTENCY STRATEGY (different from every other loader so far):
because there is no natural key, this loader deletes all rows tagged
with the target release_id, then bulk-inserts — idempotent for
RE-RUNNING THE SAME release, not for deduplicating across releases.
Re-ingesting an unchanged annual CLUE file on a different day will
currently produce a second full copy of that census_year under a new
release_id. Deduplicating identity across releases needs a deliberate
entity-matching strategy (the same one migration 0003's docstring
already defers for valid_from/valid_to) — out of scope here.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

BATCH_SIZE = 5_000

_DELETE_SQL = text("DELETE FROM core.business_establishment WHERE source_release_id = :release_id")

_INSERT_SQL = text("""
    INSERT INTO core.business_establishment
        (census_year, block_id, property_id, base_property_id, clue_small_area,
         trading_name, business_address, industry_anzsic4_code,
         industry_anzsic4_description, geom, source_release_id)
    VALUES
        (:census_year, :block_id, :property_id, :base_property_id, :clue_small_area,
         :trading_name, :business_address, :industry_anzsic4_code,
         :industry_anzsic4_description,
         ST_SetSRID(ST_GeomFromText(:geom_wkt), 4326),
         :release_id)
""")


def _row_to_params(row: dict[str, str], release_id: int) -> dict:
    # WKT is computed here, not in SQL: SQLAlchemy's batched multi-row
    # INSERT (insertmanyvalues) does not correctly scope a bind
    # parameter referenced twice inside a CASE/expression per row —
    # observed directly (AmbiguousParameter, then silently dropped
    # params) against the real 413k-row file. ST_GeomFromText(NULL) is
    # NULL naturally in PostGIS, so a plain nullable geom_wkt column
    # value needs no CASE at all.
    geom_wkt = (
        f"POINT({row['longitude']} {row['latitude']})"
        if row["longitude"] and row["latitude"]
        else None
    )
    return {
        "census_year": int(row["census_year"]),
        "block_id": int(row["block_id"]),
        "property_id": int(row["property_id"]),
        "base_property_id": int(row["base_property_id"]),
        "clue_small_area": row["clue_small_area"] or None,
        "trading_name": row["trading_name"] or None,
        "business_address": row["business_address"] or None,
        "industry_anzsic4_code": row["industry_anzsic4_code"] or None,
        "industry_anzsic4_description": row["industry_anzsic4_description"] or None,
        "geom_wkt": geom_wkt,
        "release_id": release_id,
    }


def load(conn: Connection, snapshot_dir: Path, release_id: int) -> int:
    data_file = snapshot_dir / "data.csv"
    conn.execute(_DELETE_SQL, {"release_id": release_id})

    total = 0
    batch: list[dict] = []
    with open(data_file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            batch.append(_row_to_params(row, release_id))
            if len(batch) >= BATCH_SIZE:
                conn.execute(_INSERT_SQL, batch)
                total += len(batch)
                batch = []
        if batch:
            conn.execute(_INSERT_SQL, batch)
            total += len(batch)

    if total == 0:
        raise ValueError(f"No rows in {data_file}")
    return total
