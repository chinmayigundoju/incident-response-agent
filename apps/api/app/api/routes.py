import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.agent.investigator import Investigator
from app.agent.schemas import InvestigationResult
from app.api.dependencies import (
    get_automation_dispatcher,
    get_incident_service,
    get_investigator,
    get_memory_service,
    get_scenario_service,
    get_workflow_service,
)
from app.db.session import get_session
from app.memory.coordinator import VerifiedMemoryRetentionCoordinator
from app.memory.schemas import MemoryHealth
from app.memory.service import HindsightMemoryService
from app.repositories.memory_sync import MemorySyncRepository
from app.schemas.alertmanager import AlertmanagerWebhook, WebhookResult
from app.schemas.common import HealthResponse
from app.schemas.incidents import EvidenceRead, HypothesisRead, IncidentEventRead, IncidentRead
from app.schemas.workflow import (
    ActionExecutionRead,
    ApprovalRead,
    DecisionRequest,
    PostmortemRead,
    RecommendationRead,
    RecoveryResult,
    RootCauseRequest,
    RootCauseVerificationRead,
)
from app.services.automation import AutomationStatus, IncidentAutomationDispatcher
from app.services.incidents import IncidentService
from app.services.scenarios import ScenarioName, ScenarioResult, ScenarioService
from app.services.workflow import IncidentWorkflowService

health_router = APIRouter()
api_router = APIRouter(prefix="/api/v1")
webhook_router = APIRouter(prefix="/webhooks")


@health_router.get("/health", response_model=HealthResponse)
@api_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@api_router.get("/automation/status", response_model=AutomationStatus)
def automation_status(
    automation: Annotated[IncidentAutomationDispatcher, Depends(get_automation_dispatcher)],
) -> AutomationStatus:
    return automation.status()


@api_router.get("/incidents", response_model=list[IncidentRead])
def list_incidents(
    service: Annotated[IncidentService, Depends(get_incident_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> object:
    return service.list_incidents(limit=limit, offset=offset)


@api_router.get("/incidents/{incident_id}", response_model=IncidentRead)
def get_incident(
    incident_id: uuid.UUID,
    service: Annotated[IncidentService, Depends(get_incident_service)],
) -> object:
    return service.get_incident(incident_id)


@api_router.get("/incidents/{incident_id}/events", response_model=list[IncidentEventRead])
def get_events(
    incident_id: uuid.UUID, service: Annotated[IncidentService, Depends(get_incident_service)]
) -> object:
    return service.events(incident_id)


@api_router.get("/incidents/{incident_id}/evidence", response_model=list[EvidenceRead])
def get_evidence(
    incident_id: uuid.UUID, service: Annotated[IncidentService, Depends(get_incident_service)]
) -> object:
    return service.evidence(incident_id)


@api_router.get("/incidents/{incident_id}/hypotheses", response_model=list[HypothesisRead])
def get_hypotheses(
    incident_id: uuid.UUID, service: Annotated[IncidentService, Depends(get_incident_service)]
) -> object:
    return service.hypotheses(incident_id)


@api_router.post("/incidents/{incident_id}/investigate", response_model=InvestigationResult)
async def investigate(
    incident_id: uuid.UUID,
    investigator: Annotated[Investigator, Depends(get_investigator)],
) -> InvestigationResult:
    return await investigator.investigate(incident_id)


@api_router.get("/incidents/{incident_id}/recommendations", response_model=list[RecommendationRead])
def get_recommendations(
    incident_id: uuid.UUID,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
) -> object:
    return workflow.recommendations(incident_id)


@api_router.post(
    "/incidents/{incident_id}/recommendations/{recommendation_id}/approve",
    response_model=ApprovalRead,
)
def approve_recommendation(
    incident_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    request: DecisionRequest,
    background_tasks: BackgroundTasks,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
    automation: Annotated[IncidentAutomationDispatcher, Depends(get_automation_dispatcher)],
) -> object:
    approval = workflow.decide(
        incident_id,
        recommendation_id,
        decision="APPROVED",
        approver_identifier=request.approver_identifier,
        comment=request.comment,
    )
    automation.approved(background_tasks, incident_id, recommendation_id)
    return approval


@api_router.post(
    "/incidents/{incident_id}/recommendations/{recommendation_id}/reject",
    response_model=ApprovalRead,
)
def reject_recommendation(
    incident_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    request: DecisionRequest,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
) -> object:
    return workflow.decide(
        incident_id,
        recommendation_id,
        decision="REJECTED",
        approver_identifier=request.approver_identifier,
        comment=request.comment,
    )


@api_router.post(
    "/incidents/{incident_id}/recommendations/{recommendation_id}/execute",
    response_model=ActionExecutionRead,
)
async def execute_recommendation(
    incident_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
) -> object:
    return await workflow.execute(incident_id, recommendation_id)


@api_router.post("/recommendations/{recommendation_id}/approve", response_model=ApprovalRead)
def approve_recommendation_by_id(
    recommendation_id: uuid.UUID,
    request: DecisionRequest,
    background_tasks: BackgroundTasks,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
    automation: Annotated[IncidentAutomationDispatcher, Depends(get_automation_dispatcher)],
) -> object:
    recommendation = workflow.repository.get_recommendation(recommendation_id)
    if recommendation is None:
        from app.core.errors import ApplicationError

        raise ApplicationError("RECOMMENDATION_NOT_FOUND", "Recommendation not found", 404)
    approval = workflow.decide(
        recommendation.incident_id,
        recommendation_id,
        decision="APPROVED",
        approver_identifier=request.approver_identifier,
        comment=request.comment,
    )
    automation.approved(background_tasks, recommendation.incident_id, recommendation_id)
    return approval


@api_router.post("/recommendations/{recommendation_id}/reject", response_model=ApprovalRead)
def reject_recommendation_by_id(
    recommendation_id: uuid.UUID,
    request: DecisionRequest,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
) -> object:
    recommendation = workflow.repository.get_recommendation(recommendation_id)
    if recommendation is None:
        from app.core.errors import ApplicationError

        raise ApplicationError("RECOMMENDATION_NOT_FOUND", "Recommendation not found", 404)
    return workflow.decide(
        recommendation.incident_id,
        recommendation_id,
        decision="REJECTED",
        approver_identifier=request.approver_identifier,
        comment=request.comment,
    )


@api_router.post("/recommendations/{recommendation_id}/execute", response_model=ActionExecutionRead)
async def execute_recommendation_by_id(
    recommendation_id: uuid.UUID,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
) -> object:
    recommendation = workflow.repository.get_recommendation(recommendation_id)
    if recommendation is None:
        from app.core.errors import ApplicationError

        raise ApplicationError("RECOMMENDATION_NOT_FOUND", "Recommendation not found", 404)
    return await workflow.execute(recommendation.incident_id, recommendation_id)


@api_router.post("/incidents/{incident_id}/verify-recovery", response_model=RecoveryResult)
async def verify_recovery(
    incident_id: uuid.UUID,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
) -> RecoveryResult:
    return await workflow.verify_recovery(incident_id)


@api_router.post(
    "/incidents/{incident_id}/root-cause/confirm", response_model=RootCauseVerificationRead
)
def confirm_root_cause(
    incident_id: uuid.UUID,
    request: RootCauseRequest,
    background_tasks: BackgroundTasks,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
    automation: Annotated[IncidentAutomationDispatcher, Depends(get_automation_dispatcher)],
) -> object:
    verification = workflow.confirm_root_cause(
        incident_id,
        root_cause=request.confirmed_root_cause,
        approver_identifier=request.approver_identifier,
        comment=request.verification_comment,
    )
    automation.root_cause_confirmed(background_tasks, incident_id)
    return verification


@api_router.post("/incidents/{incident_id}/postmortem", response_model=PostmortemRead)
def generate_postmortem(
    incident_id: uuid.UUID,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
) -> object:
    return workflow.generate_postmortem(incident_id)


@api_router.get("/incidents/{incident_id}/postmortem", response_model=PostmortemRead)
def get_postmortem(
    incident_id: uuid.UUID,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
) -> object:
    postmortem = workflow.repository.get_postmortem(incident_id)
    if postmortem is None:
        from app.core.errors import ApplicationError

        raise ApplicationError("POSTMORTEM_NOT_FOUND", "Postmortem not found", 404)
    return postmortem


@api_router.post("/incidents/{incident_id}/postmortem/approve", response_model=PostmortemRead)
def approve_postmortem(
    incident_id: uuid.UUID,
    request: DecisionRequest,
    background_tasks: BackgroundTasks,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
    automation: Annotated[IncidentAutomationDispatcher, Depends(get_automation_dispatcher)],
) -> object:
    postmortem = workflow.approve_postmortem(
        incident_id, approver_identifier=request.approver_identifier
    )
    automation.postmortem_approved(background_tasks, incident_id)
    return postmortem


@api_router.post("/incidents/{incident_id}/memory/commit")
async def commit_incident_memory(
    incident_id: uuid.UUID,
    workflow: Annotated[IncidentWorkflowService, Depends(get_workflow_service)],
    memory: Annotated[HindsightMemoryService, Depends(get_memory_service)],
    session: Annotated[Session, Depends(get_session)],
) -> object:
    coordinator = VerifiedMemoryRetentionCoordinator(memory, MemorySyncRepository(session))
    return await workflow.commit_memory(incident_id, coordinator)


@api_router.get("/demo/scenarios", response_model=list[ScenarioName])
def list_scenarios() -> list[ScenarioName]:
    return list(ScenarioName)


@api_router.post("/demo/scenarios/{scenario}/activate", response_model=ScenarioResult)
async def activate_scenario(
    scenario: ScenarioName,
    service: Annotated[ScenarioService, Depends(get_scenario_service)],
) -> ScenarioResult:
    return await service.activate(scenario)


@api_router.post("/demo/reset", response_model=ScenarioResult)
async def reset_demo(
    service: Annotated[ScenarioService, Depends(get_scenario_service)],
) -> ScenarioResult:
    return await service.reset()


@api_router.get("/memory/health", response_model=MemoryHealth)
async def memory_health(
    service: Annotated[HindsightMemoryService, Depends(get_memory_service)],
) -> MemoryHealth:
    return await service.health_check()


@webhook_router.post("/alertmanager", response_model=WebhookResult)
def alertmanager_webhook(
    payload: AlertmanagerWebhook,
    background_tasks: BackgroundTasks,
    service: Annotated[IncidentService, Depends(get_incident_service)],
    automation: Annotated[IncidentAutomationDispatcher, Depends(get_automation_dispatcher)],
) -> WebhookResult:
    incidents = service.ingest_alertmanager(payload)
    automation.new_incidents(background_tasks, [item.id for item in incidents])
    return WebhookResult(
        accepted=len(payload.alerts), incident_ids=[str(item.id) for item in incidents]
    )
