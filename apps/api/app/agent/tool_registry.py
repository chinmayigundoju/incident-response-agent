import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from app.agent.policies import ALLOWED_INVESTIGATION_TOOLS
from app.agent.schemas import EvidenceType, InvestigationEvidence
from app.tools.deployments import DeploymentTool
from app.tools.hindsight import HindsightTool
from app.tools.incidents import IncidentContextTool
from app.tools.loki import LokiTool
from app.tools.prometheus import PrometheusTool
from app.tools.runbooks import RunbookTool
from app.tools.schemas import ServiceName, ToolDependencyError
from app.tools.tempo import TempoTool

ToolHandler = Callable[[], Awaitable[Any]]


class ToolRegistry:
    def __init__(
        self,
        *,
        timeout: float,
        prometheus: PrometheusTool,
        loki: LokiTool,
        tempo: TempoTool,
        deployments: DeploymentTool,
        runbooks: RunbookTool,
        incident_context: IncidentContextTool,
        hindsight: HindsightTool,
    ):
        self.timeout = timeout
        self.prometheus = prometheus
        self.loki = loki
        self.tempo = tempo
        self.deployments = deployments
        self.runbooks = runbooks
        self.incident_context = incident_context
        self.hindsight = hindsight

    async def close(self) -> None:
        await asyncio.gather(
            self.prometheus.close(),
            self.loki.close(),
            self.tempo.close(),
            self.deployments.close(),
        )

    async def execute(
        self,
        name: str,
        *,
        incident: dict[str, Any],
        arguments: dict[str, Any] | None = None,
    ) -> InvestigationEvidence:
        if name not in ALLOWED_INVESTIGATION_TOOLS:
            raise ValueError("unknown or disallowed investigation tool")
        arguments = arguments or {}
        allowed_arguments = {"trace_id"} if name == "get_trace" else set()
        if set(arguments) - allowed_arguments:
            raise ValueError("tool arguments are not allowed")
        service = self._service(incident["service"])
        if name == "get_incident_context":
            context = self.incident_context.get_incident_context(uuid.UUID(str(incident["id"])))
            return self._evidence(
                EvidenceType.INCIDENT_CONTEXT,
                name,
                service,
                "Authoritative incident context loaded from PostgreSQL",
                context,
            )
        if name == "get_runbook":
            slug = self.runbooks.list_for_service(service)[0]
            document = self.runbooks.get(service, slug)
            return self._evidence(
                EvidenceType.RUNBOOK,
                f"runbook:{slug}",
                service,
                f"Retrieved runbook: {document.title}",
                document.model_dump(mode="json"),
            )
        if name == "recall_incidents":
            async with asyncio.timeout(self.timeout):
                return await self.hindsight.recall_incidents(
                    service=service.value,
                    environment=str(incident["environment"]),
                    query=str(incident["title"]),
                )
        handlers: dict[str, tuple[EvidenceType, ToolHandler]] = {
            "get_service_health": (
                EvidenceType.METRIC,
                lambda: self.prometheus.get_service_health(service),
            ),
            "get_error_rate": (
                EvidenceType.METRIC,
                lambda: self.prometheus.get_error_rate(service),
            ),
            "get_latency": (
                EvidenceType.METRIC,
                lambda: self.prometheus.get_latency(service),
            ),
            "get_db_pool_state": (
                EvidenceType.METRIC,
                lambda: self.prometheus.get_db_pool_state(service),
            ),
            "get_payment_latency": (
                EvidenceType.METRIC,
                self.prometheus.get_payment_latency,
            ),
            "search_service_logs": (
                EvidenceType.LOG,
                lambda: self.loki.search_service_logs(service),
            ),
            "search_error_logs": (
                EvidenceType.LOG,
                lambda: self.loki.search_error_logs(service),
            ),
            "search_connection_timeout_logs": (
                EvidenceType.LOG,
                self.loki.search_connection_timeout_logs,
            ),
            "search_payment_latency_logs": (
                EvidenceType.LOG,
                self.loki.search_payment_latency_logs,
            ),
            "search_recent_traces": (
                EvidenceType.TRACE,
                lambda: self.tempo.search_recent_traces(service),
            ),
            "get_trace": (
                EvidenceType.TRACE,
                lambda: self.tempo.get_trace(str(arguments.get("trace_id", ""))),
            ),
            "get_recent_deployments": (
                EvidenceType.DEPLOYMENT,
                lambda: self.deployments.get_recent_deployments(service),
            ),
        }
        evidence_type, handler = handlers[name]
        try:
            async with asyncio.timeout(self.timeout):
                result = await handler()
        except (TimeoutError, ToolDependencyError) as exc:
            return self._evidence(
                EvidenceType.TOOL_UNAVAILABLE,
                name,
                service,
                f"{name} is unavailable; no evidence was fabricated",
                {"available": False, "error": type(exc).__name__},
            )
        details = self._annotate_current_evidence(name, self._serialize(result))
        return self._evidence(
            evidence_type,
            name,
            service,
            f"Collected current {evidence_type.value.lower()} evidence from {name}",
            details,
        )

    @staticmethod
    def _annotate_current_evidence(name: str, details: dict[str, Any]) -> dict[str, Any]:
        """Add deterministic interpretations without replacing the raw tool result."""
        derived: dict[str, Any] = {}
        if name in {"get_db_pool_state", "get_payment_latency"}:
            values = [
                float(sample["value"])
                for sample in details.get("samples", [])
                if isinstance(sample, dict) and isinstance(sample.get("value"), int | float)
            ]
            if values and name == "get_db_pool_state":
                exhausted = any(value <= 0 for value in values)
                derived = {
                    "db_pool_state": "EXHAUSTED" if exhausted else "HEALTHY",
                    "supports_db_pool_exhaustion": exhausted,
                    "observed_available_connections": values,
                }
            elif values:
                threshold_seconds = 0.5
                degraded = any(value > threshold_seconds for value in values)
                derived = {
                    "payment_latency_state": "DEGRADED" if degraded else "HEALTHY",
                    "supports_payment_latency": degraded,
                    "observed_p95_seconds": values,
                    "degraded_threshold_seconds": threshold_seconds,
                }
        elif name in {"search_connection_timeout_logs", "search_payment_latency_logs"}:
            records = details.get("records", [])
            if isinstance(records, list):
                derived = {
                    "matching_log_records": len(records),
                    "supports_current_log_pattern": bool(records),
                }
        elif name == "get_recent_deployments":
            items = details.get("items", [])
            if isinstance(items, list):
                derived = {
                    "recent_deployment_count": len(items),
                    "recent_deployment_present": bool(items),
                }
        return {**details, "derived_facts": derived} if derived else details

    @staticmethod
    def _evidence(
        evidence_type: EvidenceType,
        source: str,
        service: ServiceName,
        summary: str,
        details: dict[str, Any],
    ) -> InvestigationEvidence:
        return InvestigationEvidence(
            type=evidence_type,
            source=source,
            service=service.value,
            summary=summary,
            details=details,
        )

    @staticmethod
    def _service(value: object) -> ServiceName:
        return ServiceName(str(value).removeprefix("demo-"))

    @staticmethod
    def _serialize(value: Any) -> dict[str, Any]:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return {"items": [ToolRegistry._serialize_item(item) for item in value]}
        if isinstance(value, dict):
            return value
        return {"value": str(value)}

    @staticmethod
    def _serialize_item(value: Any) -> Any:
        return value.model_dump(mode="json") if isinstance(value, BaseModel) else value
