from datetime import datetime

import httpx
from pydantic import BaseModel

from app.tools.schemas import ServiceName, ToolDependencyError


class DeploymentRecord(BaseModel):
    service: ServiceName
    version: str
    deployed_at: datetime
    previous_version: str | None = None
    simulated: bool
    change_summary: str


class DeploymentTool:
    def __init__(self, gateway_base_url: str, timeout: float = 5.0):
        self._client = httpx.AsyncClient(base_url=gateway_base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_recent_deployments(
        self, service: ServiceName, since_minutes: int = 120
    ) -> list[DeploymentRecord]:
        since_minutes = min(max(since_minutes, 1), 1440)
        try:
            response = await self._client.get(
                f"/demo/deployments/{service.value}",
                params={"since_minutes": since_minutes},
            )
            response.raise_for_status()
            return [DeploymentRecord.model_validate(item) for item in response.json()]
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolDependencyError(f"Deployment lookup failed: {type(exc).__name__}") from exc
