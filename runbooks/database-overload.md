---
title: Database overload
service: checkout
version: "1.0"
symptoms: [slow database spans, saturation, elevated checkout latency]
---

# Database overload

## Diagnostic checks

Compare DB span duration, pool state, request volume, and timeout logs.

## Decisive evidence

Sustained DB latency with saturation while downstream payment remains healthy.

## Contradicting evidence

Healthy DB spans or latency isolated to payment.

## Safe mitigation guidance

Escalate for capacity review; do not mutate infrastructure from this agent.

## Escalation criteria

Escalate immediately for data integrity errors or sustained overload.

## Verification steps

Confirm DB spans and end-to-end latency recover and alerts clear.

## False leads

A single slow request or historical memory without matching current telemetry.
