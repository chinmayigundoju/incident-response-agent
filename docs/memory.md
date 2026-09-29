# Hindsight memory

PostgreSQL owns structured incident truth. Hindsight stores compact, verified,
long-lived incident learning for semantic retrieval. The application isolates
the SDK behind `HindsightMemoryService`.

- `retain` stores a verified incident with an incident-specific document ID,
  string metadata, and strict tags. Replacement mode makes re-retention
  manageable.
- `recall` retrieves only facts tagged as verified and scoped to the requested
  service and environment. Returned SDK objects are normalized into
  application-owned schemas. SDK scores are passed through only when present;
  no confidence is invented.
- `reflect` is wrapped only for later offline pattern analysis. It is not the
  Incident Investigator.

The MVP uses one configurable organization/environment bank,
`demo-production-incidents` by default. Retention requires `resolved=true`,
`verified=true`, a confirmed root cause, decisive evidence, and a successful
mitigation. The development seed is explicitly marked verified; production
never seeds automatically.

During investigation, recalled records are labeled `HISTORICAL_MEMORY` and their details
carry `HISTORICAL_EVIDENCE`. They may suggest a hypothesis but cannot confirm the current
cause. The `/memory/commit` workflow requires a resolved incident, a human root-cause
verification record, and an approved postmortem. The PostgreSQL `memory_sync` row makes
successful commits idempotent.

When Hindsight is not configured or reachable, the API and PostgreSQL incident
flows continue. Health reports the distinction between disabled and configured
but unavailable. Recall returns an explicit unavailable structured result and
logs only the exception type, not secret material.
