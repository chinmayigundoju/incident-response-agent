import json
import logging
import os

from fastapi import FastAPI
from fastapi.responses import Response
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["service", "method", "path", "status"]
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP duration", ["service", "method", "path"]
)
HTTP_ERRORS = Counter("http_errors_total", "HTTP errors", ["service", "path"])
CHECKOUT_FAILURES = Counter("checkout_failures_total", "Checkout failures", ["reason"])
DB_POOL_AVAILABLE = Gauge(
    "db_pool_available", "Simulated available DB connections", ["service"]
)
DB_POOL_ACTIVE = Gauge("db_pool_active", "Simulated active DB connections", ["service"])
DB_POOL_WAITING = Gauge(
    "db_pool_waiting", "Simulated DB connection waiters", ["service"]
)
PAYMENT_DURATION = Histogram(
    "payment_request_duration_seconds", "Payment duration", ["service"]
)
PAYMENT_ERRORS = Counter("payment_errors_total", "Payment errors", ["service"])
PAYMENT_FAULT_ACTIVE = Gauge(
    "payment_fault_active", "Simulated payment latency fault state", ["service"]
)


class TraceJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        span_context = trace.get_current_span().get_span_context()
        payload = {
            "service": os.getenv("OTEL_SERVICE_NAME", "unknown"),
            "level": record.levelname,
            "event": record.getMessage(),
            "trace_id": f"{span_context.trace_id:032x}"
            if span_context.is_valid
            else None,
            "span_id": f"{span_context.span_id:016x}"
            if span_context.is_valid
            else None,
        }
        return json.dumps(payload)


def configure_observability(app: FastAPI, service_name: str) -> None:
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    handler = logging.StreamHandler()
    handler.setFormatter(TraceJsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: "0.1.0",
            DEPLOYMENT_ENVIRONMENT: os.getenv("DEPLOYMENT_ENVIRONMENT", "development"),
        }
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
        trace.set_tracer_provider(tracer_provider)
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")
        )
        metrics.set_meter_provider(
            MeterProvider(resource=resource, metric_readers=[reader])
        )
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
        )
        root.addHandler(
            LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        )

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()

    @app.middleware("http")
    async def record_http(request, call_next):
        import time

        started = time.perf_counter()
        response = await call_next(request)
        path = request.url.path
        HTTP_REQUESTS.labels(
            service_name, request.method, path, str(response.status_code)
        ).inc()
        HTTP_DURATION.labels(service_name, request.method, path).observe(
            time.perf_counter() - started
        )
        if response.status_code >= 500:
            HTTP_ERRORS.labels(service_name, path).inc()
        return response

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
