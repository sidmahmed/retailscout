"""Score/tiles/meta endpoints against the real dev database.

These need a reachable PostGIS with a published release + scores (the
full jobs pipeline output). If that's absent — CI's backend job has no
DB service — they SKIP rather than fail: contract-level behaviour is
covered DB-free in test_api.py, and the jobs suite covers the pipeline
itself. Assertions here are structural/relative (known golden points),
never exact scores, so legitimate data refreshes don't break them.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BOURKE_ST_MALL = {"lat": -37.8136, "lon": 144.9648}
RICHMOND_OUTSIDE = {"lat": -37.8230, "lon": 144.9980}


def _scores_available() -> bool:
    return client.get("/api/v1/business-profiles").status_code == 200


pytestmark = pytest.mark.skipif(
    not _scores_available(),
    reason="no published scores reachable — run the jobs pipeline (see db/README.md)",
)


def _tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def test_score_cbd_point_full_contract():
    r = client.get("/api/v1/locations/score", params={**BOURKE_ST_MALL, "profile": "cafe"})
    assert r.status_code == 200
    d = r.json()
    assert 0 <= d["score"] <= 100
    assert d["location"]["cell_id"]
    assert d["confidence"]["band"] in {"high", "medium", "low", "insufficient"}
    assert len(d["confidence"]["reasons"]) >= 1
    keys = {c["key"] for c in d["components"]}
    assert keys == {"pedestrian_demand", "worker_demand", "competition", "transport", "development"}
    # development went live with score_version v2 (migration 0013): a CBD
    # cell must carry a real score and its pipeline evidence.
    dev = next(c for c in d["components"] if c["key"] == "development")
    assert dev["score"] is not None and 0 <= dev["score"] <= 100
    assert dev["evidence"]["pipeline_projects_800m"] > 0
    assert d["top_drivers"] and len(d["top_drivers"]) <= 3
    assert d["score_version"] and d["data_release"].startswith("melbourne-")


def test_outside_boundary_rejected_fr02():
    r = client.get("/api/v1/locations/score", params={**RICHMOND_OUTSIDE, "profile": "cafe"})
    assert r.status_code == 400
    assert "outside" in r.json()["detail"].lower()


def test_all_published_profiles_score_the_same_point():
    profiles = [p["id"] for p in client.get("/api/v1/business-profiles").json()]
    assert set(profiles) == {"cafe", "retail_shop", "food_truck", "pop_up"}
    for p in profiles:
        r = client.get("/api/v1/locations/score", params={**BOURKE_ST_MALL, "profile": p})
        assert r.status_code == 200, p


def test_coverage_bounds_contain_cbd():
    d = client.get("/api/v1/coverage").json()
    min_lon, min_lat, max_lon, max_lat = d["bounds"]
    assert min_lon < BOURKE_ST_MALL["lon"] < max_lon
    assert min_lat < BOURKE_ST_MALL["lat"] < max_lat
    assert d["boundary"]["type"] in {"MultiPolygon", "Polygon"}


def test_suitability_tile_has_content_over_cbd_and_none_far_away():
    x, y = _tile_xy(BOURKE_ST_MALL["lat"], BOURKE_ST_MALL["lon"], 14)
    r = client.get(f"/api/v1/tiles/suitability/cafe/14/{x}/{y}.mvt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.mapbox-vector-tile")
    assert len(r.content) > 500  # real hexes encoded
    far = client.get("/api/v1/tiles/suitability/cafe/14/0/0.mvt")
    assert far.status_code == 200 and len(far.content) == 0
