import asyncio
import os

import httpx
import pytest

from app.tools.loki import LokiTool
from app.tools.schemas import ServiceName
from app.tools.tempo import TempoTool

pytestmark = [pytest.mark.integration]


def enabled() -> bool:
    return os.getenv("RUN_OBSERVABILITY_INTEGRATION_TESTS") == "1"


@pytest.mark.asyncio
async def test_real_checkout_trace_is_retrievable_from_tempo():
    if not enabled():
        pytest.skip("set RUN_OBSERVABILITY_INTEGRATION_TESTS=1 to run live telemetry tests")
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            "http://localhost:8100/checkout",
            json={"customer_id": "telemetry-test", "amount": "10.00"},
        )
    tool = TempoTool("http://localhost:3200", timeout=10)
    try:
        found = False
        for _ in range(10):
            result = await tool.search_recent_traces(ServiceName.GATEWAY)
            found = any(trace.root_span == "POST /checkout" for trace in result.traces)
            if found:
                break
            await asyncio.sleep(2)
    finally:
        await tool.close()
    assert found


@pytest.mark.asyncio
async def test_real_db_fault_diagnostic_is_retrievable_from_loki():
    if not enabled():
        pytest.skip("set RUN_OBSERVABILITY_INTEGRATION_TESTS=1 to run live telemetry tests")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post("http://localhost:8100/demo/faults/db-pool-exhaustion")
            await client.post(
                "http://localhost:8100/checkout",
                json={"customer_id": "telemetry-test", "amount": "10.00"},
            )
        await asyncio.sleep(5)
        tool = LokiTool("http://localhost:3100", timeout=10)
        try:
            result = await tool.search_connection_timeout_logs()
        finally:
            await tool.close()
    finally:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post("http://localhost:8100/demo/faults/reset")
    assert any("acquiring database connection" in record.message for record in result.records)
