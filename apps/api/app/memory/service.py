import logging

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.memory.client import HindsightClientProtocol, build_hindsight_client
from app.memory.retention import render_verified_incident
from app.memory.retrieval import normalize_recall_response
from app.memory.schemas import (
    MemoryHealth,
    RecallResult,
    ReflectionResult,
    RetentionResult,
    VerifiedIncidentMemory,
)

logger = logging.getLogger(__name__)


class HindsightMemoryService:
    def __init__(self, settings: Settings, client: HindsightClientProtocol | None = None):
        self.settings = settings
        self.client = client if client is not None else build_hindsight_client(settings)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def health_check(self) -> MemoryHealth:
        if self.client is None:
            return MemoryHealth(configured=False, available=False)
        try:
            await self.client.aget_version()
            return MemoryHealth(configured=True, available=True)
        except Exception as exc:  # SDK errors differ by transport/version
            logger.warning("Hindsight health check unavailable: %s", type(exc).__name__)
            return MemoryHealth(configured=True, available=False)

    async def retain_verified_incident(self, memory: VerifiedIncidentMemory) -> RetentionResult:
        if self.client is None:
            raise ApplicationError("MEMORY_UNAVAILABLE", "Hindsight memory is not configured", 503)
        document_id = f"incident:{memory.incident_id}"
        await self.client.aretain(
            bank_id=self.settings.HINDSIGHT_BANK_ID,
            content=render_verified_incident(memory),
            document_id=document_id,
            metadata={
                "incident_id": memory.incident_id,
                "service": memory.service,
                "environment": memory.environment,
                "verified": "true",
            },
            tags=[
                "verified:true",
                f"service:{memory.service}",
                f"environment:{memory.environment}",
                document_id,
            ],
            update_mode="replace",
            retain_async=False,
        )
        return RetentionResult(
            bank_id=self.settings.HINDSIGHT_BANK_ID,
            document_id=document_id,
            retained=True,
        )

    async def recall_similar_incidents(
        self, *, service: str, environment: str, query: str, max_tokens: int = 2048
    ) -> RecallResult:
        if self.client is None:
            return RecallResult(available=False)
        try:
            response = await self.client.arecall(
                bank_id=self.settings.HINDSIGHT_BANK_ID,
                query=query,
                max_tokens=max_tokens,
                budget="mid",
                tags=["verified:true", f"service:{service}", f"environment:{environment}"],
                tags_match="all_strict",
            )
        except Exception as exc:
            logger.warning("Hindsight recall unavailable: %s", type(exc).__name__)
            return RecallResult(available=False)
        return RecallResult(available=True, memories=normalize_recall_response(response))

    async def reflect_on_incident_patterns(self, query: str) -> ReflectionResult:
        if self.client is None:
            return ReflectionResult(available=False)
        try:
            response = await self.client.areflect(
                bank_id=self.settings.HINDSIGHT_BANK_ID,
                query=query,
                budget="low",
                tags=["verified:true"],
                tags_match="all_strict",
                include_facts=True,
            )
        except Exception as exc:
            logger.warning("Hindsight reflection unavailable: %s", type(exc).__name__)
            return ReflectionResult(available=False)
        return ReflectionResult(available=True, text=getattr(response, "text", None))
