from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent.investigator import Investigator
from app.agent.tool_registry import ToolRegistry
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.llm.groq import GroqProvider
from app.memory.service import HindsightMemoryService
from app.repositories.incidents import IncidentRepository
from app.services.workflow import IncidentWorkflowService
from app.tools.deployments import DeploymentTool
from app.tools.hindsight import HindsightTool
from app.tools.incidents import IncidentContextTool
from app.tools.loki import LokiTool
from app.tools.prometheus import PrometheusTool
from app.tools.runbooks import RunbookTool
from app.tools.tempo import TempoTool


@asynccontextmanager
async def investigator_runtime(session: Session, settings: Settings) -> AsyncIterator[Investigator]:
    if not settings.GROQ_API_KEY:
        raise ApplicationError(
            "INVESTIGATION_PROVIDER_NOT_CONFIGURED",
            "GROQ_API_KEY is required for live investigation",
            503,
        )
    memory = HindsightMemoryService(settings)
    provider = GroqProvider(
        settings.GROQ_API_KEY,
        settings.GROQ_BASE_URL,
        settings.GROQ_MODEL,
        timeout=min(settings.AGENT_TOOL_TIMEOUT_SECONDS, 30),
        max_evidence_chars=settings.GROQ_MAX_EVIDENCE_CHARS,
        rate_limit_max_wait=settings.GROQ_RATE_LIMIT_MAX_WAIT_SECONDS,
    )
    tools = ToolRegistry(
        timeout=settings.AGENT_TOOL_TIMEOUT_SECONDS,
        prometheus=PrometheusTool(
            settings.PROMETHEUS_BASE_URL, settings.OBSERVABILITY_TIMEOUT_SECONDS
        ),
        loki=LokiTool(settings.LOKI_BASE_URL, settings.OBSERVABILITY_TIMEOUT_SECONDS),
        tempo=TempoTool(settings.TEMPO_BASE_URL, settings.OBSERVABILITY_TIMEOUT_SECONDS),
        deployments=DeploymentTool(
            settings.DEMO_GATEWAY_BASE_URL, settings.OBSERVABILITY_TIMEOUT_SECONDS
        ),
        runbooks=RunbookTool(Path(settings.RUNBOOK_ROOT)),
        incident_context=IncidentContextTool(IncidentRepository(session)),
        hindsight=HindsightTool(memory),
    )
    investigator = Investigator(
        IncidentRepository(session),
        provider,
        tools,
        max_iterations=settings.AGENT_MAX_ITERATIONS,
    )
    try:
        yield investigator
    finally:
        await tools.close()
        await provider.close()
        await memory.close()


@asynccontextmanager
async def workflow_runtime(
    session: Session, settings: Settings
) -> AsyncIterator[IncidentWorkflowService]:
    service = IncidentWorkflowService(
        IncidentRepository(session),
        gateway_base_url=settings.DEMO_GATEWAY_BASE_URL,
        timeout=settings.OBSERVABILITY_TIMEOUT_SECONDS,
        prometheus=PrometheusTool(
            settings.PROMETHEUS_BASE_URL, settings.OBSERVABILITY_TIMEOUT_SECONDS
        ),
        recovery_wait=settings.RECOVERY_WAIT_SECONDS,
    )
    try:
        yield service
    finally:
        await service.close()
