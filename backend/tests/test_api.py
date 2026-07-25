from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "retailscout-api"}


def test_score_endpoint_never_500s():
    """Implemented for real (was a 501 stub). Without a reachable/populated
    DB it must degrade to 503, never crash; with data it returns 200.
    Full data-backed behaviour lives in test_score_api.py."""
    response = client.get(
        "/api/v1/locations/score",
        params={"lat": -37.8136, "lon": 144.9631, "profile": "cafe"},
    )
    assert response.status_code in {200, 503}


def test_score_endpoint_validates_profile():
    response = client.get(
        "/api/v1/locations/score",
        params={"lat": -37.8136, "lon": 144.9631, "profile": "laundromat"},
    )
    assert response.status_code == 422


def test_openapi_publishes_score_contract():
    """contracts/ generation depends on these being in the schema."""
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert "ScoreResponse" in schemas
    assert "Confidence" in schemas
    assert "ComponentScore" in schemas
    # confidence is mandatory — a score without confidence is not a valid response
    assert "confidence" in schemas["ScoreResponse"]["required"]
    assert "score_version" in schemas["ScoreResponse"]["required"]
    assert "data_release" in schemas["ScoreResponse"]["required"]
