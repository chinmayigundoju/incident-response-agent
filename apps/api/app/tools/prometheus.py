from datetime import UTC, datetime

import httpx

from app.tools.schemas import (
    MetricName,
    MetricResult,
    MetricSample,
    ServiceName,
    ToolDependencyError,
)

PROMQL_TEMPLATES = {
    MetricName.SERVICE_HEALTH: 'up{job="demo-services",instance=~"%s:.*"}',
    MetricName.REQUEST_RATE: 'sum(rate(http_requests_total{service="%s"}[5m]))',
    MetricName.ERROR_RATE: (
        'sum(rate(http_requests_total{service="%s",status=~"5.."}[5m])) '
        '/ clamp_min(sum(rate(http_requests_total{service="%s"}[5m])), 0.001)'
    ),
    MetricName.LATENCY_P95: (
        "histogram_quantile(0.95, sum by (le) "
        '(rate(http_request_duration_seconds_bucket{service="%s"}[5m])))'
    ),
    MetricName.POOL_AVAILABLE: 'db_pool_available{service="%s"}',
    MetricName.ACTIVE_ALERTS: 'ALERTS{alertstate="firing",service="%s"}',
    MetricName.PAYMENT_LATENCY: (
        "histogram_quantile(0.95, sum by (le) "
        '(rate(payment_request_duration_seconds_bucket{service="%s"}[5m])))'
    ),
}


class PrometheusTool:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_metric_snapshot(self, service: ServiceName, metric: MetricName) -> MetricResult:
        template = PROMQL_TEMPLATES[metric]
        if metric == MetricName.ACTIVE_ALERTS:
            name = service.value
        elif (
            metric in {MetricName.ERROR_RATE, MetricName.LATENCY_P95}
            and service == ServiceName.CHECKOUT
        ):
            name = ServiceName.GATEWAY.telemetry_name
        else:
            name = service.telemetry_name
        query = template % ((name, name) if template.count("%s") == 2 else name)
        try:
            response = await self._client.get("/api/v1/query", params={"query": query})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ToolDependencyError(f"Prometheus query failed: {type(exc).__name__}") from exc
        if payload.get("status") != "success":
            raise ToolDependencyError("Prometheus returned an unsuccessful response")
        samples: list[MetricSample] = []
        for item in payload.get("data", {}).get("result", []):
            raw = item.get("value")
            if not isinstance(raw, list) or len(raw) != 2:
                continue
            samples.append(
                MetricSample(
                    timestamp=datetime.fromtimestamp(float(raw[0]), UTC),
                    value=float(raw[1]),
                    labels={str(k): str(v) for k, v in item.get("metric", {}).items()},
                )
            )
        return MetricResult(
            query_name=metric.value,
            service=service,
            samples=samples,
            observed_at=datetime.now(UTC),
        )

    async def get_service_health(self, service: ServiceName) -> MetricResult:
        return await self.get_metric_snapshot(service, MetricName.SERVICE_HEALTH)

    async def get_error_rate(self, service: ServiceName) -> MetricResult:
        return await self.get_metric_snapshot(service, MetricName.ERROR_RATE)

    async def get_latency(self, service: ServiceName) -> MetricResult:
        return await self.get_metric_snapshot(service, MetricName.LATENCY_P95)

    async def get_pool_state(self, service: ServiceName) -> MetricResult:
        return await self.get_metric_snapshot(service, MetricName.POOL_AVAILABLE)

    async def get_db_pool_state(self, service: ServiceName) -> MetricResult:
        return await self.get_pool_state(service)

    async def get_active_alerts(self, service: ServiceName) -> MetricResult:
        return await self.get_metric_snapshot(service, MetricName.ACTIVE_ALERTS)

    async def get_payment_latency(self) -> MetricResult:
        return await self.get_metric_snapshot(ServiceName.PAYMENT, MetricName.PAYMENT_LATENCY)
