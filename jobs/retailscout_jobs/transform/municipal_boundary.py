"""Load core.municipal_boundary from a municipal_boundary raw snapshot.

Source shape (OpenDataSoft JSON export, confirmed by inspection of the
real 2026-07-25 snapshot): a JSON list of records, each with a
`geo_shape.geometry` GeoJSON MultiPolygon and flat attribute fields
(`mccid_gis`, `name`, ...). Uses PostGIS's own ST_GeomFromGeoJSON rather
than a Python geometry library (shapely/geopandas) — parsing GeoJSON
into a PostGIS geometry is exactly what that function is for, and
pulling in a geospatial dependency for one JSON-to-geometry conversion
would be premature (jobs/pyproject.toml adds geopandas/shapely only
when a loader needs actual geometric computation).
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection


def load(conn: Connection, snapshot_dir: Path, release_id: int) -> int:
    data_file = snapshot_dir / "data.json"
    records = json.loads(data_file.read_text())
    if not records:
        raise ValueError(f"No records in {data_file}")

    for rec in records:
        conn.execute(
            text("""
                INSERT INTO core.municipal_boundary (id, name, geom, source_release_id)
                VALUES (
                    :id, :name,
                    ST_SetSRID(ST_GeomFromGeoJSON(:geometry_json), 4326),
                    :release_id
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    geom = EXCLUDED.geom,
                    source_release_id = EXCLUDED.source_release_id,
                    loaded_at = now()
            """),
            {
                "id": rec["mccid_gis"],
                "name": rec["name"],
                "geometry_json": json.dumps(rec["geo_shape"]["geometry"]),
                "release_id": release_id,
            },
        )
    return len(records)
