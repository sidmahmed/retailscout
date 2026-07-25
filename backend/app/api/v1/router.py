"""The /api/v1 composition point. Every new endpoint module registers here.

Planned routers (architecture doc §17) — add as they are implemented:
  search (geocode), areas (rank), tiles (MVT), projects, methodology,
  data-sources (freshness/status), business-profiles, coverage.
"""

from fastapi import APIRouter

from app.api.v1 import health, locations, meta, tiles

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(locations.router)
api_router.include_router(meta.router)
api_router.include_router(tiles.router)
