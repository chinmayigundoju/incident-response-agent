---
title: Payment provider latency
service: payment
version: "1.0"
symptoms: [elevated p95 latency, checkout timeout, slow payment spans]
---

# Payment provider latency

## Diagnostic checks

- Inspect payment p95, slow distributed traces, and payment latency logs.
- Confirm DB pool health and absence of connection acquisition timeouts.

## Decisive evidence

Elevated payment duration with slow payment spans and matching payment diagnostics.

## Contradicting evidence

DB acquisition timeout logs, pool availability zero, or healthy payment spans.

## Safe mitigation guidance

Reset the simulated payment fault only after explicit human approval.

## Escalation criteria

Escalate if provider latency persists or evidence cannot isolate the dependency.

## Verification steps

Verify payment and end-to-end checkout latency and alerts recover.

## False leads

Checkout 503s or recalled DB-pool memory without matching current pool evidence.
