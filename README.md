# Incident Response Agent

Milestones M0–M18 of a memory-powered production incident response platform.
The system combines a controlled demo environment, observable evidence, a bounded
Groq-powered investigator, human-gated mitigation, recovery verification, postmortem
review, and verified-only organizational memory.

## Architecture

- `apps/api`: FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, incident lifecycle API
- `apps/web`: Next.js operator console and investigation timeline
- `demo`: gateway → checkout → payment production simulation
- `observability`: OpenTelemetry Collector, Prometheus, Alertmanager, Loki, Tempo
- `runbooks`: checked-in, read-only operational guidance
- `scenarios`: reproducible demo scenario definitions
- `evaluation`: deterministic FakeProvider quality and safety evaluation
- `scripts/seed_hindsight.py`: explicit development-only verified memory seed

PostgreSQL is the authoritative structured system of record. Hindsight is a
separate, optional store for verified organizational incident memory.

## Run with Docker Compose

From PowerShell at the repository root:

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8100/health
```

URLs:

- Web: http://localhost:3000
- Incident API and OpenAPI: http://localhost:8000 and http://localhost:8000/docs
- Demo gateway: http://localhost:8100
- Prometheus: http://localhost:9090
- Alertmanager: http://localhost:9093
- Loki: http://localhost:3100
- Tempo: http://localhost:3200

Healthy checkout:

```powershell
$body = @{ customer_id = 'demo-user'; amount = 1499.00 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8100/checkout -ContentType application/json -Body $body
```

Fault scenarios:

```powershell
Invoke-RestMethod -Method Post http://localhost:8100/demo/faults/db-pool-exhaustion
1..30 | ForEach-Object { try { Invoke-RestMethod -Method Post -Uri http://localhost:8100/checkout -ContentType application/json -Body $body } catch { } }
Invoke-RestMethod -Method Post http://localhost:8100/demo/faults/reset
Invoke-RestMethod -Method Post http://localhost:8100/demo/faults/payment-latency
Invoke-RestMethod -Method Post http://localhost:8100/demo/faults/reset
```

Or use the named scenario scripts:

```powershell
.\scripts\run_scenario.ps1 -Name recurring-db-pool
.\scripts\reset_demo.ps1
```

## Local development and validation

Python 3.12 or newer is required by the project. PowerShell commands:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\apps\api[dev]"
Set-Location apps\api
pytest
ruff check .
Set-Location ..\web
npm install
npm run lint
npm run build
Set-Location ..\..
docker compose config
git diff --check
```

Database integration tests are opt-in and must point to a disposable PostgreSQL
database:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://incident_response:change-me@localhost:5432/incident_response_test'
pytest -m integration
```

## Hindsight

Set `HINDSIGHT_BASE_URL`, optionally `HINDSIGHT_API_KEY`, and
`HINDSIGHT_BANK_ID`. With the API package installed:

```powershell
$env:PYTHONPATH = (Resolve-Path .\apps\api)
python .\scripts\seed_hindsight.py
$env:RUN_HINDSIGHT_INTEGRATION_TESTS = '1'
pytest .\apps\api\tests\test_hindsight_integration.py
```

The API starts without Hindsight. `/api/v1/memory/health` then reports
`configured: false, available: false`; database-backed incident workflows stay
available.

## Investigation and safety boundary

Set `GROQ_API_KEY` in `.env` to enable live investigation. The investigator uses only
named, schema-constrained tools and has bounded tool timeouts and a bounded iteration
count. It may collect evidence and propose an allowlisted demo action; it cannot approve
or execute that action.

An operator must approve a recommendation and then explicitly execute it. Execution is
idempotent and restricted to the simulated checkout rollback and payment circuit breaker.
Recovery is verified from current Prometheus data. Memory retention is allowed only after
resolution, human root-cause confirmation, and postmortem approval.

## Incident automation

`INCIDENT_AUTOMATION_MODE` controls safe lifecycle orchestration:

- `manual` preserves explicit investigate, execute, verify, postmortem, and memory actions.
- `assisted` (the default) investigates new alerts automatically, stops for human remediation
  approval, executes and verifies after approval, stops for human root-cause and postmortem
  review, then commits approved memory automatically.
- `demo_autopilot` additionally approves only the existing allowlisted simulator actions. The
  configuration is rejected outside development, demo, or test environments and when the action
  gateway is not the controlled demo gateway.

Webhook-triggered work uses FastAPI response background tasks with fresh database and client
lifecycles. Incident status is claimed under a PostgreSQL row lock so duplicate Alertmanager
notifications do not start duplicate investigations. Recovery retries and waits are bounded by
`AUTOMATION_RECOVERY_MAX_ATTEMPTS` and `AUTOMATION_RECOVERY_RETRY_SECONDS`.

Run the offline deterministic evaluation without Cloud access:

```powershell
.\.venv\Scripts\python.exe .\evaluation\run.py
```

## Limitations

The remediation gateway mutates only the demo simulator. Authentication and RBAC,
distributed rate limiting, durable background work, production SLO policies, and managed
observability are outside this hackathon release. Offline evaluation uses deterministic
fixtures and does not claim real-world benchmark performance.

## Milestones

M0 through M18 are represented in this repository. See
[`docs/milestones.md`](docs/milestones.md) for scope and validation expectations.
