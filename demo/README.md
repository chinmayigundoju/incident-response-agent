# Demo production system

`demo-gateway` forwards checkout traffic to `demo-checkout`, which performs a
synthetic database operation and calls `demo-payment`. The database-pool fault
is deliberately an application-level semaphore/pool simulation: it generates
real delay, HTTP 503s, spans, logs, and metrics without destabilizing PostgreSQL.

Faults are mutually exclusive and controlled at the gateway with:

- `POST /demo/faults/db-pool-exhaustion`
- `POST /demo/faults/payment-latency`
- `POST /demo/faults/reset`
- `GET /demo/faults`

