import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from app.actions.gateway import EXECUTABLE_DEMO_ACTIONS
from app.core.config import IncidentAutomationMode, Settings
from app.db.session import get_engine
from app.memory.coordinator import VerifiedMemoryRetentionCoordinator
from app.memory.service import HindsightMemoryService
from app.models.incident import IncidentStatus
from app.repositories.incidents import IncidentRepository
from app.repositories.memory_sync import MemorySyncRepository
from app.services.runtime import investigator_runtime, workflow_runtime
from app.services.transitions import IncidentTransitionService
from app.services.workflow import IncidentWorkflowService

logger = logging.getLogger(__name__)


class AutomationStatus(BaseModel):
    mode: IncidentAutomationMode
    label: str
    automatic_investigation: bool
    automatic_execution_after_approval: bool
    automatic_postmortem_after_root_cause: bool
    automatic_memory_after_postmortem_approval: bool
    simulated_autopilot: bool


class IncidentAutomationService:
    """Advances only lifecycle stages already authorized by deterministic policy."""

    def __init__(
        self,
        repository: IncidentRepository,
        settings: Settings,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.transitions = IncidentTransitionService()
        self.sleep = sleep

    def claim_investigation(self, incident_id: uuid.UUID) -> bool:
        incident = self.repository.get_for_update(incident_id)
        if incident is None or incident.status != IncidentStatus.DETECTED:
            self.repository.rollback()
            return False
        self.transitions.transition(incident, IncidentStatus.TRIAGED)
        self._event(
            incident,
            "AUTOMATION_STARTED",
            {"mode": self.settings.INCIDENT_AUTOMATION_MODE},
        )
        self._event(incident, "AUTO_INVESTIGATION_STARTED", {})
        self.repository.commit()
        return True

    def investigation_completed(self, incident_id: uuid.UUID, *, iterations: int) -> None:
        incident = self.repository.get(incident_id)
        if incident is None:
            return
        self._event(incident, "AUTO_INVESTIGATION_COMPLETED", {"iterations": iterations})
        self._event(incident, "AUTOMATION_WAITING_FOR_APPROVAL", {})
        self.repository.commit()

    async def continue_after_approval(
        self,
        incident_id: uuid.UUID,
        recommendation_id: uuid.UUID,
        workflow: IncidentWorkflowService,
    ) -> None:
        incident = self.repository.get_for_update(incident_id)
        if incident is None or incident.status != IncidentStatus.AWAITING_APPROVAL:
            self.repository.rollback()
            return
        self._event(
            incident,
            "AUTO_MITIGATION_STARTED",
            {"recommendation_id": str(recommendation_id)},
        )
        await workflow.execute(incident_id, recommendation_id)
        incident = self.repository.get(incident_id)
        if incident is None or incident.status != IncidentStatus.VERIFYING_RECOVERY:
            return
        self._event(incident, "AUTO_RECOVERY_VERIFICATION_STARTED", {})
        self.repository.commit()
        for attempt in range(1, self.settings.AUTOMATION_RECOVERY_MAX_ATTEMPTS + 1):
            result = await workflow.verify_recovery(incident_id)
            if result.recovered:
                incident = self.repository.get(incident_id)
                if incident is not None:
                    self._event(
                        incident,
                        "AUTO_RECOVERY_VERIFIED",
                        {"attempt": attempt},
                    )
                    self.repository.commit()
                return
            if attempt < self.settings.AUTOMATION_RECOVERY_MAX_ATTEMPTS:
                await self.sleep(self.settings.AUTOMATION_RECOVERY_RETRY_SECONDS)
        self.record_failure(incident_id, "recovery", "RecoveryNotVerified")

    async def continue_demo_autopilot(
        self,
        incident_id: uuid.UUID,
        workflow: IncidentWorkflowService,
    ) -> None:
        if not self.settings.demo_autopilot_allowed:
            return
        incident = self.repository.get(incident_id)
        if incident is None or incident.status != IncidentStatus.AWAITING_APPROVAL:
            return
        recommendations = self.repository.list_recommendations(incident_id)
        if not recommendations:
            self.record_failure(incident_id, "demo_autopilot", "RecommendationMissing")
            return
        recommendation = recommendations[-1]
        if recommendation.action_type not in EXECUTABLE_DEMO_ACTIONS:
            self.record_failure(incident_id, "demo_autopilot", "ActionNotSimulated")
            return
        workflow.decide(
            incident_id,
            recommendation.id,
            decision="APPROVED",
            approver_identifier="demo-autopilot",
            comment="Automatic approval restricted to the controlled simulated environment",
        )
        await self.continue_after_approval(incident_id, recommendation.id, workflow)

    def continue_after_root_cause(
        self, incident_id: uuid.UUID, workflow: IncidentWorkflowService
    ) -> None:
        incident = self.repository.get(incident_id)
        if (
            incident is None
            or incident.status != IncidentStatus.RESOLVED
            or not incident.confirmed_root_cause
        ):
            return
        if self.repository.get_postmortem(incident_id) is not None:
            return
        workflow.generate_postmortem(incident_id)
        incident = self.repository.get(incident_id)
        if incident is not None:
            self._event(incident, "AUTO_POSTMORTEM_GENERATED", {})
            self.repository.commit()

    async def continue_after_postmortem_approval(
        self,
        incident_id: uuid.UUID,
        workflow: IncidentWorkflowService,
        coordinator: VerifiedMemoryRetentionCoordinator,
    ) -> None:
        incident = self.repository.get(incident_id)
        if incident is None or incident.status == IncidentStatus.MEMORY_COMMITTED:
            return
        self._event(incident, "AUTO_MEMORY_COMMIT_STARTED", {})
        self.repository.commit()
        result = await workflow.commit_memory(incident_id, coordinator)
        incident = self.repository.get(incident_id)
        if incident is not None:
            self._event(
                incident,
                "AUTO_MEMORY_COMMITTED",
                {"document_id": result.document_id},
            )
            self.repository.commit()

    def record_failure(self, incident_id: uuid.UUID, stage: str, error: str) -> None:
        incident = self.repository.get(incident_id)
        if incident is None:
            return
        self._event(
            incident,
            "AUTOMATION_FAILED",
            {"stage": stage, "error": error},
        )
        self.repository.commit()

    def _event(self, incident, event_type: str, payload: dict[str, object]) -> None:
        self.repository.append_event(
            incident,
            event_type=event_type,
            payload=payload,
            occurred_at=datetime.now(UTC),
            actor_type="SYSTEM",
            source="automation",
        )


class IncidentAutomationWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions = sessionmaker(bind=get_engine(), expire_on_commit=False)

    async def investigate(self, incident_id: uuid.UUID) -> None:
        with self._sessions() as session:
            repository = IncidentRepository(session)
            automation = IncidentAutomationService(repository, self.settings)
            try:
                if not automation.claim_investigation(incident_id):
                    return
                async with investigator_runtime(session, self.settings) as investigator:
                    result = await investigator.investigate(incident_id)
                automation.investigation_completed(incident_id, iterations=result.iterations)
                if self.settings.demo_autopilot_allowed:
                    async with workflow_runtime(session, self.settings) as workflow:
                        await automation.continue_demo_autopilot(incident_id, workflow)
            except Exception as exc:
                session.rollback()
                automation.record_failure(incident_id, "investigation", type(exc).__name__)
                logger.warning(
                    "Automatic investigation stopped: incident_id=%s error=%s",
                    incident_id,
                    type(exc).__name__,
                )

    async def after_approval(self, incident_id: uuid.UUID, recommendation_id: uuid.UUID) -> None:
        with self._sessions() as session:
            automation = IncidentAutomationService(IncidentRepository(session), self.settings)
            try:
                async with workflow_runtime(session, self.settings) as workflow:
                    await automation.continue_after_approval(
                        incident_id, recommendation_id, workflow
                    )
            except Exception as exc:
                session.rollback()
                automation.record_failure(incident_id, "mitigation", type(exc).__name__)
                logger.warning(
                    "Automatic mitigation stopped: incident_id=%s error=%s",
                    incident_id,
                    type(exc).__name__,
                )

    async def after_root_cause(self, incident_id: uuid.UUID) -> None:
        with self._sessions() as session:
            automation = IncidentAutomationService(IncidentRepository(session), self.settings)
            try:
                async with workflow_runtime(session, self.settings) as workflow:
                    automation.continue_after_root_cause(incident_id, workflow)
            except Exception as exc:
                session.rollback()
                automation.record_failure(incident_id, "postmortem", type(exc).__name__)
                logger.warning(
                    "Automatic postmortem stopped: incident_id=%s error=%s",
                    incident_id,
                    type(exc).__name__,
                )

    async def after_postmortem_approval(self, incident_id: uuid.UUID) -> None:
        with self._sessions() as session:
            repository = IncidentRepository(session)
            automation = IncidentAutomationService(repository, self.settings)
            memory = HindsightMemoryService(self.settings)
            try:
                coordinator = VerifiedMemoryRetentionCoordinator(
                    memory, MemorySyncRepository(session)
                )
                async with workflow_runtime(session, self.settings) as workflow:
                    await automation.continue_after_postmortem_approval(
                        incident_id, workflow, coordinator
                    )
            except Exception as exc:
                session.rollback()
                automation.record_failure(incident_id, "memory_commit", type(exc).__name__)
                logger.warning(
                    "Automatic memory commit stopped: incident_id=%s error=%s",
                    incident_id,
                    type(exc).__name__,
                )
            finally:
                await memory.close()


class IncidentAutomationDispatcher:
    def __init__(self, settings: Settings, worker: IncidentAutomationWorker | None = None) -> None:
        self.settings = settings
        self.worker = worker or IncidentAutomationWorker(settings)

    @property
    def enabled(self) -> bool:
        return self.settings.INCIDENT_AUTOMATION_MODE != IncidentAutomationMode.MANUAL

    def status(self) -> AutomationStatus:
        mode = self.settings.INCIDENT_AUTOMATION_MODE
        return AutomationStatus(
            mode=mode,
            label=mode.value.replace("_", " ").title(),
            automatic_investigation=mode != IncidentAutomationMode.MANUAL,
            automatic_execution_after_approval=mode != IncidentAutomationMode.MANUAL,
            automatic_postmortem_after_root_cause=mode != IncidentAutomationMode.MANUAL,
            automatic_memory_after_postmortem_approval=mode != IncidentAutomationMode.MANUAL,
            simulated_autopilot=mode == IncidentAutomationMode.DEMO_AUTOPILOT,
        )

    def new_incidents(
        self, background_tasks: BackgroundTasks, incident_ids: list[uuid.UUID]
    ) -> None:
        if not self.enabled:
            return
        for incident_id in dict.fromkeys(incident_ids):
            background_tasks.add_task(self.worker.investigate, incident_id)

    def approved(
        self,
        background_tasks: BackgroundTasks,
        incident_id: uuid.UUID,
        recommendation_id: uuid.UUID,
    ) -> None:
        if self.enabled:
            background_tasks.add_task(self.worker.after_approval, incident_id, recommendation_id)

    def root_cause_confirmed(
        self, background_tasks: BackgroundTasks, incident_id: uuid.UUID
    ) -> None:
        if self.enabled:
            background_tasks.add_task(self.worker.after_root_cause, incident_id)

    def postmortem_approved(
        self, background_tasks: BackgroundTasks, incident_id: uuid.UUID
    ) -> None:
        if self.enabled:
            background_tasks.add_task(self.worker.after_postmortem_approval, incident_id)
