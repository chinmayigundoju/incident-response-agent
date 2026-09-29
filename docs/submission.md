# Submission

## Problem and solution

The Incident Response Agent turns alert-driven incidents into evidence-grounded,
human-governed workflows. It correlates current metrics, logs, traces, deployments, and
runbooks, then uses Hindsight to recall only verified organizational learning.

## What to judge

- Before memory: the investigator reaches a proposal from current telemetry.
- Learning: only a resolved, human-verified, approved incident enters Hindsight.
- After memory: a recurring failure recalls that incident while rechecking live evidence.
- Safety: misleading DB history does not override healthy DB and slow payment evidence.
- Control: the model proposes; a human approves; a separate gateway performs only a demo
  allowlisted action; telemetry determines recovery.

## Technology

FastAPI, SQLAlchemy, PostgreSQL, Alembic, Next.js, OpenTelemetry, Prometheus,
Alertmanager, Loki, Tempo, Groq, and Hindsight Cloud.

## Known limitations

This is a single-process hackathon system. Rate limiting is process-local, the action
gateway controls only the simulator, authentication/RBAC is not production-ready, and
the evaluation uses deterministic fixtures rather than claiming external benchmark
performance. Production use would require durable queues, identity, authorization,
distributed rate limits, SLO-specific recovery policies, and managed observability.
