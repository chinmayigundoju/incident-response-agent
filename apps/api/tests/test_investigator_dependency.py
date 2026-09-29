import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.services.runtime as runtime
from app.agent.investigator import Investigator
from app.agent.policies import ALLOWED_INVESTIGATION_TOOLS
from app.agent.schemas import EvidenceType, InvestigationEvidence
from app.agent.tool_registry import ToolRegistry
from app.api.dependencies import get_investigator
from app.core.config import Settings
from app.llm.fake import FakeProvider
from app.main import app
from app.models.incident import Incident, IncidentStatus
from app.tools.deployments import DeploymentRecord
from app.tools.runbooks import RunbookDocument
from app.tools.schemas import (
    LogResult,
    MetricResult,
    MetricSample,
    ServiceName,
    TraceResult,
)

EXPECTED_INVESTIGATION_TOOLS = {
    "get_incident_context",
    "get_service_health",
    "get_error_rate",
    "get_latency",
    "get_db_pool_state",
    "get_payment_latency",
    "search_service_logs",
    "search_error_logs",
    "search_connection_timeout_logs",
    "search_payment_latency_logs",
    "search_recent_traces",
    "get_trace",
    "get_recent_deployments",
    "get_runbook",
    "recall_incidents",
}


class ClosableFakeProvider(FakeProvider):
    def __init__(self, *_args, **_kwargs):
        self.options = _kwargs

    async def close(self):
        return None


class RouteRepository:
    def __init__(self, incident: Incident):
        self.incident = incident

    def get(self, incident_id):
        return self.incident if incident_id == self.incident.id else None

    def append_event(self, incident, **values):
        return values

    def add_evidence(self, incident_id, **values):
        return values

    def add_hypothesis(self, incident_id, **values):
        return values

    def add_recommendation(self, incident_id, **values):
        return type("Recommendation", (), {"id": uuid.uuid4()})()

    def commit(self):
        return None


class FakePrometheus:
    @staticmethod
    def result(name: str, service: ServiceName) -> MetricResult:
        now = datetime.now(UTC)
        return MetricResult(
            query_name=name,
            service=service,
            samples=[MetricSample(timestamp=now, value=1)],
            observed_at=now,
        )

    async def get_service_health(self, service):
        return self.result("service_health", service)

    async def get_error_rate(self, service):
        return self.result("error_rate", service)

    async def get_latency(self, service):
        return self.result("latency_p95", service)

    async def get_db_pool_state(self, service):
        return self.result("pool_available", service)

    async def get_payment_latency(self):
        return self.result("payment_latency", ServiceName.PAYMENT)

    async def close(self):
        return None


class FakeLoki:
    @staticmethod
    def result(name: str, service: ServiceName = ServiceName.CHECKOUT) -> LogResult:
        return LogResult(
            query_name=name,
            service=service,
            records=[],
            observed_at=datetime.now(UTC),
        )

    async def search_service_logs(self, service):
        return self.result("service_logs", service)

    async def search_error_logs(self, service):
        return self.result("error_logs", service)

    async def search_connection_timeout_logs(self):
        return self.result("connection_timeout_logs")

    async def search_payment_latency_logs(self):
        return self.result("payment_latency_logs", ServiceName.PAYMENT)

    async def close(self):
        return None


class FakeTempo:
    async def search_recent_traces(self, service):
        return TraceResult(
            query_name="recent_traces",
            service=service,
            observed_at=datetime.now(UTC),
        )

    async def get_trace(self, _trace_id):
        return TraceResult(query_name="trace_by_id", observed_at=datetime.now(UTC))

    async def close(self):
        return None


class FakeDeployments:
    async def get_recent_deployments(self, service):
        return [
            DeploymentRecord(
                service=service,
                version="2.18",
                deployed_at=datetime.now(UTC),
                previous_version="2.17",
                simulated=True,
                change_summary="Test deployment",
            )
        ]

    async def close(self):
        return None


class FakeRunbooks:
    @staticmethod
    def list_for_service(_service):
        return ("checkout-db-pool",)

    @staticmethod
    def get(service, slug):
        return RunbookDocument(
            slug=slug,
            title="Checkout DB pool",
            service=service,
            version="1",
            content="Read-only test runbook",
        )


class FakeIncidentContext:
    @staticmethod
    def get_incident_context(incident_id):
        return {"incident": {"id": str(incident_id)}}


class FakeHindsight:
    @staticmethod
    async def recall_incidents(*, service, environment, query):
        return InvestigationEvidence(
            type=EvidenceType.HISTORICAL_MEMORY,
            source="hindsight",
            service=service,
            summary="Historical memory unavailable in deterministic test",
            details={"available": False, "classification": "HISTORICAL_EVIDENCE"},
        )


def build_registry() -> ToolRegistry:
    return ToolRegistry(
        timeout=1,
        prometheus=FakePrometheus(),
        loki=FakeLoki(),
        tempo=FakeTempo(),
        deployments=FakeDeployments(),
        runbooks=FakeRunbooks(),
        incident_context=FakeIncidentContext(),
        hindsight=FakeHindsight(),
    )


def test_read_only_tool_allowlist_is_unchanged():
    assert ALLOWED_INVESTIGATION_TOOLS == EXPECTED_INVESTIGATION_TOOLS
    forbidden = {"shell", "sql", "docker", "filesystem_write", "kubectl", "promql"}
    assert forbidden.isdisjoint(ALLOWED_INVESTIGATION_TOOLS)


@pytest.mark.asyncio
async def test_fastapi_investigator_dependency_constructs_actual_registry(monkeypatch):
    monkeypatch.setattr(runtime, "GroqProvider", ClosableFakeProvider)
    settings = Settings(
        _env_file=None,
        GROQ_API_KEY="configured-for-test",
        HINDSIGHT_BASE_URL=None,
        HINDSIGHT_API_KEY=None,
        RUNBOOK_ROOT=str(Path(__file__).resolve().parents[3] / "runbooks"),
    )
    dependency = get_investigator(object(), settings)

    investigator = await anext(dependency)
    try:
        assert isinstance(investigator, Investigator)
        assert isinstance(investigator.tools, ToolRegistry)
        assert investigator.tools.timeout == settings.AGENT_TOOL_TIMEOUT_SECONDS
        assert (
            investigator.provider.options["max_evidence_chars"] == settings.GROQ_MAX_EVIDENCE_CHARS
        )
        assert (
            investigator.provider.options["rate_limit_max_wait"]
            == settings.GROQ_RATE_LIMIT_MAX_WAIT_SECONDS
        )
    finally:
        await dependency.aclose()


@pytest.mark.asyncio
async def test_actual_registry_still_rejects_unknown_tools():
    registry = build_registry()
    try:
        with pytest.raises(ValueError, match="disallowed"):
            await registry.execute("shell", incident={"service": "checkout"})
    finally:
        await registry.close()


def test_investigate_endpoint_runs_fake_provider_without_dependency_500():
    now = datetime.now(UTC)
    incident = Incident(
        id=uuid.uuid4(),
        title="Checkout failures",
        service="checkout",
        environment="test",
        severity="critical",
        status=IncidentStatus.DETECTED,
        started_at=now,
        detected_at=now,
    )
    investigator = Investigator(
        RouteRepository(incident),
        FakeProvider(),
        build_registry(),
        max_iterations=8,
    )
    app.dependency_overrides[get_investigator] = lambda: investigator
    try:
        response = TestClient(app).post(f"/api/v1/incidents/{incident.id}/investigate")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["incident_id"] == str(incident.id)
    assert response.json()["status"] == IncidentStatus.AWAITING_APPROVAL
    assert response.json()["iterations"] == 8
    assert len(response.json()["tool_calls"]) == 7
