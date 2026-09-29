import hashlib
import json
import uuid
from datetime import UTC, datetime

from app.agent.policies import ALLOWED_ACTIONS
from app.agent.schemas import (
    Diagnosis,
    EvidenceType,
    InvestigationEvidence,
    InvestigationResult,
    ToolCallRecord,
    ToolRequest,
)
from app.agent.tool_registry import ToolRegistry
from app.core.errors import ApplicationError
from app.llm.base import InvestigatorProvider, ProviderError
from app.models.incident import Incident, IncidentStatus
from app.repositories.incidents import IncidentRepository
from app.services.transitions import IncidentTransitionService


class Investigator:
    def __init__(
        self,
        repository: IncidentRepository,
        provider: InvestigatorProvider,
        tools: ToolRegistry,
        *,
        max_iterations: int,
    ):
        self.repository = repository
        self.provider = provider
        self.tools = tools
        self.max_iterations = max_iterations
        self.transitions = IncidentTransitionService()

    async def investigate(self, incident_id: uuid.UUID) -> InvestigationResult:
        incident = self.repository.get(incident_id)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident not found", 404)
        if incident.status not in {
            IncidentStatus.DETECTED,
            IncidentStatus.TRIAGED,
            IncidentStatus.INVESTIGATING,
        }:
            raise ApplicationError(
                "INCIDENT_NOT_INVESTIGABLE",
                f"Incident status {incident.status.value} cannot start investigation",
                409,
            )
        self.transitions.transition(incident, IncidentStatus.INVESTIGATING)
        self._event(incident, "INVESTIGATION_STARTED", {})
        self.repository.commit()
        incident_data = self._incident_data(incident)
        evidence: list[InvestigationEvidence] = []
        called_tools: list[str] = []
        tool_calls: list[ToolCallRecord] = []
        for iteration in range(1, self.max_iterations + 1):
            try:
                step = await self.provider.next_step(
                    incident=incident_data,
                    evidence=evidence,
                    called_tools=called_tools,
                    force_diagnosis=iteration == self.max_iterations,
                )
            except ProviderError as exc:
                self._event(
                    incident, "INVESTIGATION_PROVIDER_FAILED", {"error": type(exc).__name__}
                )
                self.repository.commit()
                raise ApplicationError(
                    "INVESTIGATION_PROVIDER_UNAVAILABLE",
                    "The configured investigation provider is unavailable",
                    503,
                ) from exc
            if isinstance(step, ToolRequest):
                if step.name in called_tools:
                    raise ApplicationError(
                        "AGENT_REPEATED_TOOL", "Agent repeated an evidence request", 422
                    )
                item = await self.tools.execute(
                    step.name, incident=incident_data, arguments=step.arguments
                )
                called_tools.append(step.name)
                evidence.append(item)
                tool_calls.append(
                    ToolCallRecord(
                        tool=step.name,
                        evidence_id=item.id,
                        status=(
                            "UNAVAILABLE"
                            if item.type == EvidenceType.TOOL_UNAVAILABLE
                            else "SUCCEEDED"
                        ),
                    )
                )
                self._persist_evidence(incident, item)
                self.repository.commit()
                continue
            return self._finalize(incident, step, evidence, tool_calls, iteration)
        raise ApplicationError(
            "AGENT_ITERATION_LIMIT", "Investigation reached its bounded iteration limit", 422
        )

    def _finalize(
        self,
        incident: Incident,
        diagnosis: Diagnosis,
        evidence: list[InvestigationEvidence],
        tool_calls: list[ToolCallRecord],
        iteration: int,
    ) -> InvestigationResult:
        if diagnosis.recommended_action.value not in ALLOWED_ACTIONS:
            raise ApplicationError("ACTION_NOT_ALLOWED", "Proposed action is not allowed", 422)
        self.repository.add_hypothesis(
            incident.id,
            statement=diagnosis.primary_hypothesis.statement,
            status=diagnosis.primary_hypothesis.status.value,
            confidence=diagnosis.primary_hypothesis.confidence.value,
        )
        self.transitions.transition(incident, IncidentStatus.DIAGNOSIS_PROPOSED)
        self.transitions.transition(incident, IncidentStatus.MITIGATION_PROPOSED)
        recommendation = self.repository.add_recommendation(
            incident.id,
            action_type=diagnosis.recommended_action.value,
            description=diagnosis.recommended_next_step,
            rationale=diagnosis.action_rationale,
            risk_level=diagnosis.risk_level,
        )
        self.transitions.transition(incident, IncidentStatus.AWAITING_APPROVAL)
        self._event(
            incident,
            "DIAGNOSIS_PROPOSED",
            {
                "diagnosis": diagnosis.model_dump(mode="json"),
                "recommendation_id": str(recommendation.id),
            },
        )
        self.repository.commit()
        return InvestigationResult(
            incident_id=str(incident.id),
            status=incident.status.value,
            proposed_diagnosis=diagnosis,
            hypotheses=[diagnosis.primary_hypothesis],
            evidence=evidence,
            historical_memories=[
                item for item in evidence if item.type == EvidenceType.HISTORICAL_MEMORY
            ],
            recommended_action=diagnosis.recommended_action,
            tool_calls=tool_calls,
            iterations=iteration,
        )

    def _persist_evidence(self, incident: Incident, item: InvestigationEvidence) -> None:
        canonical = json.dumps(item.details, sort_keys=True, separators=(",", ":"))
        self.repository.add_evidence(
            incident.id,
            evidence_type=item.type.value,
            source=item.source,
            query=item.source,
            observed_at=item.observed_at,
            content={
                "evidence_id": str(item.id),
                "service": item.service,
                "summary": item.summary,
                "details": item.details,
            },
            content_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        )

    def _event(self, incident: Incident, event_type: str, payload: dict[str, object]) -> None:
        self.repository.append_event(
            incident,
            event_type=event_type,
            payload=payload,
            occurred_at=datetime.now(UTC),
            actor_type="AGENT",
            source="investigator",
        )

    @staticmethod
    def _incident_data(incident: Incident) -> dict[str, object]:
        return {
            "id": str(incident.id),
            "title": incident.title,
            "service": incident.service,
            "environment": incident.environment,
            "severity": incident.severity,
            "status": incident.status.value,
            "started_at": incident.started_at.isoformat(),
        }
