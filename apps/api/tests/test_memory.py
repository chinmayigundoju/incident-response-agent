from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.memory.schemas import VerifiedIncidentMemory
from app.memory.service import HindsightMemoryService


def verified_memory(**overrides):
    data = {
        "incident_id": "INC-DEMO-001",
        "service": "checkout",
        "environment": "production",
        "symptoms": ["503 errors"],
        "confirmed_root_cause": "Database pool reduced",
        "decisive_evidence": ["available connections reached zero"],
        "successful_mitigation": "Rollback",
        "resolved": True,
        "verified": True,
        "verification_basis": "approved_postmortem",
    }
    data.update(overrides)
    return VerifiedIncidentMemory(**data)


class FakeHindsight:
    def __init__(self):
        self.retain_kwargs = None
        self.recall_kwargs = None
        self.closed = False

    async def aget_version(self):
        return SimpleNamespace(api_version="test")

    async def aretain(self, **kwargs):
        self.retain_kwargs = kwargs
        return SimpleNamespace(success=True)

    async def arecall(self, **kwargs):
        self.recall_kwargs = kwargs
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    text="verified incident",
                    document_id="incident:INC-DEMO-001",
                    metadata={"verified": "true"},
                    scores=SimpleNamespace(
                        final=0.8,
                        reranker=None,
                        semantic=0.7,
                        keyword=None,
                    ),
                )
            ]
        )

    async def areflect(self, **_kwargs):
        return SimpleNamespace(text="pattern")

    async def aclose(self):
        self.closed = True


def test_unverified_incident_cannot_be_trusted_memory() -> None:
    with pytest.raises(ValidationError):
        verified_memory(verified=False)


async def test_missing_configuration_is_safe() -> None:
    settings = Settings(HINDSIGHT_BASE_URL=None)
    service = HindsightMemoryService(settings)
    assert (await service.health_check()).model_dump() == {
        "configured": False,
        "available": False,
    }
    assert (
        await service.recall_similar_incidents(
            service="checkout", environment="production", query="503 errors"
        )
    ).model_dump() == {"available": False, "memories": []}


async def test_retain_uses_verified_tags_and_document_id() -> None:
    fake = FakeHindsight()
    settings = Settings(HINDSIGHT_BASE_URL="http://hindsight:8888")
    result = await HindsightMemoryService(settings, fake).retain_verified_incident(
        verified_memory()
    )
    assert result.document_id == "incident:INC-DEMO-001"
    assert fake.retain_kwargs["update_mode"] == "replace"
    assert fake.retain_kwargs["retain_async"] is False
    assert "verified:true" in fake.retain_kwargs["tags"]


async def test_recall_requires_all_verified_scope_tags() -> None:
    fake = FakeHindsight()
    settings = Settings(HINDSIGHT_BASE_URL="http://hindsight:8888")
    result = await HindsightMemoryService(settings, fake).recall_similar_incidents(
        service="checkout", environment="production", query="503 after deployment"
    )
    assert result.available is True
    assert result.memories[0].source_document == "incident:INC-DEMO-001"
    assert fake.recall_kwargs["tags_match"] == "all_strict"
    assert "verified:true" in fake.recall_kwargs["tags"]


async def test_memory_service_close_closes_sdk_client() -> None:
    fake = FakeHindsight()
    settings = Settings(HINDSIGHT_BASE_URL="http://hindsight:8888")
    service = HindsightMemoryService(settings, fake)

    await service.close()

    assert fake.closed is True
