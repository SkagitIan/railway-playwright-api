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

## Baseline snapshots

Baseline outputs for selected real URLs are stored in `tests/baseline_snapshots/`.
