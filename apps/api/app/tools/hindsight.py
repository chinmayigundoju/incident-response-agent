from app.agent.schemas import EvidenceType, InvestigationEvidence
from app.memory.service import HindsightMemoryService


class HindsightTool:
    def __init__(self, memory: HindsightMemoryService):
        self.memory = memory

    async def recall_incidents(
        self, *, service: str, environment: str, query: str
    ) -> InvestigationEvidence:
        result = await self.memory.recall_similar_incidents(
            service=service, environment=environment, query=query
        )
        return InvestigationEvidence(
            type=EvidenceType.HISTORICAL_MEMORY,
            source="hindsight",
            service=service,
            summary=(
                f"Hindsight returned {len(result.memories)} verified historical memories"
                if result.available
                else "Historical incident memory is unavailable"
            ),
            details={
                "available": result.available,
                "classification": "HISTORICAL_EVIDENCE",
                "memories": [item.model_dump(mode="json") for item in result.memories],
            },
        )
