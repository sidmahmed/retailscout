"""Load core.clue_block from a clue_blocks raw snapshot.

Source shape (OpenDataSoft JSON export, confirmed by inspecting the real
2026-07-25 snapshot): a JSON list of 603 records, each with a
`geo_shape.geometry` GeoJSON Polygon, a `geo_point_2d` {lon, lat}
centroid, an integer `block_id`, and `region_name`/`area_name` CLUE
labels. Uses PostGIS's ST_GeomFromGeoJSON / ST_MakePoint directly (no
shapely/geopandas) — same rationale as municipal_boundary.py.

Upserts on block_id (a real, unique natural key — 603 distinct, no
nulls in the real file), so re-loading the same or a refreshed snapshot
is idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

_INSERT_SQL = text("""
    INSERT INTO core.clue_block
        (block_id, region_name, area_name, centroid, geom, source_release_id)
    VALUES (
        :block_id, :region_name, :area_name,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
        ST_SetSRID(ST_GeomFromGeoJSON(:geometry_json), 4326),
        :release_id
    )
    ON CONFLICT (block_id) DO UPDATE SET
        region_name = EXCLUDED.region_name,
        area_name = EXCLUDED.area_name,
        centroid = EXCLUDED.centroid,
        geom = EXCLUDED.geom,
        source_release_id = EXCLUDED.source_release_id,
        loaded_at = now()
""")


def load(conn: Connection, snapshot_dir: Path, release_id: int) -> int:
    records = json.loads((snapshot_dir / "data.json").read_text())
    if not records:
        raise ValueError(f"No records in {snapshot_dir / 'data.json'}")

    params = [
        {
            "block_id": rec["block_id"],
            "region_name": rec["region_name"],
            "area_name": rec["area_name"],
            "lon": rec["geo_point_2d"]["lon"],
            "lat": rec["geo_point_2d"]["lat"],
            "geometry_json": json.dumps(rec["geo_shape"]["geometry"]),
            "release_id": release_id,
        }
        for rec in records
    ]
    conn.execute(_INSERT_SQL, params)
    return len(params)
