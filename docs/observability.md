# Observability

Demo services export traces, metrics, and logs over OTLP to the OpenTelemetry Collector.
The collector exposes Prometheus-compatible metrics and routes traces to Tempo and logs
to Loki. Prometheus evaluates demo alert rules and sends alerts to Alertmanager, which
creates or updates incidents through the API webhook.

The investigator cannot submit arbitrary PromQL or LogQL. It calls predefined query
templates with a validated `gateway`, `checkout`, or `payment` service. Dependency calls
have bounded timeouts; an unavailable source becomes explicit unavailable evidence and
is never replaced with invented telemetry.

Local endpoints:

- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`
