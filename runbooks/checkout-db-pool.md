---
title: Checkout database connection pool exhaustion
service: checkout
version: "1.0"
symptoms: [checkout 503s, connection acquisition timeouts, pool availability zero]
---

# Checkout database connection pool exhaustion

## Diagnostic checks

- Check `db_pool_available`, checkout error rate, connection-timeout logs, and DB spans.
- Compare onset with the simulated checkout deployment ledger; confirm payment is healthy.

## Decisive evidence

Pool availability at zero plus connection-acquisition timeout logs and slow DB spans.
A 503 response alone is not proof of database pool exhaustion.

## Contradicting evidence

Healthy pool availability, no acquisition timeouts, or slow payment rather than DB spans.

## Safe mitigation guidance

After human approval, use the controlled demo rollback from checkout v2.18 to v2.17.
Never describe this demo operation as a Kubernetes or production rollback.

## Escalation criteria

Escalate if evidence disagrees, rollback fails, or recovery does not verify.

## Verification steps

Verify the alert clears, error rate and latency improve, and pool availability recovers.

## False leads

Gateway 503s, an old similar memory, or a deployment without current pool evidence.
