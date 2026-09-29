import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from pydantic import ValidationError

from app.agent.policies import ALLOWED_ACTIONS
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.memory.schemas import RetentionResult
from app.models.incident import Incident, IncidentStatus, Recommendation
from app.schemas.workflow import RecoveryResult
from app.services.automation import IncidentAutomationDispatcher, IncidentAutomationService


def settings(mode: str = "assisted", **overrides) -> Settings:
    values = {
        "_env_file": None,
        "APP_ENV": "test",
        "INCIDENT_AUTOMATION_MODE": mode,
        "DEMO_GATEWAY_BASE_URL": "http://localhost:8100",
        "AUTOMATION_RECOVERY_MAX_ATTEMPTS": 2,
        "AUTOMATION_RECOVERY_RETRY_SECONDS": 0,
    }
    values.update(overrides)
    return Settings(**values)


def incident(status: IncidentStatus = IncidentStatus.DETECTED) -> Incident:
    now = datetime.now(UTC)
    return Incident(
        id=uuid.uuid4(),
        title="CheckoutDatabasePoolSaturation",
        service="checkout",
        environment="test",
        severity="critical",
        status=status,
        started_at=now,
        detected_at=now,
    )


def recommendation(item: Incident, action: str = "ROLLBACK_CHECKOUT_DEMO") -> Recommendation:
    return Recommendation(
        id=uuid.uuid4(),
        incident_id=item.id,
        action_type=action,
        description="Controlled rollback",
        rationale="Current evidence supports rollback",
        risk_level="MEDIUM",
        approval_required=True,
        status="PENDING",
    )


class AutomationRepository:
    def __init__(self, item: Incident, rec: Recommendation | None = None):
        self.incident = item
        self.recommendation = rec
        self.events: list[dict[str, object]] = []
        self.postmortem = None
        self.commits = 0
        self.rollbacks = 0

    def get_for_update(self, incident_id):
        return self.incident if incident_id == self.incident.id else None

    def get(self, incident_id):
        return self.incident if incident_id == self.incident.id else None

    def append_event(self, incident, **values):
        self.events.append(values)
        return values

    def list_recommendations(self, incident_id):
        return [self.recommendation] if self.recommendation else []

    def get_postmortem(self, incident_id):
        return self.postmortem

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeInvestigator:
    def __init__(self, repository: AutomationRepository):
        self.repository = repository
        self.calls = 0

    async def investigate(self, incident_id):
        self.calls += 1
        self.repository.incident.status = IncidentStatus.AWAITING_APPROVAL
        return SimpleNamespace(iterations=8)


class FakeWorkflow:
    def __init__(
        self,
        repository: AutomationRepository,
        *,
        recovered: list[bool] | None = None,
    ):
        self.repository = repository
        self.approved = False
        self.executed = False
        self.execute_calls = 0
        self.verify_calls = 0
        self.generate_calls = 0
        self.commit_calls = 0
        self.recovery = list(recovered or [True])

    def decide(self, incident_id, recommendation_id, **values):
        assert values["decision"] == "APPROVED"
        self.approved = True
        self.repository.recommendation.status = "APPROVED"
        return SimpleNamespace(decision="APPROVED")

    async def execute(self, incident_id, recommendation_id):
        if not self.approved:
            raise ApplicationError("ACTION_NOT_APPROVED", "Human approval is required", 409)
        if self.executed:
            return SimpleNamespace(status="SUCCEEDED")
        self.executed = True
        self.execute_calls += 1
        self.repository.incident.status = IncidentStatus.VERIFYING_RECOVERY
        return SimpleNamespace(status="SUCCEEDED")

    async def verify_recovery(self, incident_id):
        self.verify_calls += 1
        recovered = self.recovery.pop(0) if self.recovery else False
        if recovered:
            self.repository.incident.status = IncidentStatus.RESOLVED
        return RecoveryResult(
            recovered=recovered,
            status=self.repository.incident.status,
            evidence={},
        )

    def generate_postmortem(self, incident_id):
        self.generate_calls += 1
        self.repository.incident.status = IncidentStatus.POSTMORTEM_REVIEW
        self.repository.postmortem = SimpleNamespace(approved_at=None)
        return self.repository.postmortem

    async def commit_memory(self, incident_id, coordinator):
        self.commit_calls += 1
        self.repository.incident.status = IncidentStatus.MEMORY_COMMITTED
        return RetentionResult(
            bank_id="test-bank",
            document_id=f"incident:{incident_id}",
            retained=True,
        )


class RecordingWorker:
    def __init__(self):
        self.investigations = []
        self.approvals = []
        self.root_causes = []
        self.postmortems = []

    async def investigate(self, incident_id):
        self.investigations.append(incident_id)

    async def after_approval(self, incident_id, recommendation_id):
        self.approvals.append((incident_id, recommendation_id))

    async def after_root_cause(self, incident_id):
        self.root_causes.append(incident_id)

    async def after_postmortem_approval(self, incident_id):
        self.postmortems.append(incident_id)


@pytest.mark.asyncio
async def test_new_incident_is_scheduled_once_per_webhook_batch_in_assisted_mode():
    item = incident()
    worker = RecordingWorker()
    dispatcher = IncidentAutomationDispatcher(settings(), worker)
    tasks = BackgroundTasks()

    dispatcher.new_incidents(tasks, [item.id, item.id])
    await tasks()

    assert worker.investigations == [item.id]


@pytest.mark.asyncio
async def test_duplicate_alert_claim_does_not_start_second_investigation():
    item = incident()
    repository = AutomationRepository(item)
    automation = IncidentAutomationService(repository, settings())
    investigator = FakeInvestigator(repository)

    assert automation.claim_investigation(item.id) is True
    result = await investigator.investigate(item.id)
    automation.investigation_completed(item.id, iterations=result.iterations)
    assert automation.claim_investigation(item.id) is False

    assert investigator.calls == 1
    assert item.status == IncidentStatus.AWAITING_APPROVAL
    assert [event["event_type"] for event in repository.events].count(
        "AUTO_INVESTIGATION_STARTED"
    ) == 1


@pytest.mark.asyncio
async def test_assisted_investigation_stops_at_human_approval_gate():
    item = incident()
    rec = recommendation(item)
    repository = AutomationRepository(item, rec)
    automation = IncidentAutomationService(repository, settings())
    investigator = FakeInvestigator(repository)
    workflow = FakeWorkflow(repository)

    assert automation.claim_investigation(item.id)
    result = await investigator.investigate(item.id)
    automation.investigation_completed(item.id, iterations=result.iterations)

    assert item.status == IncidentStatus.AWAITING_APPROVAL
    assert workflow.execute_calls == 0
    assert "AUTOMATION_WAITING_FOR_APPROVAL" in [event["event_type"] for event in repository.events]


@pytest.mark.asyncio
async def test_approval_executes_once_and_verified_recovery_resolves():
    item = incident(IncidentStatus.AWAITING_APPROVAL)
    rec = recommendation(item)
    repository = AutomationRepository(item, rec)
    automation = IncidentAutomationService(repository, settings())
    workflow = FakeWorkflow(repository, recovered=[True])
    workflow.decide(item.id, rec.id, decision="APPROVED")

    await automation.continue_after_approval(item.id, rec.id, workflow)
    await automation.continue_after_approval(item.id, rec.id, workflow)

    assert workflow.execute_calls == 1
    assert workflow.verify_calls == 1
    assert item.status == IncidentStatus.RESOLVED
    assert "AUTO_RECOVERY_VERIFIED" in [event["event_type"] for event in repository.events]


@pytest.mark.asyncio
async def test_failed_recovery_retries_bounded_and_does_not_resolve():
    item = incident(IncidentStatus.AWAITING_APPROVAL)
    rec = recommendation(item)
    repository = AutomationRepository(item, rec)
    automation = IncidentAutomationService(repository, settings(), sleep=lambda _: _no_sleep())
    workflow = FakeWorkflow(repository, recovered=[False, False])
    workflow.decide(item.id, rec.id, decision="APPROVED")

    await automation.continue_after_approval(item.id, rec.id, workflow)

    assert workflow.execute_calls == 1
    assert workflow.verify_calls == 2
    assert item.status == IncidentStatus.VERIFYING_RECOVERY
    assert repository.events[-1]["event_type"] == "AUTOMATION_FAILED"


async def _no_sleep():
    return None


def test_confirmed_root_cause_generates_postmortem_once():
    item = incident(IncidentStatus.RESOLVED)
    item.confirmed_root_cause = "Checkout v2.18 reduced the database pool"
    repository = AutomationRepository(item)
    automation = IncidentAutomationService(repository, settings())
    workflow = FakeWorkflow(repository)

    automation.continue_after_root_cause(item.id, workflow)
    automation.continue_after_root_cause(item.id, workflow)

    assert workflow.generate_calls == 1
    assert item.status == IncidentStatus.POSTMORTEM_REVIEW
    assert "AUTO_POSTMORTEM_GENERATED" in [event["event_type"] for event in repository.events]


@pytest.mark.asyncio
async def test_postmortem_approval_commits_memory_once():
    item = incident(IncidentStatus.POSTMORTEM_REVIEW)
    repository = AutomationRepository(item)
    repository.postmortem = SimpleNamespace(approved_at=datetime.now(UTC))
    automation = IncidentAutomationService(repository, settings())
    workflow = FakeWorkflow(repository)

    await automation.continue_after_postmortem_approval(item.id, workflow, object())
    await automation.continue_after_postmortem_approval(item.id, workflow, object())

    assert workflow.commit_calls == 1
    assert item.status == IncidentStatus.MEMORY_COMMITTED
    assert "AUTO_MEMORY_COMMITTED" in [event["event_type"] for event in repository.events]


@pytest.mark.asyncio
async def test_manual_mode_preserves_manual_behavior():
    item = incident()
    worker = RecordingWorker()
    dispatcher = IncidentAutomationDispatcher(settings("manual"), worker)
    tasks = BackgroundTasks()

    dispatcher.new_incidents(tasks, [item.id])
    dispatcher.approved(tasks, item.id, uuid.uuid4())
    dispatcher.root_cause_confirmed(tasks, item.id)
    dispatcher.postmortem_approved(tasks, item.id)
    await tasks()

    assert worker.investigations == []
    assert worker.approvals == []
    assert worker.root_causes == []
    assert worker.postmortems == []


@pytest.mark.asyncio
async def test_demo_autopilot_executes_only_simulated_allowlisted_action():
    item = incident(IncidentStatus.AWAITING_APPROVAL)
    rec = recommendation(item)
    repository = AutomationRepository(item, rec)
    automation = IncidentAutomationService(repository, settings("demo_autopilot"))
    workflow = FakeWorkflow(repository, recovered=[True])

    await automation.continue_demo_autopilot(item.id, workflow)

    assert workflow.approved is True
    assert workflow.execute_calls == 1
    assert item.status == IncidentStatus.RESOLVED


@pytest.mark.asyncio
async def test_demo_autopilot_rejects_non_executable_action():
    item = incident(IncidentStatus.AWAITING_APPROVAL)
    rec = recommendation(item, action="ESCALATE")
    repository = AutomationRepository(item, rec)
    automation = IncidentAutomationService(repository, settings("demo_autopilot"))
    workflow = FakeWorkflow(repository)

    await automation.continue_demo_autopilot(item.id, workflow)

    assert workflow.approved is False
    assert workflow.execute_calls == 0
    assert item.status == IncidentStatus.AWAITING_APPROVAL
    assert repository.events[-1]["event_type"] == "AUTOMATION_FAILED"
    assert rec.action_type in ALLOWED_ACTIONS


def test_demo_autopilot_configuration_is_rejected_outside_simulation():
    with pytest.raises(ValidationError, match="simulated application environment"):
        settings("demo_autopilot", APP_ENV="production")


@pytest.mark.asyncio
async def test_assisted_approval_dispatches_automatic_continuation():
    item = incident(IncidentStatus.AWAITING_APPROVAL)
    rec = recommendation(item)
    worker = RecordingWorker()
    dispatcher = IncidentAutomationDispatcher(settings(), worker)
    tasks = BackgroundTasks()

    dispatcher.approved(tasks, item.id, rec.id)
    await tasks()

    assert worker.approvals == [(item.id, rec.id)]
