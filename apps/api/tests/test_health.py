from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
EXPECTED = {"status": "ok", "service": "incident-response-agent-api"}


def test_root_health_exact_response() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == EXPECTED


def test_versioned_health_exact_response() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == EXPECTED


def test_health_does_not_expose_secrets() -> None:
    body = response_text = client.get("/health").text.lower()
    assert "password" not in body
    assert "database_url" not in response_text
    assert "api_key" not in response_text
