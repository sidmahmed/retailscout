"""Load core.pedestrian_sensor from a pedestrian_sensor_locations raw snapshot.

Source shape (OpenDataSoft JSON export, confirmed by inspection of the
real 2026-07-25 snapshot, 134 records): flat records with `location_id`
(int, unique), `latitude`/`longitude` (float, never null), and several
nullable text fields. `installation_date` is null for exactly one
sensor in the real data; `direction_1`/`direction_2` (compass labels
like "North", NOT the numeric per-hour counts of the same-named field
in pedestrian_hourly) are null for 34 of 134 — all within what the
core.pedestrian_sensor schema already allows as nullable.

architecture.md §4.2 warns sensor locations change over time; this
loader always upserts by sensor_id (location_id) against the LATEST
snapshot, so a sensor relocated between two ingests silently gets its
newest known position. Tracking location HISTORY (so old observations
join to the position that was actually current when they were
recorded) is out of scope here — it needs a period/validity table,
which is future work once pedestrian_hourly is actually loaded and
that gap starts to matter.
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
                INSERT INTO core.pedestrian_sensor
                    (sensor_id, sensor_name, sensor_description, location_type, status,
                     installed_at, direction_1_label, direction_2_label, geom,
                     source_release_id)
                VALUES
                    (:sensor_id, :sensor_name, :sensor_description, :location_type, :status,
                     :installed_at, :direction_1_label, :direction_2_label,
                     ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326),
                     :release_id)
                ON CONFLICT (sensor_id) DO UPDATE SET
                    sensor_name = EXCLUDED.sensor_name,
                    sensor_description = EXCLUDED.sensor_description,
                    location_type = EXCLUDED.location_type,
                    status = EXCLUDED.status,
                    installed_at = EXCLUDED.installed_at,
                    direction_1_label = EXCLUDED.direction_1_label,
                    direction_2_label = EXCLUDED.direction_2_label,
                    geom = EXCLUDED.geom,
                    source_release_id = EXCLUDED.source_release_id,
                    loaded_at = now()
            """),
            {
                "sensor_id": rec["location_id"],
                "sensor_name": rec["sensor_name"],
                "sensor_description": rec["sensor_description"],
                "location_type": rec["location_type"],
                "status": rec["status"],
                "installed_at": rec["installation_date"],
                "direction_1_label": rec["direction_1"],
                "direction_2_label": rec["direction_2"],
                "longitude": rec["longitude"],
                "latitude": rec["latitude"],
                "release_id": release_id,
            },
        )
    return len(records)
