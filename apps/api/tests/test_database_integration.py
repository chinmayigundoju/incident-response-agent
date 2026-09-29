import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_incident_service
from app.main import app
from app.models.incident import Incident, IncidentEvent, IncidentStatus
from app.repositories.incidents import IncidentRepository
from app.schemas.alertmanager import AlertmanagerWebhook
from app.services.incidents import IncidentService

TEST_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL is not configured")


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    api_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["DATABASE_URL"] = TEST_URL or ""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=api_root,
        env=environment,
        check=True,
    )


def test_incident_event_uniqueness_timezone_and_foreign_keys() -> None:
    engine = create_engine(TEST_URL)
    started = datetime.now(UTC)
    external_alert_id = f"integration-alert-{uuid.uuid4()}"
    fingerprint = f"integration-fingerprint-{uuid.uuid4()}"
    with Session(engine) as session:
        incident = Incident(
            external_alert_id=external_alert_id,
            fingerprint=fingerprint,
            title="Integration alert",
            service="checkout",
            environment="test",
            severity="warning",
            started_at=started,
        )
        session.add(incident)
        session.flush()
        session.add(
            IncidentEvent(
                incident_id=incident.id,
                actor_type="SYSTEM",
                event_type="ALERT_RECEIVED",
                source="test",
                payload={},
            )
        )
        session.commit()
        session.refresh(incident)
        assert incident.started_at.tzinfo is not None

        duplicate = Incident(
            external_alert_id=external_alert_id,
            title="Duplicate",
            service="checkout",
            environment="test",
            severity="warning",
            started_at=started,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        session.execute(delete(Incident).where(Incident.fingerprint == fingerprint))
        session.commit()
        session.rollback()

        session.add(
            IncidentEvent(
                incident_id=uuid.uuid4(),
                actor_type="SYSTEM",
                event_type="INVALID",
                source="test",
                payload={},
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def alert_payload(*, fingerprint: str, starts_at: str, status: str) -> dict[str, object]:
    return {
        "version": "4",
        "status": status,
        "receiver": "incident-response-api",
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "CheckoutDatabasePoolSaturation",
                    "service": "checkout",
                    "environment": "test",
                    "severity": "critical",
                },
                "annotations": {"summary": "Checkout database pool is saturated"},
                "startsAt": starts_at,
                "endsAt": "2026-09-28T05:05:00Z" if status == "resolved" else None,
                "fingerprint": fingerprint,
            }
        ],
    }


def test_recurring_webhook_creates_new_history_without_500() -> None:
    engine = create_engine(TEST_URL)
    fingerprint = f"recurring-{uuid.uuid4()}"
    first_start = "2026-09-28T04:00:00Z"
    second_start = "2026-09-28T05:00:00Z"
    with Session(engine, expire_on_commit=False) as session:
        app.dependency_overrides[get_incident_service] = lambda: IncidentService(
            IncidentRepository(session)
        )
        client = TestClient(app)
        try:
            first = client.post(
                "/webhooks/alertmanager",
                json=alert_payload(fingerprint=fingerprint, starts_at=first_start, status="firing"),
            )
            repeated_first = client.post(
                "/webhooks/alertmanager",
                json=alert_payload(fingerprint=fingerprint, starts_at=first_start, status="firing"),
            )
            resolved_first = client.post(
                "/webhooks/alertmanager",
                json=alert_payload(
                    fingerprint=fingerprint, starts_at=first_start, status="resolved"
                ),
            )
            second = client.post(
                "/webhooks/alertmanager",
                json=alert_payload(
                    fingerprint=fingerprint, starts_at=second_start, status="firing"
                ),
            )
            repeated_second = client.post(
                "/webhooks/alertmanager",
                json=alert_payload(
                    fingerprint=fingerprint, starts_at=second_start, status="firing"
                ),
            )
            resolved_second = client.post(
                "/webhooks/alertmanager",
                json=alert_payload(
                    fingerprint=fingerprint, starts_at=second_start, status="resolved"
                ),
            )

            responses = [
                first,
                repeated_first,
                resolved_first,
                second,
                repeated_second,
                resolved_second,
            ]
            assert all(response.status_code == 200 for response in responses)
            first_id = first.json()["incident_ids"][0]
            second_id = second.json()["incident_ids"][0]
            assert repeated_first.json()["incident_ids"] == [first_id]
            assert resolved_first.json()["incident_ids"] == [first_id]
            assert repeated_second.json()["incident_ids"] == [second_id]
            assert resolved_second.json()["incident_ids"] == [second_id]
            assert second_id != first_id

            session.expire_all()
            incidents = session.scalars(
                select(Incident)
                .where(Incident.fingerprint == fingerprint)
                .order_by(Incident.started_at)
            ).all()
            assert len(incidents) == 2
            assert [incident.status for incident in incidents] == [
                IncidentStatus.RESOLVED,
                IncidentStatus.RESOLVED,
            ]
            assert all(incident.confirmed_root_cause is None for incident in incidents)
        finally:
            app.dependency_overrides.clear()
            session.rollback()
            session.execute(delete(Incident).where(Incident.fingerprint == fingerprint))
            session.commit()


def test_database_allows_history_but_rejects_two_active_incidents() -> None:
    engine = create_engine(TEST_URL)
    fingerprint = f"active-constraint-{uuid.uuid4()}"
    started = datetime.now(UTC)
    with Session(engine) as session:
        try:
            session.add_all(
                [
                    Incident(
                        external_alert_id=f"history-{uuid.uuid4()}",
                        fingerprint=fingerprint,
                        title="Resolved occurrence",
                        service="checkout",
                        environment="test",
                        severity="critical",
                        status=IncidentStatus.RESOLVED,
                        started_at=started,
                        resolved_at=started,
                    ),
                    Incident(
                        external_alert_id=f"active-{uuid.uuid4()}",
                        fingerprint=fingerprint,
                        title="Active occurrence",
                        service="checkout",
                        environment="test",
                        severity="critical",
                        status=IncidentStatus.DETECTED,
                        started_at=started,
                    ),
                ]
            )
            session.commit()

            session.add(
                Incident(
                    external_alert_id=f"duplicate-active-{uuid.uuid4()}",
                    fingerprint=fingerprint,
                    title="Conflicting active occurrence",
                    service="checkout",
                    environment="test",
                    severity="critical",
                    status=IncidentStatus.INVESTIGATING,
                    started_at=started,
                )
            )
            with pytest.raises(IntegrityError) as captured:
                session.flush()
            assert captured.value.orig.diag.constraint_name == "uq_incidents_active_fingerprint"
        finally:
            session.rollback()
            session.execute(delete(Incident).where(Incident.fingerprint == fingerprint))
            session.commit()


def test_simultaneous_firing_deliveries_converge_on_one_active_incident() -> None:
    engine = create_engine(TEST_URL)
    fingerprint = f"concurrent-{uuid.uuid4()}"
    payload = AlertmanagerWebhook.model_validate(
        alert_payload(
            fingerprint=fingerprint,
            starts_at="2026-09-28T06:00:00Z",
            status="firing",
        )
    )
    barrier = threading.Barrier(2)

    class RacingRepository(IncidentRepository):
        def __init__(self, session):
            super().__init__(session)
            self.waited = False

        def find_active_by_fingerprint(self, candidate):
            incident = super().find_active_by_fingerprint(candidate)
            if incident is None and not self.waited:
                self.waited = True
                barrier.wait(timeout=10)
            return incident

    def deliver() -> uuid.UUID:
        with Session(engine) as session:
            incident = IncidentService(RacingRepository(session)).ingest_alertmanager(payload)[0]
            return incident.id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(deliver) for _ in range(2)]
            incident_ids = [future.result(timeout=20) for future in futures]

        assert incident_ids[0] == incident_ids[1]
        with Session(engine) as session:
            incidents = session.scalars(
                select(Incident).where(Incident.fingerprint == fingerprint)
            ).all()
            assert len(incidents) == 1
            assert incidents[0].status == IncidentStatus.DETECTED
    finally:
        with Session(engine) as session:
            session.execute(delete(Incident).where(Incident.fingerprint == fingerprint))
            session.commit()
