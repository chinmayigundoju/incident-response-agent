"""Seed one explicitly verified historical incident into configured Hindsight."""

import asyncio

from app.core.config import get_settings
from app.memory.schemas import VerifiedIncidentMemory
from app.memory.service import HindsightMemoryService


async def main() -> None:
    settings = get_settings()
    print(f"Hindsight configured: {'yes' if settings.hindsight_configured else 'no'}")
    print(f"Bank: {settings.HINDSIGHT_BANK_ID}")
    memory = VerifiedIncidentMemory(
        incident_id="INC-DEMO-001",
        service="checkout",
        environment="production",
        symptoms=[
            "checkout 503 errors",
            "high p95 latency",
            "database connection wait",
            "recent checkout deployment",
        ],
        confirmed_root_cause="Database connection pool reduced from 50 to 5",
        decisive_evidence=[
            "DB pool available reached zero",
            "connection acquisition timeout logs",
            "slow database acquisition trace span",
        ],
        successful_mitigation="Rollback checkout deployment",
        failed_investigation_paths=["Payment provider"],
        recovery_verification="Checkout recovered following rollback",
        important_caveats=[
            "Do not assume identical symptoms imply the same root cause; verify pool saturation and deployment context first"
        ],
        resolved=True,
        verified=True,
        verification_basis="seeded_historical_incident",
    )
    service = HindsightMemoryService(settings)
    try:
        await service.retain_verified_incident(memory)
        print("Retain: succeeded")
        recall = await service.recall_similar_incidents(
            service="checkout",
            environment="production",
            query=(
                "Checkout is returning 503 errors after a recent deployment and "
                "database connection waits are high."
            ),
        )
        document_id = f"incident:{memory.incident_id}"
        if not recall.available or not any(
            item.source_document == document_id or memory.incident_id in item.text
            for item in recall.memories
        ):
            raise RuntimeError("Seeded incident was not returned by Hindsight recall")
        print("Recall: succeeded")
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(main())
