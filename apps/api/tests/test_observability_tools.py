import asyncio

import httpx
import pytest

from app.agent.schemas import EvidenceType
from app.agent.tool_registry import ToolRegistry
from app.memory.schemas import MemoryRecord, RecallResult
from app.tools.hindsight import HindsightTool
from app.tools.loki import LokiTool
from app.tools.prometheus import PrometheusTool
from app.tools.schemas import ServiceName
from app.tools.tempo import TempoTool


@pytest.mark.asyncio
async def test_prometheus_normalizes_vector_and_uses_safe_template():
    observed_query = None

    async def handler(request):
        nonlocal observed_query
        observed_query = request.url.params["query"]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"result": [{"metric": {"service": "demo-gateway"}, "value": [1, "0.25"]}]},
            },
        )

    tool = PrometheusTool("http://prometheus.test")
    await tool._client.aclose()
    tool._client = httpx.AsyncClient(
        base_url="http://prometheus.test", transport=httpx.MockTransport(handler)
    )
    try:
        result = await tool.get_error_rate(ServiceName.CHECKOUT)
    finally:
        await tool.close()
    assert result.samples[0].value == 0.25
    assert 'service="demo-gateway"' in observed_query


@pytest.mark.asyncio
async def test_loki_parses_structured_log_fields():
    async def handler(_):
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {
                            "stream": {"service_name": "demo-checkout"},
                            "values": [
                                [
                                    "1000000000",
                                    '{"level":"ERROR","event":"pool timeout","trace_id":"abc"}',
                                ]
                            ],
                        }
                    ]
                },
            },
        )

    tool = LokiTool("http://loki.test")
    await tool._client.aclose()
    tool._client = httpx.AsyncClient(
        base_url="http://loki.test", transport=httpx.MockTransport(handler)
    )
    try:
        result = await tool.search_connection_timeout_logs()
    finally:
        await tool.close()
    assert result.records[0].message == "pool timeout"
    assert result.records[0].level == "ERROR"
    assert result.records[0].trace_id == "abc"


@pytest.mark.asyncio
async def test_tempo_normalizes_search_results():
    async def handler(_):
        return httpx.Response(
            200,
            json={
                "traces": [
                    {
                        "traceID": "abc123",
                        "rootServiceName": "demo-gateway",
                        "rootTraceName": "POST /checkout",
                        "startTimeUnixNano": "1000000000",
                        "durationMs": 1200,
                    }
                ]
            },
        )

    tool = TempoTool("http://tempo.test")
    await tool._client.aclose()
    tool._client = httpx.AsyncClient(
        base_url="http://tempo.test", transport=httpx.MockTransport(handler)
    )
    try:
        result = await tool.search_recent_traces(ServiceName.GATEWAY)
    finally:
        await tool.close()
    assert result.traces[0].trace_id == "abc123"
    assert result.traces[0].duration_ms == 1200


@pytest.mark.asyncio
async def test_hindsight_result_is_always_historical_evidence():
    class Memory:
        async def recall_similar_incidents(self, **_):
            return RecallResult(
                available=True,
                memories=[MemoryRecord(text="prior incident", source_document="incident:1")],
            )

    evidence = await HindsightTool(Memory()).recall_incidents(
        service="checkout", environment="test", query="timeouts"
    )
    assert evidence.type == EvidenceType.HISTORICAL_MEMORY
    assert evidence.details["classification"] == "HISTORICAL_EVIDENCE"


def test_invalid_service_is_rejected():
    with pytest.raises(ValueError):
        ToolRegistry._service("arbitrary-service")


def test_registry_marks_healthy_pool_and_degraded_payment_as_current_facts():
    healthy_pool = ToolRegistry._annotate_current_evidence(
        "get_db_pool_state", {"samples": [{"value": 5.0}]}
    )
    slow_payment = ToolRegistry._annotate_current_evidence(
        "get_payment_latency", {"samples": [{"value": 0.98}]}
    )

    assert healthy_pool["derived_facts"] == {
        "db_pool_state": "HEALTHY",
        "supports_db_pool_exhaustion": False,
        "observed_available_connections": [5.0],
    }
    assert slow_payment["derived_facts"] == {
        "payment_latency_state": "DEGRADED",
        "supports_payment_latency": True,
        "observed_p95_seconds": [0.98],
        "degraded_threshold_seconds": 0.5,
    }


def test_registry_marks_absent_current_logs_and_deployments():
    logs = ToolRegistry._annotate_current_evidence(
        "search_connection_timeout_logs", {"records": []}
    )
    deployments = ToolRegistry._annotate_current_evidence("get_recent_deployments", {"items": []})

    assert logs["derived_facts"] == {
        "matching_log_records": 0,
        "supports_current_log_pattern": False,
    }
    assert deployments["derived_facts"] == {
        "recent_deployment_count": 0,
        "recent_deployment_present": False,
    }


@pytest.mark.asyncio
async def test_tool_timeout_becomes_unavailable_evidence():
    class SlowPrometheus:
        async def get_error_rate(self, _):
            await asyncio.sleep(0.05)

        def __getattr__(self, _):
            async def unavailable(*args, **kwargs):
                await asyncio.sleep(0.05)

            return unavailable

    class DynamicTool:
        def __getattr__(self, _):
            async def unavailable(*args, **kwargs):
                await asyncio.sleep(0.05)

            return unavailable

    registry = object.__new__(ToolRegistry)
    registry.timeout = 0.001
    registry.prometheus = SlowPrometheus()
    registry.loki = registry.tempo = registry.deployments = DynamicTool()
    evidence = await registry.execute(
        "get_error_rate",
        incident={"id": "00000000-0000-0000-0000-000000000001", "service": "checkout"},
    )
    assert evidence.type == EvidenceType.TOOL_UNAVAILABLE
    assert evidence.details["available"] is False
