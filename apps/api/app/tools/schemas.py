import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ServiceName(enum.StrEnum):
    GATEWAY = "gateway"
    CHECKOUT = "checkout"
    PAYMENT = "payment"

    @property
    def telemetry_name(self) -> str:
        return f"demo-{self.value}"


class MetricName(enum.StrEnum):
    SERVICE_HEALTH = "service_health"
    REQUEST_RATE = "request_rate"
    ERROR_RATE = "error_rate"
    LATENCY_P95 = "latency_p95"
    POOL_AVAILABLE = "pool_available"
    ACTIVE_ALERTS = "active_alerts"
    PAYMENT_LATENCY = "payment_latency"


class MetricSample(BaseModel):
    timestamp: datetime
    value: float
    labels: dict[str, str] = Field(default_factory=dict)


class MetricResult(BaseModel):
    query_name: str
    service: ServiceName
    samples: list[MetricSample]
    observed_at: datetime


class LogRecord(BaseModel):
    timestamp: datetime
    service: str
    level: str | None = None
    message: str
    trace_id: str | None = None
    span_id: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class LogResult(BaseModel):
    query_name: str
    service: ServiceName
    records: list[LogRecord]
    observed_at: datetime


class TraceSummary(BaseModel):
    trace_id: str
    root_service: str | None = None
    root_span: str | None = None
    start_time: datetime | None = None
    duration_ms: float | None = None
    services: list[str] = Field(default_factory=list)
    important_spans: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TraceResult(BaseModel):
    query_name: str
    service: ServiceName | None = None
    traces: list[TraceSummary] = Field(default_factory=list)
    trace: dict[str, Any] | None = None
    observed_at: datetime


class ToolDependencyError(RuntimeError):
    """A bounded dependency call failed or returned an invalid response."""
