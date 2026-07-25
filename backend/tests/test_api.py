from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "retailscout-api"}


def test_score_endpoint_is_stubbed_not_absent():
    """The endpoint must exist (contract published) but honestly refuse."""
    response = client.get(
        "/api/v1/locations/score",
        params={"lat": -37.8136, "lon": 144.9631, "profile": "cafe"},
    )
    assert response.status_code == 501


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
