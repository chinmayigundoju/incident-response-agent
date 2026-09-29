import asyncio
import enum
import logging

import httpx
from pydantic import BaseModel

from app.core.errors import ApplicationError

logger = logging.getLogger(__name__)

DEMO_TRAFFIC_REQUESTS = 30


class ScenarioName(enum.StrEnum):
    RECURRING_DB_POOL = "recurring-db-pool"
    PAYMENT_LATENCY = "payment-latency"
    MISLEADING_MEMORY = "misleading-memory"
    HEALTHY_BASELINE = "healthy-baseline"


class ScenarioResult(BaseModel):
    scenario: ScenarioName
    state: str


class ScenarioService:
    def __init__(self, gateway_base_url: str, timeout: float):
        self._client = httpx.AsyncClient(base_url=gateway_base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def activate(self, scenario: ScenarioName) -> ScenarioResult:
        route = {
            ScenarioName.RECURRING_DB_POOL: "/demo/faults/db-pool-exhaustion",
            ScenarioName.PAYMENT_LATENCY: "/demo/faults/payment-latency",
            ScenarioName.MISLEADING_MEMORY: "/demo/faults/payment-latency",
            ScenarioName.HEALTHY_BASELINE: "/demo/faults/reset",
        }[scenario]
        try:
            response = await self._client.post(route)
            response.raise_for_status()
            state = str(response.json()["state"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ApplicationError("DEMO_UNAVAILABLE", "Demo gateway is unavailable", 503) from exc
        if scenario != ScenarioName.HEALTHY_BASELINE:
            await self._generate_demo_traffic(scenario)
        return ScenarioResult(scenario=scenario, state=state)

    async def reset(self) -> ScenarioResult:
        return await self.activate(ScenarioName.HEALTHY_BASELINE)

    async def _generate_demo_traffic(self, scenario: ScenarioName) -> None:
        results = await asyncio.gather(
            *(
                self._client.post(
                    "/checkout",
                    json={"customer_id": "website-scenario-user", "amount": "1499.00"},
                )
                for _ in range(DEMO_TRAFFIC_REQUESTS)
            ),
            return_exceptions=True,
        )
        transport_failures = sum(isinstance(result, Exception) for result in results)
        if transport_failures:
            logger.warning(
                "Demo scenario traffic completed with transport failures: scenario=%s "
                "requests=%s transport_failures=%s",
                scenario.value,
                DEMO_TRAFFIC_REQUESTS,
                transport_failures,
            )
