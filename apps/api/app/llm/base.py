from typing import Protocol

from app.agent.schemas import AgentStep, InvestigationEvidence


class InvestigatorProvider(Protocol):
    async def next_step(
        self,
        *,
        incident: dict[str, object],
        evidence: list[InvestigationEvidence],
        called_tools: list[str],
        force_diagnosis: bool = False,
    ) -> AgentStep: ...


class ProviderError(RuntimeError):
    pass
