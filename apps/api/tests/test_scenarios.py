import httpx
import pytest

from app.services.scenarios import DEMO_TRAFFIC_REQUESTS, ScenarioName, ScenarioService


@pytest.mark.asyncio
async def test_fault_scenario_generates_bounded_checkout_traffic():
    checkout_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal checkout_requests
        if request.url.path == "/demo/faults/db-pool-exhaustion":
            return httpx.Response(200, json={"state": "DB_POOL_EXHAUSTION"})
        if request.url.path == "/checkout":
            checkout_requests += 1
            return httpx.Response(503, json={"detail": "Checkout failed"})
        return httpx.Response(404)

    service = ScenarioService("http://demo.test", 1)
    await service._client.aclose()
    service._client = httpx.AsyncClient(
        base_url="http://demo.test", transport=httpx.MockTransport(handler)
    )
    try:
        result = await service.activate(ScenarioName.RECURRING_DB_POOL)
    finally:
        await service.close()

    assert result.state == "DB_POOL_EXHAUSTION"
    assert checkout_requests == DEMO_TRAFFIC_REQUESTS


@pytest.mark.asyncio
async def test_healthy_baseline_does_not_generate_fault_traffic():
    checkout_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal checkout_requests
        if request.url.path == "/demo/faults/reset":
            return httpx.Response(200, json={"state": "NORMAL"})
        if request.url.path == "/checkout":
            checkout_requests += 1
        return httpx.Response(500)

    service = ScenarioService("http://demo.test", 1)
    await service._client.aclose()
    service._client = httpx.AsyncClient(
        base_url="http://demo.test", transport=httpx.MockTransport(handler)
    )
    try:
        result = await service.activate(ScenarioName.HEALTHY_BASELINE)
    finally:
        await service.close()

    assert result.state == "NORMAL"
    assert checkout_requests == 0
