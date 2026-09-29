from typing import Any, Protocol

from hindsight_client import Hindsight

from app.core.config import Settings


class HindsightClientProtocol(Protocol):
    async def aget_version(self) -> Any: ...
    async def aretain(self, **kwargs: Any) -> Any: ...
    async def arecall(self, **kwargs: Any) -> Any: ...
    async def areflect(self, **kwargs: Any) -> Any: ...
    async def aclose(self) -> None: ...


def build_hindsight_client(settings: Settings) -> HindsightClientProtocol | None:
    if not settings.hindsight_configured:
        return None
    return Hindsight(
        base_url=settings.HINDSIGHT_BASE_URL or "",
        api_key=settings.HINDSIGHT_API_KEY,
        timeout=settings.HINDSIGHT_TIMEOUT_SECONDS,
        user_agent="incident-response-agent/0.1.0",
    )
