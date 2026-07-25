"""Build the precomputed hex analysis grid (analytics.analysis_cell).

The grid is the substrate ADR-002 scores against: rather than scoring
arbitrary raw coordinates per request, RetailScout precomputes a fixed
grid of cells and maps a user's point to its containing cell. We use
H3 (Uber's hexagonal hierarchical index) rather than a bespoke grid so
cell_ids are globally stable and comparable — the same geography always
yields the same cell_id, across releases and across any future
municipality, with no ad hoc grid geometry to version.

Resolution: H3 res 10 (DEFAULT_RESOLUTION). Chosen by benchmarking all
candidate resolutions against the REAL City of Melbourne boundary
(37.66 km²), not picked from a table:

    res  cells  edge_m  cell_width_m   note
     8      43   531    ~920           whole-suburb scale, too coarse
     9     307   201    ~350           block-cluster scale
    10    2317    76    ~130           block-face scale  <-- chosen
    11  14966    29    ~50             sub-storefront, needlessly fine

architecture.md targets ~100-200m cells at "block-face scale"; res 10
is the only resolution whose cell width (~130m) lands in that range.
Resolution is a parameter and is recorded per data_release
(analytics.data_release.grid_resolution), so it can change in a future
release without a schema change or code change.

How H3 is used: h3 ONLY enumerates candidate cells and yields their
hexagon boundary / centre as lat/lng. All boundary clipping is done in
PostGIS (ST_Intersects) — so shapely/geopandas are still not needed
(jobs/pyproject.toml). Enumeration uses `overlap` containment (every
cell that overlaps the boundary, not just those whose centre is inside)
so there are no gaps at the edge where an in-boundary click could fall
into no cell. A precise ST_Intersects prune afterward drops the handful
of overlap-mode false positives at the bounding extremes — the same
enumerate-loosely-then-prune-precisely pattern the transport_stop
loader uses.

Publication is atomic (architecture.md invariant 3): a data_release row
is created `building`, its cells are inserted, then it is flipped to
`published` and the singleton analytics.active_release pointer is
updated to it in the same transaction. Rollback is re-pointing
active_release at a prior release — old releases' cells are never
deleted here.
"""

from __future__ import annotations

from dataclasses import dataclass

import h3
from sqlalchemy import text
from sqlalchemy.engine import Connection

DEFAULT_RESOLUTION = 10

# H3 v4 experimental polyfill containment mode — see module docstring.
_CONTAINMENT = "overlap"

_READ_BOUNDARY_SQL = text("""
    SELECT ST_AsGeoJSON(ST_Union(geom)) AS geojson,
           max(source_release_id)       AS boundary_source_release_id
    FROM core.municipal_boundary
""")

_CREATE_RELEASE_SQL = text("""
    INSERT INTO analytics.data_release
        (status, grid_resolution, boundary_source_release_id, notes)
    VALUES ('building', :resolution, :boundary_source_release_id, :notes)
    RETURNING release_id
""")

_INSERT_CELL_SQL = text("""
    INSERT INTO analytics.analysis_cell (release_id, cell_id, geom, centroid)
    VALUES (
        :release_id, :cell_id,
        ST_SetSRID(ST_GeomFromText(:geom_wkt), 4326),
        ST_SetSRID(ST_GeomFromText(:centroid_wkt), 4326)
    )
""")

# Backstop prune: `overlap` containment can include a few cells that
# touch only the bounding extremes, not the boundary's true shape.
_PRUNE_SQL = text("""
    DELETE FROM analytics.analysis_cell c
    WHERE c.release_id = :release_id
      AND NOT EXISTS (
          SELECT 1 FROM core.municipal_boundary b
          WHERE ST_Intersects(b.geom, c.geom)
      )
""")

_PUBLISH_SQL = text("""
    UPDATE analytics.data_release
    SET status = 'published', published_at = now()
    WHERE release_id = :release_id
""")

# Atomic pointer flip: mark the outgoing release superseded (if any and
# different), then upsert the singleton active_release row.
_SUPERSEDE_PREVIOUS_SQL = text("""
    UPDATE analytics.data_release
    SET status = 'superseded'
    WHERE release_id = (SELECT release_id FROM analytics.active_release WHERE only_one)
      AND release_id <> :release_id
""")

_ACTIVATE_SQL = text("""
    INSERT INTO analytics.active_release (only_one, release_id)
    VALUES (true, :release_id)
    ON CONFLICT (only_one) DO UPDATE
        SET release_id = EXCLUDED.release_id, updated_at = now()
""")

_BATCH_SIZE = 1_000


@dataclass
class GridBuildResult:
    release_id: int
    resolution: int
    cell_count: int
    activated: bool


def _geojson_to_polys(geojson: dict) -> list[h3.LatLngPoly]:
    """GeoJSON Polygon/MultiPolygon -> H3 LatLngPoly list (lng,lat -> lat,lng)."""
    if geojson["type"] == "MultiPolygon":
        polygons = geojson["coordinates"]
    elif geojson["type"] == "Polygon":
        polygons = [geojson["coordinates"]]
    else:
        raise ValueError(f"Unsupported boundary geometry type: {geojson['type']}")

    polys: list[h3.LatLngPoly] = []
    for rings in polygons:  # rings = [outer, hole, hole, ...]
        loops = [[(lat, lng) for lng, lat in ring] for ring in rings]
        polys.append(h3.LatLngPoly(loops[0], *loops[1:]))
    return polys


def _enumerate_cells(polys: list[h3.LatLngPoly], resolution: int) -> set[str]:
    cells: set[str] = set()
    for poly in polys:
        cells |= set(h3.polygon_to_cells_experimental(poly, resolution, _CONTAINMENT))
    return cells


def _cell_to_params(cell_id: str, release_id: int) -> dict:
    boundary = h3.cell_to_boundary(cell_id)  # ((lat, lng), ...), CCW, not closed
    ring = ", ".join(f"{lng} {lat}" for lat, lng in boundary)
    first_lat, first_lng = boundary[0]
    ring += f", {first_lng} {first_lat}"  # close the polygon ring
    lat, lng = h3.cell_to_latlng(cell_id)
    return {
        "release_id": release_id,
        "cell_id": cell_id,
        "geom_wkt": f"POLYGON(({ring}))",
        "centroid_wkt": f"POINT({lng} {lat})",
    }


def build_grid(
    conn: Connection,
    resolution: int = DEFAULT_RESOLUTION,
    notes: str | None = None,
    activate: bool = True,
) -> GridBuildResult:
    """Build a new hex-grid data_release from core.municipal_boundary.

    Runs inside the caller's transaction (see cli.cmd_build_grid) — must
    not commit. If `activate`, atomically flips analytics.active_release
    to the new release before returning.
    """
    import json

    row = conn.execute(_READ_BOUNDARY_SQL).one()
    if row.geojson is None:
        raise ValueError(
            "core.municipal_boundary is empty — load it first "
            "(`cli load municipal_boundary`) before building the grid."
        )
    polys = _geojson_to_polys(json.loads(row.geojson))
    cells = _enumerate_cells(polys, resolution)
    if not cells:
        raise ValueError(f"No H3 cells enumerated for the boundary at resolution {resolution}")

    release_id = conn.execute(
        _CREATE_RELEASE_SQL,
        {
            "resolution": resolution,
            "boundary_source_release_id": row.boundary_source_release_id,
            "notes": notes,
        },
    ).scalar_one()

    batch: list[dict] = []
    for cell_id in cells:
        batch.append(_cell_to_params(cell_id, release_id))
        if len(batch) >= _BATCH_SIZE:
            conn.execute(_INSERT_CELL_SQL, batch)
            batch = []
    if batch:
        conn.execute(_INSERT_CELL_SQL, batch)

    conn.execute(_PRUNE_SQL, {"release_id": release_id})

    cell_count = conn.execute(
        text("SELECT count(*) FROM analytics.analysis_cell WHERE release_id = :id"),
        {"id": release_id},
    ).scalar_one()
    if cell_count == 0:
        raise ValueError(
            "No cells survived the boundary intersection prune — "
            "check that core.municipal_boundary holds a real geometry."
        )

    conn.execute(_PUBLISH_SQL, {"release_id": release_id})

    if activate:
        conn.execute(_SUPERSEDE_PREVIOUS_SQL, {"release_id": release_id})
        conn.execute(_ACTIVATE_SQL, {"release_id": release_id})

    return GridBuildResult(
        release_id=release_id,
        resolution=resolution,
        cell_count=cell_count,
        activated=activate,
    )
