import hashlib
import uuid

from app.memory.retention import render_verified_incident
from app.memory.schemas import RetentionResult, VerifiedIncidentMemory
from app.memory.service import HindsightMemoryService
from app.repositories.memory_sync import MemorySyncRepository


class VerifiedMemoryRetentionCoordinator:
    """Coordinates Hindsight writes with the authoritative memory_sync ledger."""

    def __init__(
        self,
        memory: HindsightMemoryService,
        sync_repository: MemorySyncRepository,
    ) -> None:
        self.memory = memory
        self.sync_repository = sync_repository

    async def retain(
        self, incident_id: uuid.UUID, payload: VerifiedIncidentMemory
    ) -> RetentionResult:
        if payload.incident_id != str(incident_id):
            raise ValueError("memory incident identifier does not match the database incident")
        document_id = f"incident:{incident_id}"
        existing = self.sync_repository.get(
            incident_id, self.memory.settings.HINDSIGHT_BANK_ID, document_id
        )
        if existing is not None and existing.status == "SUCCEEDED":
            return RetentionResult(
                bank_id=self.memory.settings.HINDSIGHT_BANK_ID,
                document_id=document_id,
                retained=True,
            )
        sync = self.sync_repository.begin(
            incident_id,
            self.memory.settings.HINDSIGHT_BANK_ID,
            document_id,
        )
        try:
            result = await self.memory.retain_verified_incident(payload)
        except Exception as exc:
            self.sync_repository.failed(sync, type(exc).__name__)
            raise
        checksum = hashlib.sha256(render_verified_incident(payload).encode()).hexdigest()
        self.sync_repository.succeeded(sync, checksum)
        return result
