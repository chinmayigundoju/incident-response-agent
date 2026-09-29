import json
from datetime import UTC, datetime, timedelta

import httpx

from app.tools.schemas import LogRecord, LogResult, ServiceName, ToolDependencyError

LOGQL_TEMPLATES = {
    "recent_errors": '{service_name="%s"} |~ "(?i)(error|exception|timeout|failed)"',
    "recent_logs": '{service_name="%s"}',
    "connection_timeouts": (
        '{service_name="%s"} |~ "(?i)(timed out acquiring database connection|pool timeout)"'
    ),
    "payment_latency": '{service_name="%s"} |~ "(?i)(payment.*latency|slow payment)"',
}


class LokiTool:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _search(
        self, service: ServiceName, query_name: str, *, minutes: int = 15
    ) -> LogResult:
        now = datetime.now(UTC)
        params = {
            "query": LOGQL_TEMPLATES[query_name] % service.telemetry_name,
            "start": str(
                int((now - timedelta(minutes=min(max(minutes, 1), 60))).timestamp() * 1e9)
            ),
            "end": str(int(now.timestamp() * 1e9)),
            "limit": "200",
            "direction": "backward",
        }
        try:
            response = await self._client.get("/loki/api/v1/query_range", params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolDependencyError(f"Loki query failed: {type(exc).__name__}") from exc
        if payload.get("status") != "success":
            raise ToolDependencyError("Loki returned an unsuccessful response")
        records: list[LogRecord] = []
        for stream in payload.get("data", {}).get("result", []):
            labels = {str(k): str(v) for k, v in stream.get("stream", {}).items()}
            for timestamp, message, *_ in stream.get("values", [])[:200]:
                parsed: dict[str, object] = {}
                try:
                    candidate = json.loads(str(message))
                    if isinstance(candidate, dict):
                        parsed = candidate
                except ValueError:
                    pass
                records.append(
                    LogRecord(
                        timestamp=datetime.fromtimestamp(int(timestamp) / 1e9, UTC),
                        service=str(
                            labels.get("service_name")
                            or parsed.get("service")
                            or service.telemetry_name
                        ),
                        level=str(parsed["level"]) if parsed.get("level") else None,
                        message=str(parsed.get("event") or parsed.get("body") or message),
                        trace_id=str(parsed["trace_id"]) if parsed.get("trace_id") else None,
                        span_id=str(parsed["span_id"]) if parsed.get("span_id") else None,
                        labels=labels,
                        attributes=parsed,
                    )
                )
        records.sort(key=lambda record: record.timestamp)
        return LogResult(
            query_name=query_name,
            service=service,
            records=records[:200],
            observed_at=now,
        )

    async def search_service_logs(self, service: ServiceName, *, minutes: int = 15) -> LogResult:
        return await self._search(service, "recent_logs", minutes=minutes)

    async def search_error_logs(self, service: ServiceName, *, minutes: int = 15) -> LogResult:
        return await self._search(service, "recent_errors", minutes=minutes)

    async def search_connection_timeout_logs(
        self, service: ServiceName = ServiceName.CHECKOUT, *, minutes: int = 15
    ) -> LogResult:
        return await self._search(service, "connection_timeouts", minutes=minutes)

    async def search_payment_latency_logs(self, *, minutes: int = 15) -> LogResult:
        return await self._search(ServiceName.PAYMENT, "payment_latency", minutes=minutes)

    async def get_recent_logs(
        self, service: ServiceName, *, errors_only: bool = True, minutes: int = 15
    ) -> LogResult:
        if errors_only:
            return await self.search_error_logs(service, minutes=minutes)
        return await self.search_service_logs(service, minutes=minutes)
