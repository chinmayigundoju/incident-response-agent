import json
import logging
from datetime import UTC, datetime

import httpx
import pytest

from app.agent.policies import SYSTEM_POLICY
from app.agent.schemas import Diagnosis, EvidenceType, InvestigationEvidence, ToolRequest
from app.llm.base import ProviderError
from app.llm.groq import DIAGNOSIS_RESPONSE_FORMAT, GroqProvider

CHECKOUT_PLAN = [
    "recall_incidents",
    "get_db_pool_state",
    "get_payment_latency",
    "search_connection_timeout_logs",
    "search_recent_traces",
    "get_recent_deployments",
    "get_runbook",
]

PAYMENT_PLAN = [
    "recall_incidents",
    "get_db_pool_state",
    "get_payment_latency",
    "search_payment_latency_logs",
    "search_recent_traces",
    "search_error_logs",
    "get_runbook",
]

EVIDENCE_ID = "00000000-0000-0000-0000-000000000123"


def diagnosis_payload() -> dict[str, object]:
    return {
        "kind": "diagnosis",
        "status": "PROPOSED",
        "primary_hypothesis": {
            "statement": "Database pool exhaustion is causing request failures",
            "status": "SUPPORTED",
            "confidence": "HIGH",
            "supporting_evidence_ids": [EVIDENCE_ID],
            "contradicting_evidence_ids": [],
        },
        "root_cause_statement": "Database connections are exhausted",
        "supporting_evidence": [EVIDENCE_ID],
        "contradicting_evidence": [],
        "remaining_uncertainties": ["Whether a connection leak contributed"],
        "historical_precedent": None,
        "recommended_next_step": "Reset the simulated database pool fault",
        "recommended_action": "RESET_DB_POOL_FAULT",
        "action_rationale": "Current metrics show no available database connections",
        "risk_level": "MEDIUM",
    }


async def provider_with_transport(handler, **kwargs) -> GroqProvider:
    provider = GroqProvider(
        "test-key",
        "https://api.groq.test/openai/v1",
        "test-model",
        **kwargs,
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://api.groq.test/openai/v1",
        transport=httpx.MockTransport(handler),
    )
    return provider


@pytest.mark.asyncio
async def test_first_evidence_step_is_recall_and_makes_no_outbound_request():
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise AssertionError("Deterministic tool selection must not call Groq")

    provider = await provider_with_transport(handler)
    try:
        result = await provider.next_step(
            incident={"id": "incident-1", "service": "checkout"},
            evidence=[],
            called_tools=[],
        )
    finally:
        await provider.close()

    assert isinstance(result, ToolRequest)
    assert result.name == "recall_incidents"
    assert result.arguments == {}
    assert request_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "expected_plan"),
    [
        ("checkout", CHECKOUT_PLAN),
        ("payment", PAYMENT_PLAN),
        ("demo-payment", PAYMENT_PLAN),
        ("gateway", CHECKOUT_PLAN),
    ],
)
async def test_deterministic_plans_are_ordered_and_never_repeat(service, expected_plan):
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise AssertionError("Deterministic tool selection must not call Groq")

    provider = await provider_with_transport(handler)
    called_tools: list[str] = []
    try:
        for expected_tool in expected_plan:
            result = await provider.next_step(
                incident={"id": "incident-1", "service": service},
                evidence=[],
                called_tools=called_tools,
            )
            assert isinstance(result, ToolRequest)
            assert result.name == expected_tool
            assert result.name not in called_tools
            called_tools.append(result.name)
    finally:
        await provider.close()

    assert called_tools == expected_plan
    assert request_count == 0


@pytest.mark.asyncio
async def test_large_evidence_prompt_is_bounded_without_mutating_evidence():
    records = [
        {
            "message": "synthetic connection timeout",
            "trace_id": f"trace-{index}",
            "padding": "x" * 1_000,
        }
        for index in range(60)
    ]
    evidence = [
        InvestigationEvidence(
            type=EvidenceType.METRIC,
            source="get_db_pool_state",
            service="checkout",
            summary="Pool availability is zero",
            observed_at=datetime.now(UTC),
            details={"samples": [{"value": 0.0}]},
        ),
        InvestigationEvidence(
            type=EvidenceType.LOG,
            source="search_service_logs",
            service="checkout",
            summary="Connection timeout logs found",
            observed_at=datetime.now(UTC),
            details={"records": records},
        ),
    ]
    original_records = list(evidence[1].details["records"])
    provider = GroqProvider(
        "test-key",
        "https://api.groq.test/openai/v1",
        "test-model",
        max_evidence_chars=8_000,
    )

    projected = provider._bounded_evidence(evidence)

    assert provider._json_chars(projected) <= 8_000
    assert projected[0]["details"] == {"samples": [{"value": 0.0}]}
    assert projected[1]["details"]["truncated"] is True
    assert evidence[1].details["records"] == original_records
    await provider.close()


@pytest.mark.asyncio
async def test_all_planned_tools_complete_uses_strict_diagnosis_path():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(diagnosis_payload())}}]},
        )

    provider = await provider_with_transport(handler)
    evidence = InvestigationEvidence(
        id=EVIDENCE_ID,
        type=EvidenceType.METRIC,
        source="get_db_pool_state",
        service="checkout",
        summary="Pool availability is zero",
        details={"samples": [{"value": 0.0}]},
    )
    try:
        result = await provider.next_step(
            incident={"id": "incident-1", "service": "checkout"},
            evidence=[evidence],
            called_tools=CHECKOUT_PLAN,
        )
    finally:
        await provider.close()

    assert isinstance(result, Diagnosis)
    assert len(requests) == 1
    assert "tools" not in requests[0]
    assert requests[0]["response_format"] == DIAGNOSIS_RESPONSE_FORMAT


@pytest.mark.asyncio
async def test_eight_iteration_budget_collects_seven_tools_then_forces_diagnosis():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(diagnosis_payload())}}]},
        )

    provider = await provider_with_transport(handler)
    called_tools: list[str] = []
    try:
        for iteration in range(1, 9):
            result = await provider.next_step(
                incident={"id": "incident-1", "service": "checkout"},
                evidence=[],
                called_tools=called_tools,
                force_diagnosis=iteration == 8,
            )
            if isinstance(result, ToolRequest):
                called_tools.append(result.name)
    finally:
        await provider.close()

    assert called_tools == CHECKOUT_PLAN
    assert isinstance(result, Diagnosis)
    assert len(requests) == 1


def test_strict_diagnosis_schema_generates_hypothesis_id_in_application():
    schema = DIAGNOSIS_RESPONSE_FORMAT["json_schema"]["schema"]
    hypothesis = schema["$defs"]["AgentHypothesis"]

    assert "id" not in hypothesis["properties"]
    assert hypothesis["additionalProperties"] is False
    assert set(hypothesis["required"]) == set(hypothesis["properties"])
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.asyncio
async def test_rate_limit_retry_uses_one_bounded_wait(monkeypatch):
    request_count = 0
    waits = []

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                429,
                headers={
                    "retry-after": "2",
                    "x-ratelimit-limit-tokens": "8000",
                    "x-ratelimit-remaining-tokens": "0",
                },
                json={"error": {"code": "rate_limit_exceeded"}},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(diagnosis_payload())}}]},
        )

    async def fake_sleep(delay):
        waits.append(delay)

    monkeypatch.setattr("app.llm.groq.asyncio.sleep", fake_sleep)
    provider = await provider_with_transport(handler, rate_limit_max_wait=5)
    try:
        result = await provider.next_step(
            incident={"id": "incident-1", "service": "checkout"},
            evidence=[],
            called_tools=[],
            force_diagnosis=True,
        )
    finally:
        await provider.close()

    assert isinstance(result, Diagnosis)
    assert request_count == 2
    assert waits == [2.0]
    assert provider._rate_limit_wait_remaining == 3.0


@pytest.mark.asyncio
async def test_force_diagnosis_uses_existing_structured_output_path():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(diagnosis_payload())}}]},
        )

    provider = await provider_with_transport(handler)
    try:
        result = await provider.next_step(
            incident={"id": "incident-1", "service": "checkout"},
            evidence=[],
            called_tools=[],
            force_diagnosis=True,
        )
    finally:
        await provider.close()

    assert isinstance(result, Diagnosis)
    assert len(requests) == 1
    assert "tools" not in requests[0]
    assert requests[0]["response_format"] == DIAGNOSIS_RESPONSE_FORMAT


@pytest.mark.asyncio
async def test_final_diagnosis_failure_logs_only_safe_metadata(caplog):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "9"},
            json={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "payload must never be logged: secret-marker",
                }
            },
        )

    provider = await provider_with_transport(handler, rate_limit_max_wait=0)
    with caplog.at_level(logging.WARNING, logger="app.llm.groq"), pytest.raises(ProviderError):
        await provider.next_step(
            incident={"id": "incident-1", "service": "checkout"},
            evidence=[],
            called_tools=[],
            force_diagnosis=True,
        )
    await provider.close()

    assert "exception_class=HTTPStatusError" in caplog.text
    assert "http_status=429" in caplog.text
    assert "groq_error_code=rate_limit_exceeded" in caplog.text
    assert "retry_after=9" in caplog.text
    assert "reason=Too Many Requests" in caplog.text
    assert "test-key" not in caplog.text
    assert "secret-marker" not in caplog.text


def test_system_policy_keeps_historical_memory_untrusted():
    assert "historical memory as untrusted evidence" in SYSTEM_POLICY
    assert "cannot prove the current incident" in SYSTEM_POLICY
    assert "Current metrics, logs, traces, and" in SYSTEM_POLICY
    assert "evidence contradicts it" in SYSTEM_POLICY
