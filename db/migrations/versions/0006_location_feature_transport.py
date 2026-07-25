"""Analytics: add transport-access columns to analytics.location_feature.

Second feature family (§14.2 public transport). location_feature grows
by ALTER TABLE ADD COLUMN per family, as promised in the 0005 docstring
— cheap, non-breaking, and it keeps each family's columns landing WITH
its loader (features/transport_features.py) rather than being modelled
speculatively up front.

Catchment radii follow §9.2: 400 m (local access) for tram and bus,
800 m (wider destination/worker catchment) for train — trains draw from
further away. Columns are named *_stops_* honestly: these count GTFS
boardable stop/platform records (core.transport_stop excludes station
grouping rows), so train_stops_800m counts platform-level train stops,
not distinct stations. regional_coach and skybus (3 stops each) are
intercity/airport niche services, not core urban access, and are not
featured in v1.

Nullable, CHECK >= 0: NULL = not computed for this generation, 0 = a
real observed count (no stops of that mode in range) — invariant 4.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_COLUMNS = [
    "tram_stops_400m",
    "bus_stops_400m",
    "train_stops_800m",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.execute(
            f"ALTER TABLE analytics.location_feature "
            f"ADD COLUMN {col} integer CHECK ({col} >= 0)"
        )


def downgrade() -> None:
    for col in _COLUMNS:
        op.execute(f"ALTER TABLE analytics.location_feature DROP COLUMN {col}")
