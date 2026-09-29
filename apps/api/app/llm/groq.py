import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

import httpx

from app.agent.policies import ALLOWED_INVESTIGATION_TOOLS, SYSTEM_POLICY
from app.agent.schemas import Diagnosis, InvestigationEvidence, ToolRequest
from app.llm.base import ProviderError

logger = logging.getLogger(__name__)

_CHECKOUT_EVIDENCE_PLAN = (
    "recall_incidents",
    "get_db_pool_state",
    "get_payment_latency",
    "search_connection_timeout_logs",
    "search_recent_traces",
    "get_recent_deployments",
    "get_runbook",
)

_PAYMENT_EVIDENCE_PLAN = (
    "recall_incidents",
    "get_db_pool_state",
    "get_payment_latency",
    "search_payment_latency_logs",
    "search_recent_traces",
    "search_error_logs",
    "get_runbook",
)

if not set(_CHECKOUT_EVIDENCE_PLAN + _PAYMENT_EVIDENCE_PLAN).issubset(ALLOWED_INVESTIGATION_TOOLS):
    raise RuntimeError("Deterministic evidence plan contains a non-allowlisted tool")


def _strict_diagnosis_schema() -> dict[str, Any]:
    schema = Diagnosis.model_json_schema()
    # Hypothesis IDs are authoritative application data, not model-generated evidence.
    schema["$defs"]["AgentHypothesis"]["properties"].pop("id")

    def make_strict(value: Any) -> Any:
        if isinstance(value, dict):
            result = {key: make_strict(item) for key, item in value.items() if key != "default"}
            if result.get("type") == "object" or "properties" in result:
                result["additionalProperties"] = False
                result["required"] = list(result.get("properties", {}))
            return result
        if isinstance(value, list):
            return [make_strict(item) for item in value]
        return value

    return make_strict(schema)


DIAGNOSIS_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "incident_diagnosis",
        "strict": True,
        "schema": _strict_diagnosis_schema(),
    },
}


class GroqProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        max_evidence_chars: int = 12_000,
        rate_limit_max_wait: float = 65.0,
    ):
        self.model = model
        self.max_evidence_chars = max_evidence_chars
        self._rate_limit_wait_remaining = rate_limit_max_wait
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def next_step(
        self,
        *,
        incident: dict[str, object],
        evidence: list[InvestigationEvidence],
        called_tools: list[str],
        force_diagnosis: bool = False,
    ) -> ToolRequest | Diagnosis:
        context = {
            "incident": incident,
            "called_tools": called_tools,
            "evidence": self._bounded_evidence(evidence),
        }
        plan = self._evidence_plan(incident)
        if not force_diagnosis:
            called = set(called_tools)
            next_tool = next((name for name in plan if name not in called), None)
            if next_tool is not None:
                return ToolRequest(
                    name=next_tool,
                    arguments={},
                    rationale="Collect the next source in the bounded deterministic evidence plan",
                )

        try:
            return await self._final_diagnosis(context)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            self._log_final_diagnosis_failure(exc)
            raise ProviderError(f"Groq provider failed: {type(exc).__name__}") from exc

    @staticmethod
    def _evidence_plan(incident: dict[str, object]) -> tuple[str, ...]:
        service = str(incident.get("service") or "").strip().lower().removeprefix("demo-")
        return _PAYMENT_EVIDENCE_PLAN if service == "payment" else _CHECKOUT_EVIDENCE_PLAN

    @staticmethod
    def _log_final_diagnosis_failure(exc: Exception) -> None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        retry_after = response.headers.get("retry-after") if response is not None else None
        reason = getattr(response, "reason_phrase", None) or type(exc).__name__
        error_code = None
        if response is not None:
            with suppress(TypeError, ValueError):
                error_code = response.json().get("error", {}).get("code")
        logger.warning(
            "Groq final diagnosis failed: exception_class=%s http_status=%s "
            "groq_error_code=%s retry_after=%s reason=%s",
            type(exc).__name__,
            status,
            error_code,
            retry_after,
            str(reason)[:80],
        )

    async def _final_diagnosis(self, context: dict[str, Any]) -> Diagnosis:
        instructions = (
            "Return the final proposed diagnosis using only the supplied evidence. "
            "Use exact evidence UUIDs. Preserve uncertainty and contradictions, "
            "choose only an allowlisted recommended action. Treat derived_facts as "
            "deterministic interpretations of current raw telemetry. The root "
            "cause remains proposed, not verified."
        )
        prompt = f"{instructions}\nContext:\n{json.dumps(context)}"
        response = await self._post(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_POLICY},
                    {"role": "user", "content": prompt},
                ],
                "response_format": DIAGNOSIS_RESPONSE_FORMAT,
                "temperature": 0,
            }
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content") or "{}"
        return Diagnosis.model_validate_json(content)

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        response = await self._client.post("/chat/completions", json=payload)
        delay = self._rate_limit_delay(response)
        if delay is not None:
            self._rate_limit_wait_remaining -= delay
            await asyncio.sleep(delay)
            response = await self._client.post("/chat/completions", json=payload)
        return response

    def _rate_limit_delay(self, response: httpx.Response) -> float | None:
        if response.status_code not in {413, 429}:
            return None
        try:
            if response.json().get("error", {}).get("code") != "rate_limit_exceeded":
                return None
            delay = float(response.headers["retry-after"])
            limit = int(response.headers.get("x-ratelimit-limit-tokens", "0"))
            remaining = int(response.headers.get("x-ratelimit-remaining-tokens", "0"))
        except (KeyError, TypeError, ValueError):
            return None
        # A full remaining bucket plus 413 means this request alone is too large;
        # waiting cannot make it valid.
        if response.status_code == 413 and limit and remaining >= limit:
            return None
        if delay <= 0 or delay > self._rate_limit_wait_remaining:
            return None
        return delay

    def _bounded_evidence(self, evidence: list[InvestigationEvidence]) -> list[dict[str, Any]]:
        """Project evidence into a deterministic prompt budget without altering stored evidence."""
        if not evidence:
            return []

        serialized = [item.model_dump(mode="json") for item in evidence]
        details_json = [self._compact_json(item["details"]) for item in serialized]
        projected = []
        for item, details in zip(serialized, details_json, strict=True):
            projected.append(
                {
                    **{key: value for key, value in item.items() if key != "details"},
                    "details": {
                        "truncated": True,
                        "original_characters": len(details),
                    },
                }
            )

        # Preserve every evidence item's identity and summary, then spend the remaining
        # budget on complete small results before excerpting a large telemetry result.
        for index in sorted(range(len(serialized)), key=lambda item: len(details_json[item])):
            candidate = list(projected)
            candidate[index] = serialized[index]
            if self._json_chars(candidate) <= self.max_evidence_chars:
                projected = candidate
                continue

            low = 0
            high = len(details_json[index])
            while low < high:
                midpoint = (low + high + 1) // 2
                candidate = list(projected)
                candidate[index] = {
                    **{key: value for key, value in serialized[index].items() if key != "details"},
                    "details": {
                        "truncated": True,
                        "original_characters": len(details_json[index]),
                        "json_excerpt": details_json[index][:midpoint],
                    },
                }
                if self._json_chars(candidate) <= self.max_evidence_chars:
                    low = midpoint
                else:
                    high = midpoint - 1
            if low:
                projected[index]["details"]["json_excerpt"] = details_json[index][:low]

        return projected

    @staticmethod
    def _compact_json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def _json_chars(cls, value: object) -> int:
        return len(cls._compact_json(value))
