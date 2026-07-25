"""Load core.transport_stop from a ptv_gtfs raw snapshot (stops.txt only).

Source shape: a nested zip. The top-level ptv_gtfs snapshot is a zip
containing numbered folders (1, 2, 3, 4, 5, 6, 10, 11 in the real
2026-07-25 archive — not contiguous; never assume a fixed range), each
holding its own inner `google_transit.zip` with the standard GTFS file
set. `agency.txt` is uninformative (every bundle says "Transport
Victoria"); mode per folder was determined by inspecting each bundle's
`routes.txt` `route_type` + real route names against the real archive:

    1  = regional_train      (route_type 2,   e.g. "Albury - Melbourne Via Seymour")
    2  = metro_train         (route_type 400, e.g. "Alamein - City")
    3  = tram                (route_type 0,   e.g. "Port Melbourne - Box Hill")
    4  = bus                 (route_type 3,   e.g. "Bulleen - City (Queen St)")
    5  = regional_coach      (route_type 204, e.g. "Warrnambool - Melbourne Via Ararat & Hamilton")
    6  = regional_bus        (route_type 701, e.g. "Paynesville - Bairnsdale")
    10 = long_distance_train (route_type 102, "The Overland")
    11 = skybus               (route_type 3,  airport routes)

This is a documented, verified fact about the 2026-07-25 archive, not
a guess — but PTV could renumber or add folders later. FOLDER_TO_MODE
deliberately KeyErrors on an unrecognised folder rather than silently
mislabelling a new mode.

Statewide stops.txt totals ~31,973 rows across all 8 bundles — small
enough to hold fully in memory per bundle (unlike pedestrian_hourly;
no streaming needed here).

This loader does NOT load all statewide stops:
- Only `location_type` '' or '0' (boardable stop/platform records) —
  excludes station-grouping rows (1), entrances (2), and generic nodes
  (3), which are structurally near-duplicate points at the same
  physical location as their parent and would inflate stop density
  near stations.
- Only stops within core.municipal_boundary + 1km: a cheap Python
  bounding-box pre-filter avoids parsing/holding irrelevant regional
  stops, followed by a precise ST_DWithin prune in SQL after insert
  (the bbox is a rectangle, not the boundary's actual shape, so a few
  false positives at the corners need trimming).

A stop_id CAN collide across mode bundles (293 of 2,584 bbox-filtered
rows in the real archive — e.g. a station shared by train and
connecting bus/tram services). core.transport_stop has a single
`mode` column (no multi-modal list yet — `routes` stays nullable
until a routes/trips loader exists, per migration 0003), so a
colliding stop_id ends up tagged with whichever bundle is processed
LAST. Bundles are processed in a fixed, documented order so this is
deterministic, not incidental: peripheral/regional modes first, ending
with metro_train and tram — the modes that actually define access in
the City of Melbourne CBD, this product's initial scope, so they win
any collision. Genuine multi-modal tagging is future work once a
routes/trips loader exists.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

FOLDER_TO_MODE = {
    "1": "regional_train",
    "2": "metro_train",
    "3": "tram",
    "4": "bus",
    "5": "regional_coach",
    "6": "regional_bus",
    "10": "long_distance_train",
    "11": "skybus",
}

# Last wins on stop_id collision — see module docstring.
_PROCESSING_ORDER = ["11", "5", "10", "1", "6", "4", "3", "2"]

_BOARDABLE_LOCATION_TYPES = {"", "0"}

_WHEELCHAIR_MAP = {"1": True, "2": False}  # "0"/"" -> None (no info)

_DELETE_ALL_SQL = text("DELETE FROM core.transport_stop")

_BUFFERED_BBOX_SQL = text("""
    SELECT ST_XMin(bbox) AS xmin, ST_YMin(bbox) AS ymin,
           ST_XMax(bbox) AS xmax, ST_YMax(bbox) AS ymax
    FROM (
        SELECT ST_Envelope(ST_Buffer(ST_Union(geom)::geography, 1000)::geometry) AS bbox
        FROM core.municipal_boundary
    ) t
""")

_INSERT_SQL = text("""
    INSERT INTO core.transport_stop
        (stop_id, stop_name, mode, wheelchair_boarding, geom, source_release_id)
    VALUES
        (:stop_id, :stop_name, :mode, :wheelchair_boarding,
         ST_SetSRID(ST_GeomFromText(:geom_wkt), 4326), :release_id)
    ON CONFLICT (stop_id) DO UPDATE SET
        stop_name = EXCLUDED.stop_name,
        mode = EXCLUDED.mode,
        wheelchair_boarding = EXCLUDED.wheelchair_boarding,
        geom = EXCLUDED.geom,
        source_release_id = EXCLUDED.source_release_id,
        loaded_at = now()
""")

_PRUNE_OUTSIDE_BUFFER_SQL = text("""
    DELETE FROM core.transport_stop t
    WHERE source_release_id = :release_id
      AND NOT EXISTS (
          SELECT 1 FROM core.municipal_boundary b
          WHERE ST_DWithin(b.geom::geography, t.geom::geography, 1000)
      )
""")


def _read_inner_stops(outer_zip: zipfile.ZipFile, folder: str) -> list[dict[str, str]]:
    inner_bytes = outer_zip.read(f"{folder}/google_transit.zip")
    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner_zip:
        raw = inner_zip.read("stops.txt").decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(raw)))


def _row_to_params(row: dict[str, str], mode: str, release_id: int) -> dict:
    return {
        "stop_id": row["stop_id"],
        "stop_name": row["stop_name"],
        "mode": mode,
        "wheelchair_boarding": _WHEELCHAIR_MAP.get(row.get("wheelchair_boarding", "")),
        "geom_wkt": f"POINT({row['stop_lon']} {row['stop_lat']})",
        "release_id": release_id,
    }


def load(conn: Connection, snapshot_dir: Path, release_id: int) -> int:
    xmin, ymin, xmax, ymax = conn.execute(_BUFFERED_BBOX_SQL).one()

    # This loader owns the whole table (single source) — full replace
    # on every load, matching the other non-natural-key loaders.
    conn.execute(_DELETE_ALL_SQL)

    with zipfile.ZipFile(snapshot_dir / "data.zip") as outer_zip:
        available = {name.split("/")[0] for name in outer_zip.namelist() if "/" in name}
        batch: list[dict] = []
        for folder in _PROCESSING_ORDER:
            if folder not in available:
                continue
            mode = FOLDER_TO_MODE[folder]
            for row in _read_inner_stops(outer_zip, folder):
                if row.get("location_type", "") not in _BOARDABLE_LOCATION_TYPES:
                    continue
                lon, lat = float(row["stop_lon"]), float(row["stop_lat"])
                if not (xmin <= lon <= xmax and ymin <= lat <= ymax):
                    continue
                batch.append(_row_to_params(row, mode, release_id))

    if not batch:
        raise ValueError(f"No stops found within the boundary buffer in {snapshot_dir}")

    conn.execute(_INSERT_SQL, batch)
    conn.execute(_PRUNE_OUTSIDE_BUFFER_SQL, {"release_id": release_id})

    total = conn.execute(
        text("SELECT count(*) FROM core.transport_stop WHERE source_release_id = :id"),
        {"id": release_id},
    ).scalar_one()
    return total
