import os

import pytest

from app.core.config import Settings
from app.memory.schemas import VerifiedIncidentMemory
from app.memory.service import HindsightMemoryService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HINDSIGHT_INTEGRATION_TESTS") != "1",
    reason="RUN_HINDSIGHT_INTEGRATION_TESTS is not enabled",
)


async def test_seed_and_recall_live_hindsight() -> None:
    settings = Settings()
    service = HindsightMemoryService(settings)
    memory = VerifiedIncidentMemory(
        incident_id="INC-DEMO-001",
        service="checkout",
        environment="production",
        symptoms=["checkout 503", "database connection waits", "recent deployment"],
        confirmed_root_cause="Database connection pool reduced from 50 to 5",
        decisive_evidence=["Pool availability reached zero", "Acquisition timeout logs"],
        successful_mitigation="Rollback checkout deployment",
        failed_investigation_paths=["Payment provider"],
        important_caveats=["Verify current evidence before applying prior mitigation"],
        resolved=True,
        verified=True,
        verification_basis="seeded_historical_incident",
    )
    try:
        await service.retain_verified_incident(memory)
        result = await service.recall_similar_incidents(
            service="checkout",
            environment="production",
            query=(
                "Checkout is returning 503 errors after a recent deployment and "
                "database connection waits are high."
            ),
        )
        assert result.available is True
        assert any(
            "pool" in item.text.lower() or "INC-DEMO-001" in item.text for item in result.memories
        )
        unrelated = await service.recall_similar_incidents(
            service="checkout",
            environment="production",
            query="The office coffee machine needs a new water filter.",
        )
        assert unrelated.available is True
    finally:
        await service.close()
