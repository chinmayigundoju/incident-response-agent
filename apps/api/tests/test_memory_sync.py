import uuid

from app.core.config import Settings
from app.memory.coordinator import VerifiedMemoryRetentionCoordinator
from app.memory.schemas import RetentionResult, VerifiedIncidentMemory


class FakeMemoryService:
    def __init__(self):
        self.settings = Settings(HINDSIGHT_BASE_URL="http://hindsight:8888")

    async def retain_verified_incident(self, payload):
        return RetentionResult(
            bank_id=self.settings.HINDSIGHT_BANK_ID,
            document_id=f"incident:{payload.incident_id}",
            retained=True,
        )


class FakeSyncRepository:
    def __init__(self):
        self.status = None
        self.checksum = None

    def begin(self, incident_id, bank_id, document_id):
        self.status = "PENDING"
        return object()

    def get(self, incident_id, bank_id, document_id):
        return None

    def succeeded(self, sync, checksum):
        self.status = "SUCCEEDED"
        self.checksum = checksum

    def failed(self, sync, error_type):
        self.status = "FAILED"


async def test_retention_updates_memory_sync_ledger() -> None:
    incident_id = uuid.uuid4()
    payload = VerifiedIncidentMemory(
        incident_id=str(incident_id),
        service="checkout",
        environment="production",
        symptoms=["503 errors"],
        confirmed_root_cause="Pool reduced",
        decisive_evidence=["Pool availability zero"],
        successful_mitigation="Rollback",
        resolved=True,
        verified=True,
        verification_basis="approved_postmortem",
    )
    repository = FakeSyncRepository()
    coordinator = VerifiedMemoryRetentionCoordinator(FakeMemoryService(), repository)
    result = await coordinator.retain(incident_id, payload)
    assert result.retained is True
    assert repository.status == "SUCCEEDED"
    assert len(repository.checksum) == 64
