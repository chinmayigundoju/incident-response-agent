import uuid

from fastapi.testclient import TestClient

from app.api.dependencies import get_automation_dispatcher, get_incident_service
from app.core.errors import ApplicationError
from app.main import app


class MissingIncidentService:
    def get_incident(self, _incident_id):
        raise ApplicationError("INCIDENT_NOT_FOUND", "Incident not found", 404)


class IngestingIncidentService:
    def __init__(self):
        self.calls = 0
        self.incident_id = uuid.uuid4()

    def ingest_alertmanager(self, payload):
        self.calls += 1
        return [type("IncidentResult", (), {"id": self.incident_id})()]


class RecordingAutomation:
    def __init__(self):
        self.incident_ids = []

    def new_incidents(self, _background_tasks, incident_ids):
        self.incident_ids.extend(incident_ids)


def test_malformed_alertmanager_payload_rejected_safely() -> None:
    response = TestClient(app).post("/webhooks/alertmanager", json={"status": "firing"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "traceback" not in response.text.lower()


def test_unknown_incident_has_deterministic_404() -> None:
    app.dependency_overrides[get_incident_service] = lambda: MissingIncidentService()
    try:
        response = TestClient(app).get(f"/api/v1/incidents/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "INCIDENT_NOT_FOUND", "message": "Incident not found"}
    }


def test_valid_alertmanager_webhook_is_accepted() -> None:
    service = IngestingIncidentService()
    automation = RecordingAutomation()
    app.dependency_overrides[get_incident_service] = lambda: service
    app.dependency_overrides[get_automation_dispatcher] = lambda: automation
    payload = {
        "version": "4",
        "status": "firing",
        "receiver": "incident-response-api",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CheckoutHighErrorRate"},
                "annotations": {},
                "startsAt": "2026-09-28T04:00:00Z",
                "fingerprint": "abc123",
            }
        ],
    }
    try:
        response = TestClient(app).post("/webhooks/alertmanager", json=payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "accepted": 1,
        "incident_ids": [str(service.incident_id)],
    }
    assert service.calls == 1
    assert automation.incident_ids == [service.incident_id]
