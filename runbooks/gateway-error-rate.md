---
title: Gateway error-rate investigation
service: gateway
version: "1.0"
symptoms: [5xx spike, checkout unavailable]
---

# Gateway error-rate investigation

1. Confirm the gateway error ratio, then follow traces to the failing downstream service.
2. Compare log timestamps with deployments and fault activations.
3. Do not execute changes solely from gateway symptoms; identify the downstream cause.
4. Verify both gateway and downstream recovery.
