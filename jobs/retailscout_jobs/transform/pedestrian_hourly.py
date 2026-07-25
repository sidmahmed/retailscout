"""Load core.pedestrian_observation from a pedestrian_hourly raw snapshot.

Source shape (confirmed by profiling the FULL real 2026-07-25 snapshot,
1,610,006 rows — not a sample): CSV, semicolon-delimited with a UTF-8
BOM (see jobs/registry/sources.yaml — undocumented by OpenDataSoft,
found by opening the actual file). Columns:
id;location_id;sensing_date;hourday;direction_1;direction_2;pedestriancount;sensor_name;location

Full-file profiling findings that shaped this loader:
- `id` is a synthetic composite (location_id+hourday+date as a single
  number, e.g. "1091420250121" = location_id 109, hourday 14, date
  2025-01-21) — NOT a stable key. The real key is
  (location_id, sensing_date, hourday); zero duplicates confirmed
  across all 1.6M rows, so (sensor_id, observed_at) is safe as the
  table's primary key.
- No nulls in location_id/sensing_date/hourday/direction_1/direction_2
  /pedestriancount. sensor_name and location ARE null for 26,265 rows,
  but this table doesn't use either column (geometry lives in
  core.pedestrian_sensor, joined by sensor_id) so that's irrelevant
  here.
- No negative pedestriancount values.
- 103 distinct location_ids appear in the observation data, but only
  134 sensors exist in the currently-loaded core.pedestrian_sensor
  snapshot, and THREE of the 103 (28, 65, 78) are not among them —
  i.e. real historical sensors not present in the current
  sensor-locations export. This is an empirical CONFIRMATION of
  architecture.md §4.2's warning, not a theoretical concern: it is
  exactly why core.pedestrian_observation has no foreign key to
  core.pedestrian_sensor (migration 0003). Loading must not fail or
  silently drop rows for these sensor_ids.

Timezone: sensing_date + hourday is a LOCAL Australia/Melbourne hour
bucket (the dataset's own description says pedestrian counts are
totalled per local hour). observed_at is built by localizing
(date, hourday) in Australia/Melbourne via zoneinfo, then storing as
UTC (timestamptz).

DST was checked against all 4 real transition dates in the snapshot's
range (2024-10-06, 2025-04-06, 2025-10-05, 2026-04-05), not just
reasoned about:
- Spring-forward dates (October): hourday=2 (the local hour that does
  not exist that day) NEVER appears in the source for any sensor — the
  council's own aggregation already omits it. No PK collision risk.
- Fall-back dates (April): hourday=2 (locally ambiguous — occurs
  twice) appears exactly ONCE per sensor (confirmed via the
  no-duplicate-keys check above) — the source has already collapsed
  whatever happened during that hour into a single bucket before this
  loader sees it. zoneinfo's default `fold=0` resolves this loader's
  local→UTC conversion to the first (AEDT, +11:00) occurrence, a
  documented but essentially arbitrary choice for that one row per
  sensor per year — it does not affect any other hour.

Performance: streams the CSV (never holds all 1.6M rows in memory) and
inserts in batches via SQLAlchemy's multi-row VALUES support, since
1.6M individual round-trip INSERTs would be impractically slow.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Connection

MELBOURNE = ZoneInfo("Australia/Melbourne")
BATCH_SIZE = 5_000

_UPSERT_SQL = text("""
    INSERT INTO core.pedestrian_observation
        (sensor_id, observed_at, pedestrian_count, direction_1_count, direction_2_count,
         source_release_id)
    VALUES
        (:sensor_id, :observed_at, :pedestrian_count, :direction_1_count, :direction_2_count,
         :release_id)
    ON CONFLICT (sensor_id, observed_at) DO UPDATE SET
        pedestrian_count = EXCLUDED.pedestrian_count,
        direction_1_count = EXCLUDED.direction_1_count,
        direction_2_count = EXCLUDED.direction_2_count,
        source_release_id = EXCLUDED.source_release_id,
        loaded_at = now()
""")


def _observed_at(sensing_date: str, hourday: str) -> dt.datetime:
    year, month, day = (int(x) for x in sensing_date.split("-"))
    local = dt.datetime(year, month, day, int(hourday), tzinfo=MELBOURNE)
    return local.astimezone(dt.UTC)


def _row_to_params(row: dict[str, str], release_id: int) -> dict:
    return {
        "sensor_id": int(row["location_id"]),
        "observed_at": _observed_at(row["sensing_date"], row["hourday"]),
        "pedestrian_count": int(row["pedestriancount"]),
        "direction_1_count": int(row["direction_1"]),
        "direction_2_count": int(row["direction_2"]),
        "release_id": release_id,
    }


def load(conn: Connection, snapshot_dir: Path, release_id: int) -> int:
    data_file = snapshot_dir / "data.csv"
    total = 0
    batch: list[dict] = []

    with open(data_file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            batch.append(_row_to_params(row, release_id))
            if len(batch) >= BATCH_SIZE:
                conn.execute(_UPSERT_SQL, batch)
                total += len(batch)
                batch = []
                if total % 200_000 == 0:
                    print(f"  ... {total:,} rows loaded")
        if batch:
            conn.execute(_UPSERT_SQL, batch)
            total += len(batch)

    if total == 0:
        raise ValueError(f"No rows in {data_file}")
    return total
