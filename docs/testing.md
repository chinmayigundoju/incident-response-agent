# Testing

From the repository root:

```powershell
Set-Location .\apps\api
..\..\.venv\Scripts\python.exe -m pytest
..\..\.venv\Scripts\python.exe -m ruff check .
..\..\.venv\Scripts\python.exe -m ruff format --check .
Set-Location ..\web
npm run lint
npm run build
Set-Location ..\..
docker compose config --quiet
git diff --check
```

Cloud and running-stack tests are disabled normally. Enable only the integration under
test and provide its environment configuration:

```powershell
$env:RUN_HINDSIGHT_INTEGRATION_TESTS = '1'
$env:RUN_GROQ_INTEGRATION_TESTS = '1'
$env:RUN_OBSERVABILITY_INTEGRATION_TESTS = '1'
```

Do not enable these flags in a standard offline CI run.
