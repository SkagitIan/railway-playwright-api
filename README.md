# railway-playwright-api

## Run locally

```bash
pip install -r requirements.txt
playwright install chromium
OPENAI_API_KEY=your_key uvicorn main:app --reload
```

## Run tests

```bash
OPENAI_API_KEY=dummy pytest -q
```

## API versioning

### v1 endpoints (current, stable)
- `POST /extract-page-text`
- `POST /extract-links`
- `POST /extract-jobs-ai`
- `POST /analyze-network-fallback`

### v2 endpoint (pipeline)
- `POST /v2/jobs`

`/v2/jobs` runs the classify → acquire → extract → validate pipeline and returns pipeline metadata (`classification`, `validation`, and `debug`) in addition to extracted `jobs`.

## Compatibility and deprecation timeline

- v1 remains supported now for backward compatibility.
- Deprecation notice date: **May 20, 2026**.
- Earliest removal target for v1: **August 31, 2026**.
- During overlap, clients should migrate to `POST /v2/jobs`.

## Baseline snapshots

Baseline outputs for selected real URLs are stored in `tests/baseline_snapshots/`.
