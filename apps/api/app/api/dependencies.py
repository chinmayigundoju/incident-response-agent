from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.agent.investigator import Investigator
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.memory.service import HindsightMemoryService
from app.repositories.incidents import IncidentRepository
from app.services.automation import IncidentAutomationDispatcher
from app.services.incidents import IncidentService
from app.services.runtime import investigator_runtime, workflow_runtime
from app.services.scenarios import ScenarioService
from app.services.workflow import IncidentWorkflowService


def get_incident_service(session: Annotated[Session, Depends(get_session)]) -> IncidentService:
    return IncidentService(IncidentRepository(session))


async def get_memory_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncGenerator[HindsightMemoryService, None]:
    service = HindsightMemoryService(settings)
    try:
        yield service
    finally:
        await service.close()


async def get_investigator(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncGenerator[Investigator, None]:
    async with investigator_runtime(session, settings) as investigator:
        yield investigator


async def get_workflow_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncGenerator[IncidentWorkflowService, None]:
    async with workflow_runtime(session, settings) as service:
        yield service


def get_automation_dispatcher(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IncidentAutomationDispatcher:
    return IncidentAutomationDispatcher(settings)


async def get_scenario_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncGenerator[ScenarioService, None]:
    service = ScenarioService(
        settings.DEMO_GATEWAY_BASE_URL, settings.OBSERVABILITY_TIMEOUT_SECONDS
    )
    try:
        yield service
    finally:
        await service.close()
