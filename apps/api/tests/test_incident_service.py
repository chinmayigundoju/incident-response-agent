import uuid
from datetime import UTC, datetime, timedelta

from app.models.incident import ACTIVE_INCIDENT_STATUSES, Incident, IncidentStatus
from app.schemas.alertmanager import AlertmanagerWebhook
from app.services.incidents import IncidentService


def webhook(
    status: str = "firing", *, starts_at: datetime = datetime(2026, 9, 28, 4, tzinfo=UTC)
) -> AlertmanagerWebhook:
    ends_at = starts_at + timedelta(minutes=5) if status == "resolved" else None
    return AlertmanagerWebhook.model_validate(
        {
            "version": "4",
            "status": status,
            "receiver": "incident-response-api",
            "alerts": [
                {
                    "status": status,
                    "labels": {
                        "alertname": "CheckoutHighErrorRate",
                        "service": "checkout",
                        "environment": "production",
                        "severity": "critical",
                    },
                    "annotations": {"summary": "Checkout failures"},
                    "startsAt": starts_at.isoformat(),
                    "endsAt": ends_at.isoformat() if ends_at else None,
                    "fingerprint": "abc123",
                }
            ],
        }
    )


class FakeRepository:
    def __init__(self):
        self.incidents: list[Incident] = []
        self.events = []
        self.commits = 0

    def find_active_by_fingerprint(self, fingerprint):
        return next(
            (
                item
                for item in self.incidents
                if item.fingerprint == fingerprint and item.status in ACTIVE_INCIDENT_STATUSES
            ),
            None,
        )

    def find_latest_by_fingerprint(self, fingerprint):
        return next(
            (item for item in reversed(self.incidents) if item.fingerprint == fingerprint),
            None,
        )

    def find_by_external_alert_id(self, external_alert_id):
        return next(
            (item for item in self.incidents if item.external_alert_id == external_alert_id),
            None,
        )

    def create(self, **kwargs):
        kwargs.setdefault("status", IncidentStatus.DETECTED)
        kwargs.setdefault("id", uuid.uuid4())
        incident = Incident(**kwargs)
        self.incidents.append(incident)
        return incident

    def create_active_or_get(self, **kwargs):
        active = self.find_active_by_fingerprint(kwargs["fingerprint"])
        return active or self.create(**kwargs)

    def append_event(self, incident, **kwargs):
        self.events.append((incident, kwargs))

    def commit(self):
        self.commits += 1


def test_firing_alert_creates_incident_and_event_without_root_cause() -> None:
    repository = FakeRepository()
    created = IncidentService(repository).ingest_alertmanager(webhook())
    assert len(created) == 1
    assert created[0].status == IncidentStatus.DETECTED
    assert created[0].confirmed_root_cause is None
    assert repository.events[0][1]["event_type"] == "ALERT_RECEIVED"


def test_same_fingerprint_deduplicates_active_incident() -> None:
    repository = FakeRepository()
    service = IncidentService(repository)
    first = service.ingest_alertmanager(webhook())[0]
    second = service.ingest_alertmanager(webhook())[0]
    assert first is second
    assert len(repository.incidents) == 1
    assert len(repository.events) == 2


def test_resolved_alert_records_resolution() -> None:
    repository = FakeRepository()
    service = IncidentService(repository)
    incident = service.ingest_alertmanager(webhook())[0]
    resolved = service.ingest_alertmanager(webhook("resolved"))[0]
    assert resolved is incident
    assert resolved.status == IncidentStatus.RESOLVED
    assert resolved.resolved_at == datetime(2026, 9, 28, 4, 5, tzinfo=UTC)
    repeated = service.ingest_alertmanager(webhook("resolved"))[0]
    assert repeated is incident
    assert len(repository.incidents) == 1


def test_resolved_alert_can_close_incident_waiting_for_approval() -> None:
    repository = FakeRepository()
    service = IncidentService(repository)
    incident = service.ingest_alertmanager(webhook())[0]
    incident.status = IncidentStatus.AWAITING_APPROVAL

    resolved = service.ingest_alertmanager(webhook("resolved"))[0]

    assert resolved is incident
    assert resolved.status == IncidentStatus.RESOLVED
    assert resolved.resolved_at == datetime(2026, 9, 28, 4, 5, tzinfo=UTC)
    assert repository.events[-1][1]["event_type"] == "ALERT_RECEIVED"


def test_same_fingerprint_creates_distinct_incident_after_resolution() -> None:
    repository = FakeRepository()
    service = IncidentService(repository)
    first_start = datetime(2026, 9, 28, 4, tzinfo=UTC)
    second_start = first_start + timedelta(hours=1)

    first = service.ingest_alertmanager(webhook(starts_at=first_start))[0]
    assert service.ingest_alertmanager(webhook(starts_at=first_start))[0] is first
    assert service.ingest_alertmanager(webhook("resolved", starts_at=first_start))[0] is first

    second = service.ingest_alertmanager(webhook(starts_at=second_start))[0]
    assert service.ingest_alertmanager(webhook(starts_at=second_start))[0] is second
    assert second.id != first.id
    assert second.external_alert_id != first.external_alert_id
    assert first.status == IncidentStatus.RESOLVED
    assert second.status == IncidentStatus.DETECTED
    assert len(repository.incidents) == 2
    assert all(incident.confirmed_root_cause is None for incident in repository.incidents)

    resolved_second = service.ingest_alertmanager(webhook("resolved", starts_at=second_start))[0]
    assert resolved_second is second
    assert second.status == IncidentStatus.RESOLVED
    assert len(repository.incidents) == 2


def test_stale_resolution_does_not_resolve_new_occurrence() -> None:
    repository = FakeRepository()
    service = IncidentService(repository)
    first_start = datetime(2026, 9, 28, 4, tzinfo=UTC)
    second_start = first_start + timedelta(hours=1)
    first = service.ingest_alertmanager(webhook(starts_at=first_start))[0]
    service.ingest_alertmanager(webhook("resolved", starts_at=first_start))
    second = service.ingest_alertmanager(webhook(starts_at=second_start))[0]

    stale = service.ingest_alertmanager(webhook("resolved", starts_at=first_start))[0]

    assert stale is first
    assert second.status == IncidentStatus.DETECTED
