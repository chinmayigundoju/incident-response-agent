# Memory evaluation

`evaluation/run.py` executes the recurring DB-pool, payment-latency, and misleading-memory
fixtures twice: `STATELESS` and `HINDSIGHT_ENABLED`. Both modes use the same deterministic
provider policy and current-evidence fixtures; the enabled mode additionally supplies
explicitly historical memory evidence.

The generated metrics are diagnosis correctness, Recall@K for the relevant recurring
case, historical-memory usage, false-transfer rate, tool-call count, runbook correctness,
evidence grounding, and unapproved disruptive actions. The final metric must remain zero.
Results are generated into `evaluation/results.json` and `evaluation/report.md`; committed
numbers should be treated as results of that recorded run, not a Cloud benchmark.
