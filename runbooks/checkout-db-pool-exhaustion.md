---
title: Checkout database pool exhaustion
service: checkout
version: "1.0"
symptoms: [high error rate, pool saturation, connection acquisition timeout]
---

# Checkout database pool exhaustion

1. Confirm `db_pool_active` is at capacity and `db_pool_waiting` is increasing.
2. Correlate checkout errors with the most recent checkout deployment.
3. Prefer rolling back a recently introduced connection leak over increasing capacity.
4. After an approved rollback, verify pool pressure and checkout error rate recover.
