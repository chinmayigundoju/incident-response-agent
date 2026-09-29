from datetime import UTC, datetime, timedelta

import httpx

from app.tools.schemas import ServiceName, ToolDependencyError, TraceResult, TraceSummary


class TempoTool:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def search_recent_traces(self, service: ServiceName, *, minutes: int = 15) -> TraceResult:
        now = datetime.now(UTC)
        start = now - timedelta(minutes=min(max(minutes, 1), 60))
        params = {
            "tags": f"service.name={service.telemetry_name}",
            "start": str(int(start.timestamp())),
            "end": str(int(now.timestamp())),
            "limit": "100",
        }
        try:
            response = await self._client.get("/api/search", params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolDependencyError(f"Tempo search failed: {type(exc).__name__}") from exc
        traces = []
        for item in payload.get("traces", []):
            start_ns = item.get("startTimeUnixNano")
            traces.append(
                TraceSummary(
                    trace_id=str(item.get("traceID", "")),
                    root_service=item.get("rootServiceName"),
                    root_span=item.get("rootTraceName"),
                    start_time=(
                        datetime.fromtimestamp(int(start_ns) / 1e9, UTC) if start_ns else None
                    ),
                    duration_ms=(
                        float(item["durationMs"]) if item.get("durationMs") is not None else None
                    ),
                )
            )
        return TraceResult(
            query_name="recent_traces", service=service, traces=traces, observed_at=now
        )

    async def get_trace(self, trace_id: str) -> TraceResult:
        if (
            not trace_id
            or len(trace_id) > 64
            or any(ch not in "0123456789abcdefABCDEF" for ch in trace_id)
        ):
            raise ValueError("trace_id must be a hexadecimal trace identifier")
        try:
            response = await self._client.get(f"/api/traces/{trace_id}")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolDependencyError(f"Tempo trace lookup failed: {type(exc).__name__}") from exc
        services: set[str] = set()
        important_spans: list[dict[str, object]] = []
        errors: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        for batch in payload.get("batches", []):
            attributes = batch.get("resource", {}).get("attributes", [])
            service = next(
                (
                    item.get("value", {}).get("stringValue")
                    for item in attributes
                    if item.get("key") == "service.name"
                ),
                None,
            )
            if service:
                services.add(str(service))
            for scope in batch.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    start = int(span.get("startTimeUnixNano", 0))
                    end = int(span.get("endTimeUnixNano", 0))
                    if start:
                        starts.append(start)
                    if end:
                        ends.append(end)
                    status = span.get("status", {})
                    if status.get("code") == "STATUS_CODE_ERROR":
                        errors.append(
                            str(status.get("message") or span.get("name") or "span error")
                        )
                    important_spans.append(
                        {
                            "service": service,
                            "operation": span.get("name"),
                            "duration_ms": ((end - start) / 1e6 if end and start else None),
                            "status": status.get("code"),
                        }
                    )
        duration_ms = (max(ends) - min(starts)) / 1e6 if starts and ends else None
        summary = TraceSummary(
            trace_id=trace_id,
            root_service=next(iter(services), None),
            duration_ms=duration_ms,
            services=sorted(services),
            important_spans=important_spans,
            errors=errors,
        )
        return TraceResult(
            query_name="trace_by_id",
            traces=[summary],
            observed_at=datetime.now(UTC),
        )

    async def find_slow_checkout_traces(self, *, minutes: int = 15) -> TraceResult:
        result = await self.search_recent_traces(ServiceName.CHECKOUT, minutes=minutes)
        result.query_name = "slow_checkout_traces"
        result.traces.sort(key=lambda trace: trace.duration_ms or 0, reverse=True)
        return result
