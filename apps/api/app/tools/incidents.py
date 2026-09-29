import uuid
from typing import Any

from app.core.errors import ApplicationError
from app.repositories.incidents import IncidentRepository


class IncidentContextTool:
    def __init__(self, repository: IncidentRepository):
        self.repository = repository

    def get_incident_context(self, incident_id: uuid.UUID) -> dict[str, Any]:
        incident = self.repository.get(incident_id)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident not found", 404)
        return {
            "incident": {
                "id": str(incident.id),
                "title": incident.title,
                "service": incident.service,
                "environment": incident.environment,
                "severity": incident.severity,
                "status": incident.status.value,
                "started_at": incident.started_at.isoformat(),
            },
            "events": [
                {
                    "id": str(item.id),
                    "event_type": item.event_type,
                    "occurred_at": item.occurred_at.isoformat(),
                    "payload": item.payload,
                }
                for item in self.repository.list_events(incident_id)
            ],
            "existing_evidence": [
                {
                    "id": str(item.id),
                    "type": item.type,
                    "source": item.source,
                    "observed_at": item.observed_at.isoformat(),
                    "content": item.content,
                }
                for item in self.repository.list_evidence(incident_id)
            ],
            "existing_hypotheses": [
                {
                    "id": str(item.id),
                    "statement": item.statement,
                    "status": item.status,
                    "confidence": str(item.confidence) if item.confidence else None,
                }
                for item in self.repository.list_hypotheses(incident_id)
            ],
        }
