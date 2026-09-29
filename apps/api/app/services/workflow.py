import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime

from app.actions.gateway import EXECUTABLE_DEMO_ACTIONS, ControlledDemoActionGateway
from app.agent.policies import ALLOWED_ACTIONS
from app.core.errors import ApplicationError
from app.memory.coordinator import VerifiedMemoryRetentionCoordinator
from app.memory.schemas import VerifiedIncidentMemory
from app.models.incident import Incident, IncidentStatus, Postmortem
from app.repositories.incidents import IncidentRepository
from app.schemas.workflow import RecoveryResult
from app.services.transitions import IncidentTransitionService
from app.tools.prometheus import PrometheusTool
from app.tools.schemas import ServiceName, ToolDependencyError

RECOVERY_MAX_ERROR_RATE = 0.05
RECOVERY_MAX_P95_LATENCY_SECONDS = 0.5


class IncidentWorkflowService:
    def __init__(
        self,
        repository: IncidentRepository,
        *,
        gateway_base_url: str,
        timeout: float,
        prometheus: PrometheusTool | None = None,
        recovery_wait: float = 2.0,
    ):
        self.repository = repository
        self.transitions = IncidentTransitionService()
        self.prometheus = prometheus
        self.recovery_wait = recovery_wait
        self.actions = ControlledDemoActionGateway(gateway_base_url, timeout)

    async def close(self) -> None:
        await self.actions.close()
        if self.prometheus is not None:
            await self.prometheus.close()

    def recommendations(self, incident_id: uuid.UUID):
        self._incident(incident_id)
        return self.repository.list_recommendations(incident_id)

    def decide(
        self,
        incident_id: uuid.UUID,
        recommendation_id: uuid.UUID,
        *,
        decision: str,
        approver_identifier: str,
        comment: str | None,
    ):
        incident = self._incident(incident_id)
        recommendation = self._recommendation(incident_id, recommendation_id)
        existing = self.repository.get_approval(recommendation_id)
        if existing:
            if existing.decision == decision:
                return existing
            raise ApplicationError("APPROVAL_ALREADY_DECIDED", "Approval is already final", 409)
        if incident.status != IncidentStatus.AWAITING_APPROVAL:
            raise ApplicationError(
                "INCIDENT_NOT_AWAITING_APPROVAL", "Incident is not awaiting approval", 409
            )
        approval = self.repository.add_approval(
            recommendation_id,
            decision=decision,
            approver_identifier=approver_identifier,
            comment=comment,
        )
        recommendation.status = decision
        if decision == "REJECTED":
            self.transitions.transition(incident, IncidentStatus.INVESTIGATING)
        self._event(
            incident,
            "MITIGATION_APPROVED" if decision == "APPROVED" else "MITIGATION_REJECTED",
            {"recommendation_id": str(recommendation_id), "comment": comment},
            actor="HUMAN",
        )
        self.repository.commit()
        return approval

    async def execute(self, incident_id: uuid.UUID, recommendation_id: uuid.UUID):
        incident = self._incident(incident_id)
        recommendation = self._recommendation(incident_id, recommendation_id)
        existing = self.repository.get_execution(recommendation_id)
        if existing:
            return existing
        approval = self.repository.get_approval(recommendation_id)
        if approval is None or approval.decision != "APPROVED":
            raise ApplicationError("ACTION_NOT_APPROVED", "Human approval is required", 409)
        if recommendation.action_type not in ALLOWED_ACTIONS:
            raise ApplicationError("ACTION_NOT_ALLOWED", "Action is not allowlisted", 422)
        if recommendation.action_type not in EXECUTABLE_DEMO_ACTIONS:
            raise ApplicationError(
                "ACTION_NOT_EXECUTABLE", "Recommendation is not a demo mutation", 409
            )
        if incident.status != IncidentStatus.AWAITING_APPROVAL:
            raise ApplicationError(
                "INCIDENT_NOT_READY_FOR_ACTION", "Incident cannot execute action", 409
            )
        self.transitions.transition(incident, IncidentStatus.MITIGATING)
        try:
            result = await self.actions.execute(recommendation.action_type)
        except ApplicationError as exc:
            self.transitions.transition(incident, IncidentStatus.INVESTIGATING)
            self._event(incident, "MITIGATION_FAILED", {"error": type(exc).__name__})
            self.repository.commit()
            raise ApplicationError(
                "ACTION_EXECUTION_FAILED", "Approved action failed", 502
            ) from exc
        execution = self.repository.add_execution(
            recommendation_id, status="SUCCEEDED", result=result
        )
        recommendation.status = "EXECUTED"
        incident.mitigated_at = datetime.now(UTC)
        self.transitions.transition(incident, IncidentStatus.VERIFYING_RECOVERY)
        self._event(incident, "MITIGATION_EXECUTED", {"result": result})
        self.repository.commit()
        return execution

    async def verify_recovery(self, incident_id: uuid.UUID) -> RecoveryResult:
        incident = self._incident(incident_id)
        if incident.status != IncidentStatus.VERIFYING_RECOVERY:
            raise ApplicationError(
                "INCIDENT_NOT_VERIFYING", "Incident is not verifying recovery", 409
            )
        if self.prometheus is None:
            raise ApplicationError(
                "RECOVERY_TOOL_UNAVAILABLE", "Recovery telemetry is unavailable", 503
            )
        try:
            await asyncio.sleep(self.recovery_wait)
            service = ServiceName(incident.service.removeprefix("demo-"))
            error_rate, latency, health, alerts = await asyncio.gather(
                self.prometheus.get_error_rate(service),
                self.prometheus.get_latency(service),
                self.prometheus.get_service_health(service),
                self.prometheus.get_active_alerts(service),
            )
            pool = (
                await self.prometheus.get_db_pool_state(ServiceName.CHECKOUT)
                if service == ServiceName.CHECKOUT
                else None
            )
        except (ToolDependencyError, ValueError) as exc:
            raise ApplicationError(
                "RECOVERY_TOOL_UNAVAILABLE", "Recovery telemetry is unavailable", 503
            ) from exc
        error_ok = bool(error_rate.samples) and all(
            sample.value <= RECOVERY_MAX_ERROR_RATE for sample in error_rate.samples
        )
        latency_ok = bool(latency.samples) and all(
            sample.value <= RECOVERY_MAX_P95_LATENCY_SECONDS for sample in latency.samples
        )
        health_ok = bool(health.samples) and all(sample.value == 1 for sample in health.samples)
        pool_ok = pool is None or (
            bool(pool.samples) and all(sample.value > 0 for sample in pool.samples)
        )
        alerts_clear = not alerts.samples
        recovered = error_ok and latency_ok and health_ok and pool_ok and alerts_clear
        content = {
            "checks": {
                "error_rate_improved": error_ok,
                "latency_improved": latency_ok,
                "service_healthy": health_ok,
                "db_pool_recovered": pool_ok,
                "alerts_clear": alerts_clear,
            },
            "error_rate": error_rate.model_dump(mode="json"),
            "latency": latency.model_dump(mode="json"),
            "health": health.model_dump(mode="json"),
            "alerts": alerts.model_dump(mode="json"),
            "pool": pool.model_dump(mode="json") if pool else None,
        }
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        self.repository.add_evidence(
            incident.id,
            evidence_type="RECOVERY",
            source="prometheus_error_rate",
            query=error_rate.query_name,
            observed_at=datetime.now(UTC),
            content={"recovered": recovered, **content},
            content_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        )
        if recovered:
            self.transitions.transition(incident, IncidentStatus.RESOLVED)
            incident.resolved_at = datetime.now(UTC)
            self._event(incident, "RECOVERY_VERIFIED", content)
        else:
            self._event(
                incident,
                "RECOVERY_NOT_VERIFIED",
                {**content, "next_step": "Escalate or return to investigation"},
            )
        self.repository.commit()
        return RecoveryResult(
            recovered=recovered,
            status=incident.status.value,
            evidence={"source": "prometheus_error_rate", **content},
        )

    def confirm_root_cause(
        self,
        incident_id: uuid.UUID,
        *,
        root_cause: str,
        approver_identifier: str,
        comment: str | None,
    ):
        incident = self._incident(incident_id)
        if incident.status != IncidentStatus.RESOLVED:
            raise ApplicationError(
                "INCIDENT_NOT_RESOLVED", "Resolve incident before confirmation", 409
            )
        existing = self.repository.get_root_cause_verification(incident_id)
        if existing:
            return existing
        incident.confirmed_root_cause = root_cause
        verification = self.repository.add_root_cause_verification(
            incident_id,
            root_cause=root_cause,
            approver_identifier=approver_identifier,
            comment=comment,
        )
        self._event(incident, "ROOT_CAUSE_CONFIRMED", {"comment": comment}, actor="HUMAN")
        self.repository.commit()
        return verification

    def generate_postmortem(self, incident_id: uuid.UUID) -> Postmortem:
        incident = self._incident(incident_id)
        existing = self.repository.get_postmortem(incident_id)
        if existing:
            return existing
        if not incident.confirmed_root_cause or incident.status != IncidentStatus.RESOLVED:
            raise ApplicationError(
                "ROOT_CAUSE_NOT_CONFIRMED", "Confirmed root cause is required", 409
            )
        events = self.repository.list_events(incident_id)
        recommendations = self.repository.list_recommendations(incident_id)
        mitigation = (
            recommendations[-1].description if recommendations else "No mitigation recorded"
        )
        timeline = "\n".join(
            f"- {event.occurred_at.isoformat()}: {event.event_type}" for event in events
        )
        draft = (
            f"# Postmortem: {incident.title}\n\n"
            f"## Incident Summary\n{incident.summary or incident.title}\n\n"
            "## Impact\nImpact is limited to evidence recorded in this incident.\n\n"
            f"## Timeline\n{timeline}\n\n"
            f"## Symptoms\n{incident.title}\n\n"
            "## Detection\nDetected through Prometheus and Alertmanager.\n\n"
            "## Investigation\nSee the persisted evidence and hypothesis records.\n\n"
            "## Hypotheses Considered\nSee the incident hypothesis ledger.\n\n"
            f"## Confirmed Root Cause\n{incident.confirmed_root_cause}\n\n"
            "## Contributing Factors\nTo be completed during human review.\n\n"
            f"## Mitigation\n{mitigation}\n\n"
            "## Recovery Verification\nSee persisted RECOVERY evidence.\n\n"
            "## False Leads\nSee contradicted and rejected hypotheses.\n\n"
            "## What Went Well\nEvidence and approvals were persisted.\n\n"
            "## What Went Poorly\nTo be completed during human review.\n\n"
            "## Follow-Up Actions\n- Add a regression alert and review capacity assumptions.\n\n"
            "## Runbook Improvements\nRecord gaps found during this investigation.\n\n"
            "## Historical Memory Context\nHistorical memory was supporting evidence, not proof.\n"
        )
        postmortem = self.repository.add_postmortem(incident_id, draft)
        self.transitions.transition(incident, IncidentStatus.POSTMORTEM_REVIEW)
        self._event(incident, "POSTMORTEM_DRAFTED", {})
        self.repository.commit()
        return postmortem

    def approve_postmortem(self, incident_id: uuid.UUID, *, approver_identifier: str) -> Postmortem:
        incident = self._incident(incident_id)
        postmortem = self.repository.get_postmortem(incident_id)
        if postmortem is None:
            raise ApplicationError("POSTMORTEM_NOT_FOUND", "Generate postmortem first", 404)
        if postmortem.approved_at:
            return postmortem
        postmortem.final_markdown = postmortem.draft_markdown
        postmortem.approved_by = approver_identifier
        postmortem.approved_at = datetime.now(UTC)
        self._event(incident, "POSTMORTEM_APPROVED", {}, actor="HUMAN")
        self.repository.commit()
        return postmortem

    async def commit_memory(
        self,
        incident_id: uuid.UUID,
        coordinator: VerifiedMemoryRetentionCoordinator,
    ):
        incident = self._incident(incident_id)
        postmortem = self.repository.get_postmortem(incident_id)
        verification = self.repository.get_root_cause_verification(incident_id)
        if incident.status == IncidentStatus.MEMORY_COMMITTED:
            document_id = f"incident:{incident.id}"
            from app.memory.schemas import RetentionResult

            return RetentionResult(
                bank_id=coordinator.memory.settings.HINDSIGHT_BANK_ID,
                document_id=document_id,
                retained=True,
            )
        if (
            incident.status != IncidentStatus.POSTMORTEM_REVIEW
            or postmortem is None
            or postmortem.approved_at is None
            or verification is None
            or not incident.confirmed_root_cause
        ):
            raise ApplicationError(
                "MEMORY_NOT_VERIFIED",
                "Resolved incident, confirmed root cause, and approved postmortem are required",
                409,
            )
        evidence = self.repository.list_evidence(incident_id)
        hypotheses = self.repository.list_hypotheses(incident_id)
        recommendations = self.repository.list_recommendations(incident_id)
        payload = VerifiedIncidentMemory(
            incident_id=str(incident.id),
            service=incident.service.removeprefix("demo-"),
            environment=incident.environment,
            symptoms=[incident.title],
            confirmed_root_cause=incident.confirmed_root_cause,
            decisive_evidence=[f"{item.type}: {item.source}" for item in evidence]
            or ["Human review"],
            successful_mitigation=(
                recommendations[-1].description if recommendations else "Human mitigation"
            ),
            recovery_verification="Prometheus recovery evidence persisted",
            failed_investigation_paths=[
                item.statement for item in hypotheses if item.status in {"CONTRADICTED", "REJECTED"}
            ],
            runbook="Checked-in service runbook",
            important_caveats=[
                "Historical memory was treated as supporting evidence only",
                "Action was a controlled demo remediation, not a production rollback",
            ],
            resolved=True,
            verified=True,
            verification_basis="approved_postmortem",
        )
        result = await coordinator.retain(incident.id, payload)
        self.transitions.transition(incident, IncidentStatus.MEMORY_COMMITTED)
        self._event(incident, "MEMORY_COMMITTED", {"document_id": result.document_id})
        self.repository.commit()
        return result

    def _incident(self, incident_id: uuid.UUID) -> Incident:
        incident = self.repository.get(incident_id)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident not found", 404)
        return incident

    def _recommendation(self, incident_id: uuid.UUID, recommendation_id: uuid.UUID):
        recommendation = self.repository.get_recommendation(recommendation_id)
        if recommendation is None or recommendation.incident_id != incident_id:
            raise ApplicationError("RECOMMENDATION_NOT_FOUND", "Recommendation not found", 404)
        return recommendation

    def _event(
        self,
        incident: Incident,
        event_type: str,
        payload: dict[str, object],
        *,
        actor: str = "SYSTEM",
    ) -> None:
        self.repository.append_event(
            incident,
            event_type=event_type,
            payload=payload,
            occurred_at=datetime.now(UTC),
            actor_type=actor,
            source="workflow",
        )
