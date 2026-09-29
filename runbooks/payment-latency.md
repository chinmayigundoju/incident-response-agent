---
title: Payment provider latency
service: payment
version: "1.0"
symptoms: [elevated p95 latency, checkout timeout, slow payment spans]
---

# Payment provider latency

1. Confirm payment p95 latency and inspect slow distributed traces.
2. Check whether errors are downstream timeouts rather than checkout failures.
3. Use the payment circuit-breaker action only after human approval.
4. Verify payment and end-to-end checkout latency after mitigation.
