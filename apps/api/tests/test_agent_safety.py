import uuid
from datetime import UTC, datetime

import pytest

from app.agent.investigator import Investigator
from app.agent.policies import ALLOWED_INVESTIGATION_TOOLS
from app.agent.schemas import (
    ActionType,
    AgentHypothesis,
    Confidence,
    Diagnosis,
    EvidenceType,
    HypothesisStatus,
    InvestigationEvidence,
    ToolRequest,
)
from app.agent.tool_registry import ToolRegistry
from app.core.errors import ApplicationError
from app.llm.base import ProviderError
from app.llm.fake import FakeProvider
from app.models.incident import Incident, IncidentStatus


class AgentRepository:
    def __init__(self, incident: Incident):
        self.incident = incident
        self.events = []
        self.evidence = []
        self.commits = 0

    def get(self, incident_id):
        return self.incident if incident_id == self.incident.id else None

    def append_event(self, incident, **values):
        self.events.append(values)

    def add_evidence(self, incident_id, **values):
        self.evidence.append(values)

    def add_hypothesis(self, incident_id, **values):
        return values

    def add_recommendation(self, incident_id, **values):
        return type("Recommendation", (), {"id": uuid.uuid4()})()

    def commit(self):
        self.commits += 1


class StaticTools:
    async def execute(self, name, *, incident, arguments=None):
        return InvestigationEvidence(
            type=EvidenceType.METRIC,
            source=name,
            service=str(incident["service"]),
            summary="test evidence",
            details={"samples": [{"value": 0.8}]},
        )


class DiagnosisProvider:
    async def next_step(self, **_):
        return Diagnosis(
            primary_hypothesis=AgentHypothesis(
                statement="checkout pool saturation after deployment",
                status=HypothesisStatus.SUPPORTED,
                confidence=Confidence.HIGH,
            ),
            root_cause_statement="checkout pool saturation after deployment",
            supporting_evidence=[uuid.uuid4()],
            recommended_next_step="Rollback checkout",
            recommended_action=ActionType.ROLLBACK_CHECKOUT_DEMO,
            action_rationale="Correlated evidence",
            risk_level="MEDIUM",
        )


class EndlessProvider:
    def __init__(self):
        self.index = 0

    async def next_step(self, **_):
        tools = ["get_incident_context", "get_error_rate"]
        tool = tools[self.index]
        self.index += 1
        return ToolRequest(name=tool, rationale="collect evidence")


class FailOnceProvider(DiagnosisProvider):
    def __init__(self):
        self.failed = False

    async def next_step(self, **kwargs):
        if not self.failed:
            self.failed = True
            raise ProviderError("temporary provider failure")
        return await super().next_step(**kwargs)


def incident() -> Incident:
    now = datetime.now(UTC)
    return Incident(
        id=uuid.uuid4(),
        title="Checkout failures",
        service="checkout",
        environment="test",
        severity="critical",
        status=IncidentStatus.DETECTED,
        started_at=now,
        detected_at=now,
    )


class ScenarioTools:
    async def execute(self, name, *, incident, arguments=None):
        evidence_type = {
            "search_payment_latency_logs": EvidenceType.LOG,
            "search_connection_timeout_logs": EvidenceType.LOG,
            "search_error_logs": EvidenceType.LOG,
            "search_recent_traces": EvidenceType.TRACE,
            "get_recent_deployments": EvidenceType.DEPLOYMENT,
            "get_runbook": EvidenceType.RUNBOOK,
            "recall_incidents": EvidenceType.HISTORICAL_MEMORY,
        }.get(name, EvidenceType.METRIC)
        return InvestigationEvidence(
            type=evidence_type,
            source=name,
            service=str(incident["service"]),
            summary=f"scenario evidence from {name}",
            details={"available": True},
        )


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected_before_execution():
    registry = object.__new__(ToolRegistry)
    with pytest.raises(ValueError, match="disallowed"):
        await registry.execute("shell", incident={"service": "checkout"})


def test_model_has_no_shell_sql_docker_or_cloud_mutation_tool():
    forbidden = {"shell", "sql", "docker", "kubectl", "cloud", "filesystem_write"}
    assert forbidden.isdisjoint(ALLOWED_INVESTIGATION_TOOLS)


@pytest.mark.asyncio
async def test_investigation_persists_proposal_and_stops_at_human_gate():
    item = incident()
    repository = AgentRepository(item)
    investigator = Investigator(repository, DiagnosisProvider(), StaticTools(), max_iterations=3)

    result = await investigator.investigate(item.id)

    assert result.status == IncidentStatus.AWAITING_APPROVAL.value
    assert item.status == IncidentStatus.AWAITING_APPROVAL
    assert any(event["event_type"] == "DIAGNOSIS_PROPOSED" for event in repository.events)


@pytest.mark.asyncio
async def test_investigation_iteration_limit_is_bounded():
    item = incident()
    investigator = Investigator(
        AgentRepository(item), EndlessProvider(), StaticTools(), max_iterations=2
    )

    with pytest.raises(ApplicationError) as captured:
        await investigator.investigate(item.id)

    assert captured.value.code == "AGENT_ITERATION_LIMIT"


@pytest.mark.asyncio
async def test_provider_failure_can_retry_investigating_incident():
    item = incident()
    repository = AgentRepository(item)
    investigator = Investigator(repository, FailOnceProvider(), StaticTools(), max_iterations=3)

    with pytest.raises(ApplicationError) as captured:
        await investigator.investigate(item.id)

    assert captured.value.code == "INVESTIGATION_PROVIDER_UNAVAILABLE"
    assert item.status == IncidentStatus.INVESTIGATING

    result = await investigator.investigate(item.id)

    assert result.status == IncidentStatus.AWAITING_APPROVAL.value
    assert item.status == IncidentStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_misleading_db_memory_does_not_override_payment_evidence():
    item = incident()
    item.service = "payment"
    investigator = Investigator(
        AgentRepository(item), FakeProvider(), ScenarioTools(), max_iterations=8
    )

    result = await investigator.investigate(item.id)

    assert result.recommended_action == ActionType.RESET_PAYMENT_FAULT
    assert "healthy DB" in result.proposed_diagnosis.root_cause_statement
    assert result.proposed_diagnosis.contradicting_evidence
    assert result.iterations == 8
