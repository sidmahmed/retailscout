"""Transport-access features: count nearby transit stops per cell.

Fills the transport columns of analytics.location_feature (§14.2) for
the active grid release: per cell, the number of tram and bus stops
within 400 m and train stops within 800 m of the cell centroid (§9.2's
local vs. wider catchments; trains draw from further away). A pure
ST_DWithin spatial count from core.transport_stop (1,300 GTFS stops) —
service-frequency features wait for a routes/trips loader (§14.2).

Counts are platform-level GTFS stops, not distinct stations
(core.transport_stop keeps boardable stop/platform records, not station
groupings). regional_coach/skybus are not featured (niche; see the 0006
migration). Cells with no stops in range get a real 0 (LEFT JOIN),
never NULL (invariant 4).

Upserts only its own columns for (release_id, cell_id, feature_version),
so it composes with the other feature-family loaders in any order (each
touches a disjoint column set on the shared row).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

DEFAULT_FEATURE_VERSION = "v1"

TRAM_BUS_RADIUS_M = 400
TRAIN_RADIUS_M = 800

_ACTIVE_RELEASE_SQL = text("SELECT release_id FROM analytics.active_release WHERE only_one")

# Join covers the WIDER radius (train, 800 m) with an index-accelerated
# &&/ST_Expand pre-filter; the 400 m tram/bus counts re-check distance in
# the FILTER (cheap over the small per-cell candidate set). A straight
# geography cast in the join would bypass transport_stop_geom_idx.
_BUILD_SQL = text("""
    INSERT INTO analytics.location_feature
        (release_id, cell_id, feature_version,
         tram_stops_400m, bus_stops_400m, train_stops_800m)
    SELECT
        ac.release_id, ac.cell_id, :feature_version,
        count(*) FILTER (
            WHERE ts.mode = 'tram'
              AND ST_DWithin(ts.geom::geography, ac.centroid::geography, :r_local)
        ) AS tram_stops_400m,
        count(*) FILTER (
            WHERE ts.mode = 'bus'
              AND ST_DWithin(ts.geom::geography, ac.centroid::geography, :r_local)
        ) AS bus_stops_400m,
        count(*) FILTER (WHERE ts.mode = 'metro_train') AS train_stops_800m
    FROM analytics.analysis_cell ac
    LEFT JOIN core.transport_stop ts
        ON ts.geom && ST_Expand(ac.centroid, :bbox_deg)
       AND ST_DWithin(ts.geom::geography, ac.centroid::geography, :r_wide)
    WHERE ac.release_id = :release_id
    GROUP BY ac.release_id, ac.cell_id
    ON CONFLICT (release_id, cell_id, feature_version) DO UPDATE SET
        tram_stops_400m  = EXCLUDED.tram_stops_400m,
        bus_stops_400m   = EXCLUDED.bus_stops_400m,
        train_stops_800m = EXCLUDED.train_stops_800m,
        calculated_at    = now()
""")


@dataclass
class TransportFeatureResult:
    release_id: int
    feature_version: str
    tram_bus_radius_m: int
    train_radius_m: int
    cells_written: int


def build_transport_features(
    conn: Connection,
    feature_version: str = DEFAULT_FEATURE_VERSION,
) -> TransportFeatureResult:
    """Compute transport-access features for the active release's grid.
    Runs inside the caller's transaction — must not commit."""
    release_id = conn.execute(_ACTIVE_RELEASE_SQL).scalar_one_or_none()
    if release_id is None:
        raise ValueError("No active grid release — run `cli build-grid` before building features.")

    # bbox for the wider (train) radius; longitude is the binding axis at
    # Melbourne's latitude (~87.9 km/deg), so /75_000 never under-covers.
    bbox_deg = TRAIN_RADIUS_M / 75_000.0

    conn.execute(
        _BUILD_SQL,
        {
            "feature_version": feature_version,
            "r_local": TRAM_BUS_RADIUS_M,
            "r_wide": TRAIN_RADIUS_M,
            "bbox_deg": bbox_deg,
            "release_id": release_id,
        },
    )

    cells_written = conn.execute(
        text(
            "SELECT count(*) FROM analytics.location_feature "
            "WHERE release_id = :r AND feature_version = :fv"
        ),
        {"r": release_id, "fv": feature_version},
    ).scalar_one()

    return TransportFeatureResult(
        release_id=release_id,
        feature_version=feature_version,
        tram_bus_radius_m=TRAM_BUS_RADIUS_M,
        train_radius_m=TRAIN_RADIUS_M,
        cells_written=cells_written,
    )
