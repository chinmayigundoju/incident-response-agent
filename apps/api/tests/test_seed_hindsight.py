import pytest
from scripts import seed_hindsight

from app.core.config import Settings
from app.memory.schemas import MemoryRecord, RecallResult, RetentionResult


class FakeSeedMemoryService:
    def __init__(self, *, fail_retain: bool = False) -> None:
        self.fail_retain = fail_retain
        self.closed = False
        self.recall_called = False

    async def retain_verified_incident(self, memory):
        if self.fail_retain:
            raise TimeoutError("retain timed out")
        return RetentionResult(
            bank_id="demo-production-incidents",
            document_id=f"incident:{memory.incident_id}",
            retained=True,
        )

    async def recall_similar_incidents(self, **_kwargs):
        self.recall_called = True
        return RecallResult(
            available=True,
            memories=[
                MemoryRecord(
                    text="Verified incident INC-DEMO-001",
                    source_document="incident:INC-DEMO-001",
                )
            ],
        )

    async def close(self) -> None:
        self.closed = True


async def test_seed_closes_client_after_success(monkeypatch, capsys) -> None:
    settings = Settings(
        HINDSIGHT_BASE_URL="https://api.hindsight.vectorize.io",
        HINDSIGHT_API_KEY="must-not-be-printed",
    )
    service = FakeSeedMemoryService()
    monkeypatch.setattr(seed_hindsight, "get_settings", lambda: settings)
    monkeypatch.setattr(seed_hindsight, "HindsightMemoryService", lambda _: service)

    await seed_hindsight.main()

    output = capsys.readouterr().out
    assert service.closed is True
    assert service.recall_called is True
    assert "Hindsight configured: yes" in output
    assert "Bank: demo-production-incidents" in output
    assert "Retain: succeeded" in output
    assert "Recall: succeeded" in output
    assert settings.HINDSIGHT_API_KEY not in output


async def test_seed_closes_client_when_retain_fails(monkeypatch) -> None:
    settings = Settings(HINDSIGHT_BASE_URL="https://api.hindsight.vectorize.io")
    service = FakeSeedMemoryService(fail_retain=True)
    monkeypatch.setattr(seed_hindsight, "get_settings", lambda: settings)
    monkeypatch.setattr(seed_hindsight, "HindsightMemoryService", lambda _: service)

    with pytest.raises(TimeoutError, match="retain timed out"):
        await seed_hindsight.main()

    assert service.closed is True
    assert service.recall_called is False
