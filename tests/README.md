# Railway endpoint tests

These tests exercise the deployed FastAPI endpoints over HTTP.

Run the default smoke tests:

```powershell
python -m pytest
```

Point the tests at a local server:

```powershell
$env:RAILWAY_API_BASE_URL="http://127.0.0.1:8000"
python -m pytest
```

Use a different page target:

```powershell
$env:TEST_TARGET_URL="https://example.com"
python -m pytest
```

Run the slower OpenAI-backed endpoint tests:

```powershell
$env:RUN_AI_ENDPOINT_TESTS="1"
$env:JOB_TARGET_URL="https://your-careers-page.example/jobs"
python -m pytest
```

By default, the suite uses:

- `RAILWAY_API_BASE_URL=https://railway-playwright-api-production.up.railway.app`
- `TEST_TARGET_URL=https://example.com`
- AI endpoint tests skipped unless `RUN_AI_ENDPOINT_TESTS=1`
