# Security

- Secrets are supplied only through environment variables or a future secret
  manager. Health and error responses never include settings, credentials,
  connection strings, headers, or tracebacks.
- Containers use non-root runtime users where practical. Production database
  roles and network policy should follow least privilege.
- There is no arbitrary command execution endpoint. Fault injection accepts
  only enumerated modes.
- Alertmanager payloads are typed, bounded, and normalized before persistence.
- Hindsight creates a memory-poisoning risk if unreviewed claims become trusted
  organizational memory. The retention schema requires an explicitly resolved,
  verified incident, a confirmed root cause, decisive evidence, and successful
  mitigation. Unverified hypotheses cannot pass this boundary.
- Disruptive demo operations pass an explicit human approval gateway; agent output
  alone cannot authorize mutation. Rejected recommendations cannot execute and a
  successful action is idempotent.
- The model has no shell, SQL, Docker, Kubernetes, filesystem-write, or cloud-mutation
  tool. PromQL, LogQL, and service names are built from application allowlists.
- External calls, agent iterations, request bodies, and mutation rates are bounded.
  Dependency failures become explicit unavailable evidence; secrets are redacted.
- Incident events provide the audit trail for investigations, approvals, actions,
  recovery, postmortems, verification, and memory commits.
