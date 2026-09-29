# Five-minute demo script

## 0:00–0:30 — Problem

Production incidents create fragmented telemetry and pressure operators to repeat old
fixes. Explain that the product gathers evidence while preserving human authority.

## 0:30–1:00 — Architecture

Show the diagram: demo services emit OTLP, Prometheus alerts, PostgreSQL owns state, and
Hindsight provides verified history—not current truth.

## 1:00–2:00 — Trigger DB pool incident

Run `scripts/run_scenario.ps1 -Name recurring-db-pool`. Show the firing alert and incident.

## 2:00–3:00 — Agent investigation

Open the incident and click Investigate. Show current metrics, timeout logs, slow trace,
simulated v2.18 deployment, DB-pool runbook, hypotheses, and cited evidence.

## 3:00–3:40 — Historical Hindsight memory

Show the prior verified incident and the warning that historical memory is evidence, not
proof. Contrast the before-memory investigation with the recurring incident.

## 3:40–4:15 — Human approval and controlled remediation

Approve the `ROLLBACK_CHECKOUT_DEMO` recommendation, then separately execute it. Emphasize
that this is a controlled simulator action, not a Kubernetes rollback.

## 4:15–4:40 — Recovery verification

Run bounded verification and show alert, error-rate, latency, and pool checks before the
incident reaches RESOLVED.

## 4:40–5:00 — Postmortem and learning

Confirm the root cause, generate and approve the postmortem, then commit verified memory.
Trigger `misleading-memory` and show that current payment evidence defeats DB-history bias.

## Backup plan

If a Cloud or Docker dependency is unavailable, use the persisted incident UI, checked-in
runbooks, generated offline evaluation report, and unit tests. State which dependency is
unavailable; do not claim live telemetry or memory calls occurred.
