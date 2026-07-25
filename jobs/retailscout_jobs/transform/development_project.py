"""Load core.development_project from a development_activity raw snapshot.

Source shape (confirmed by profiling the FULL real 2026-07-25 snapshot,
1,438 rows — not a sample): CSV, semicolon-delimited with a UTF-8 BOM
(see jobs/registry/sources.yaml).

Full-file profiling findings that shaped this loader:
- `development_key` has ZERO duplicates across all 1,438 rows — unlike
  business_establishments, this source DOES have a genuine natural
  key. It is nonetheless loaded with the same delete-by-release +
  reinsert pattern as business_establishment, not a true ON CONFLICT
  upsert, because architecture.md's own refresh strategy for this
  source is "Monthly" full snapshot (not incremental) — a full
  replace on every load matches how the source itself is actually
  updated, and avoids a migration just to add a UNIQUE constraint
  nothing else needs yet.
- longitude/latitude are NEVER null — unlike business_establishments,
  every development has geometry.
- Only `year_completed` (317 nulls, i.e. not-yet-completed projects)
  and `property_id_2..5` (increasingly null — most developments only
  span one property) have any nulls at all.
- All ~30 numeric attribute columns (floor areas by use, dwelling/bed
  counts by type, car/bike spaces) parse cleanly as integers with no
  decimals anywhere in the real file — stored as JSON integers, not
  strings, in `raw_attributes`.
- `data_format` and `town_planning_application` are free-text/
  categorical (e.g. "Post Oct 2022", "TP-2024-243"), not numeric —
  kept as JSON strings in `raw_attributes` alongside the numeric
  fields, per migration 0003's rationale for using a JSONB bucket
  instead of ~30 speculative typed columns.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

BATCH_SIZE = 5_000

# Every source column NOT promoted to a first-class core.development_project
# column. Kept in raw_attributes verbatim (see module docstring).
_RAW_ATTRIBUTE_FIELDS = (
    "data_format",
    "property_id",
    "property_id_2",
    "property_id_3",
    "property_id_4",
    "property_id_5",
    "floors_above",
    "resi_dwellings",
    "studio_dwe",
    "one_bdrm_dwe",
    "two_bdrm_dwe",
    "three_bdrm_dwe",
    "student_apartments",
    "student_beds",
    "student_accommodation_units",
    "institutional_accom_beds",
    "hotel_rooms",
    "serviced_apartments",
    "hotels_serviced_apartments",
    "hostel_beds",
    "childcare_places",
    "office_flr",
    "retail_flr",
    "industrial_flr",
    "storage_flr",
    "education_flr",
    "hospital_flr",
    "recreation_flr",
    "publicdispaly_flr",  # sic — council's own field name typo, kept verbatim
    "community_flr",
    "car_spaces",
    "bike_spaces",
    "town_planning_application",
)
_TEXT_ATTRIBUTE_FIELDS = {"data_format", "town_planning_application"}

_DELETE_SQL = text("DELETE FROM core.development_project WHERE source_release_id = :release_id")

_INSERT_SQL = text("""
    INSERT INTO core.development_project
        (development_key, status, year_completed, clue_small_area, clue_block,
         street_address, geom, raw_attributes, source_release_id)
    VALUES
        (:development_key, :status, :year_completed, :clue_small_area, :clue_block,
         :street_address, ST_SetSRID(ST_GeomFromText(:geom_wkt), 4326),
         :raw_attributes, :release_id)
""")


def _attribute_value(field: str, raw: str) -> int | str | None:
    if raw == "":
        return None
    if field in _TEXT_ATTRIBUTE_FIELDS:
        return raw
    return int(raw)


def _row_to_params(row: dict[str, str], release_id: int) -> dict:
    raw_attributes = {f: _attribute_value(f, row[f]) for f in _RAW_ATTRIBUTE_FIELDS}
    geom_wkt = (
        f"POINT({row['longitude']} {row['latitude']})"
        if row["longitude"] and row["latitude"]
        else None
    )
    return {
        "development_key": row["development_key"],
        "status": row["status"] or None,
        "year_completed": int(row["year_completed"]) if row["year_completed"] else None,
        "clue_small_area": row["clue_small_area"] or None,
        "clue_block": row["clue_block"] or None,
        "street_address": row["street_address"] or None,
        "geom_wkt": geom_wkt,
        "raw_attributes": json.dumps(raw_attributes),
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
