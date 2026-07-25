"""Staging→core loaders: one module per core table, one function per module.

Each loader reads an already-ingested raw snapshot (never re-downloads —
that is ingest's job) and upserts into its core.* table, tagging every
row with the source_release_id it came from. Loaders are registered in
LOADERS below and invoked via `cli.py load <source_id>`.

A loader function has the signature:

    def load(conn: Connection, snapshot_dir: Path, release_id: int) -> int

and returns the number of rows written. It runs inside the caller's
transaction (see cli.cmd_load) — it must not call conn.commit() itself.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.engine import Connection

from . import municipal_boundary, pedestrian_sensor

LoaderFn = Callable[[Connection, Path, int], int]

LOADERS: dict[str, LoaderFn] = {
    "municipal_boundary": municipal_boundary.load,
    "pedestrian_sensor_locations": pedestrian_sensor.load,
}
