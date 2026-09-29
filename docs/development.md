# Development

Use Python 3.12+, Node.js 20.9+, Docker Desktop, and PowerShell. Exact setup,
test, lint, build, and Compose commands are in the root README.

Configuration is loaded from environment variables with `pydantic-settings`.
Copy `.env.example` to `.env` for local Compose development. Never commit the
resulting `.env` file.

Health endpoints deliberately do not connect to PostgreSQL, so process health
can be tested independently. Database integration tests use
`TEST_DATABASE_URL`; live Hindsight tests use
`RUN_HINDSIGHT_INTEGRATION_TESTS=1` and are excluded by default.

Alembic migrations run when the API container starts. For a local environment:

```powershell
Set-Location apps\api
alembic upgrade head
```

