import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.core.errors import ApplicationError
from app.models.incident import Incident, IncidentStatus, Recommendation
from app.services.workflow import IncidentWorkflowService
from app.tools.schemas import MetricResult, MetricSample, ServiceName


class WorkflowRepository:
    def __init__(self, incident, recommendation):
        self.incident = incident
        self.recommendation = recommendation
        self.approval = None
        self.execution = None
        self.evidence = []

    def get(self, incident_id):
        return self.incident if incident_id == self.incident.id else None

    def get_recommendation(self, recommendation_id):
        return self.recommendation if recommendation_id == self.recommendation.id else None

    def get_approval(self, recommendation_id):
        return self.approval

    def add_approval(self, recommendation_id, **values):
        self.approval = type("Approval", (), {"decision": values["decision"]})()
        return self.approval

    def get_execution(self, recommendation_id):
        return self.execution

    def add_execution(self, recommendation_id, **values):
        self.execution = type("Execution", (), values)()
        return self.execution

    def append_event(self, incident, **values):
        return None

    def add_evidence(self, incident_id, **values):
        self.evidence.append(values)
        return values

    def commit(self):
        return None


def records():
    now = datetime.now(UTC)
    incident = Incident(
        id=uuid.uuid4(),
        title="Checkout failures",
        service="checkout",
        environment="test",
        severity="critical",
        status=IncidentStatus.AWAITING_APPROVAL,
        started_at=now,
        detected_at=now,
    )
    recommendation = Recommendation(
        id=uuid.uuid4(),
        incident_id=incident.id,
        action_type="ROLLBACK_CHECKOUT_DEMO",
        description="Rollback checkout",
        rationale="Evidence supports rollback",
        risk_level="MEDIUM",
        approval_required=True,
        status="PENDING",
    )
    return incident, recommendation


class RecoveryPrometheus:
    def __init__(self, *, latency: float):
        self.latency = latency

    @staticmethod
    def _result(name: str, value: float, *, samples: bool = True) -> MetricResult:
        now = datetime.now(UTC)
        return MetricResult(
            query_name=name,
            service=ServiceName.CHECKOUT,
            samples=[MetricSample(timestamp=now, value=value)] if samples else [],
            observed_at=now,
        )

    async def get_error_rate(self, service):
        return self._result("error_rate", 0.01)

    async def get_latency(self, service):
        return self._result("latency_p95", self.latency)

    async def get_service_health(self, service):
        return self._result("service_health", 1)

    async def get_active_alerts(self, service):
        return self._result("active_alerts", 0, samples=False)

    async def get_db_pool_state(self, service):
        return self._result("pool_available", 5)

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_action_cannot_execute_without_human_approval():
    incident, recommendation = records()
    workflow = IncidentWorkflowService(
        WorkflowRepository(incident, recommendation),
        gateway_base_url="http://demo.test",
        timeout=1,
    )
    try:
        with pytest.raises(ApplicationError) as captured:
            await workflow.execute(incident.id, recommendation.id)
    finally:
        await workflow.close()
    assert captured.value.code == "ACTION_NOT_APPROVED"


@pytest.mark.asyncio
async def test_rejected_action_cannot_execute():
    incident, recommendation = records()
    repository = WorkflowRepository(incident, recommendation)
    workflow = IncidentWorkflowService(repository, gateway_base_url="http://demo.test", timeout=1)
    workflow.decide(
        incident.id,
        recommendation.id,
        decision="REJECTED",
        approver_identifier="operator@example.com",
        comment="Evidence is insufficient",
    )
    try:
        with pytest.raises(ApplicationError) as captured:
            await workflow.execute(incident.id, recommendation.id)
    finally:
        await workflow.close()
    assert captured.value.code == "ACTION_NOT_APPROVED"


@pytest.mark.asyncio
async def test_approved_action_is_executed_once():
    incident, recommendation = records()
    repository = WorkflowRepository(incident, recommendation)
    workflow = IncidentWorkflowService(repository, gateway_base_url="http://demo.test", timeout=1)
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "succeeded"})

    await workflow.actions._client.aclose()
    workflow.actions._client = httpx.AsyncClient(
        base_url="http://demo.test", transport=httpx.MockTransport(handler)
    )
    workflow.decide(
        incident.id,
        recommendation.id,
        decision="APPROVED",
        approver_identifier="operator@example.com",
        comment=None,
    )
    try:
        first = await workflow.execute(incident.id, recommendation.id)
        second = await workflow.execute(incident.id, recommendation.id)
    finally:
        await workflow.close()

    assert first is second
    assert calls == 1
    assert incident.status == IncidentStatus.VERIFYING_RECOVERY


@pytest.mark.asyncio
async def test_recovery_requires_latency_to_improve():
    incident, recommendation = records()
    incident.status = IncidentStatus.VERIFYING_RECOVERY
    repository = WorkflowRepository(incident, recommendation)
    workflow = IncidentWorkflowService(
        repository,
        gateway_base_url="http://demo.test",
        timeout=1,
        prometheus=RecoveryPrometheus(latency=0.8),
        recovery_wait=0,
    )

    try:
        result = await workflow.verify_recovery(incident.id)
    finally:
        await workflow.close()

    assert not result.recovered
    assert not result.evidence["checks"]["latency_improved"]
    assert incident.status == IncidentStatus.VERIFYING_RECOVERY
