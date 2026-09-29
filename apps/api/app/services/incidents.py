import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.core.errors import ApplicationError
from app.models.incident import (
    ACTIVE_INCIDENT_STATUSES,
    Hypothesis,
    Incident,
    IncidentEvent,
    IncidentStatus,
    TelemetryEvidence,
)
from app.repositories.incidents import IncidentRepository
from app.schemas.alertmanager import AlertmanagerAlert, AlertmanagerWebhook, normalized_payload
from app.services.transitions import IncidentTransitionService


class IncidentService:
    def __init__(self, repository: IncidentRepository):
        self.repository = repository
        self.transitions = IncidentTransitionService()

    def ingest_alertmanager(self, webhook: AlertmanagerWebhook) -> list[Incident]:
        incidents = [self._ingest_alert(alert) for alert in webhook.alerts]
        self.repository.commit()
        return incidents

    def _ingest_alert(self, alert: AlertmanagerAlert) -> Incident:
        labels = alert.labels
        fingerprint = alert.fingerprint or self._fallback_fingerprint(alert)
        external_id = self._occurrence_external_id(fingerprint, alert.startsAt)
        occurrence = self.repository.find_by_external_alert_id(external_id)

        if alert.status == "resolved":
            incident = occurrence or self.repository.find_active_by_fingerprint(fingerprint)
            if incident is None:
                incident = self.repository.find_latest_by_fingerprint(fingerprint)
        else:
            incident = self.repository.find_active_by_fingerprint(fingerprint) or occurrence

        if incident is None:
            incident = self.repository.create_active_or_get(
                title=labels.get("alertname", "Unclassified production alert"),
                service=labels.get("service", "unknown-service"),
                environment=labels.get("environment", "unknown"),
                severity=labels.get("severity", "unknown"),
                started_at=alert.startsAt,
                fingerprint=fingerprint,
                external_alert_id=external_id,
            )

        if alert.status == "resolved" and incident.status in ACTIVE_INCIDENT_STATUSES:
            self.transitions.transition(incident, IncidentStatus.RESOLVED)
            incident.resolved_at = alert.endsAt or datetime.now(UTC)

        self.repository.append_event(
            incident,
            event_type="ALERT_RECEIVED",
            payload=normalized_payload(alert),
            occurred_at=datetime.now(UTC),
        )
        return incident

    @staticmethod
    def _occurrence_external_id(fingerprint: str, starts_at: datetime) -> str:
        identity = json.dumps(
            {
                "fingerprint": fingerprint,
                "starts_at": starts_at.astimezone(UTC).isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"alertmanager:{hashlib.sha256(identity.encode()).hexdigest()}"

    @staticmethod
    def _fallback_fingerprint(alert: AlertmanagerAlert) -> str:
        identity = json.dumps(
            {"labels": alert.labels, "starts_at": alert.startsAt.isoformat()},
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"generated:{hashlib.sha256(identity.encode()).hexdigest()}"

    def list_incidents(self, *, limit: int, offset: int) -> Sequence[Incident]:
        return self.repository.list(limit=limit, offset=offset)

    def get_incident(self, incident_id: uuid.UUID) -> Incident:
        incident = self.repository.get(incident_id)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident not found", 404)
        return incident

    def events(self, incident_id: uuid.UUID) -> Sequence[IncidentEvent]:
        self.get_incident(incident_id)
        return self.repository.list_events(incident_id)

    def evidence(self, incident_id: uuid.UUID) -> Sequence[TelemetryEvidence]:
        self.get_incident(incident_id)
        return self.repository.list_evidence(incident_id)

    def hypotheses(self, incident_id: uuid.UUID) -> Sequence[Hypothesis]:
        self.get_incident(incident_id)
        return self.repository.list_hypotheses(incident_id)
