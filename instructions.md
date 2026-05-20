# Railway Playwright API — Quick Usage Guide

This file shows exactly how to call each endpoint after deploying to Railway.

## 1) Set your base URL

Replace with your real Railway domain:

```bash
export BASE_URL="https://your-service-name.up.railway.app"
```

Health check:

```bash
curl -s "$BASE_URL/"
```

Expected result:

```json
{"status":"ok"}
```

---

## 2) Request format (all POST endpoints)

Use this JSON body:

```json
{
  "url": "https://company-site.com/careers"
}
```

---

## 3) Endpoints

## `POST /extract-page-text`

Gets page title, combined page text, links found, and number of pages scraped.

```bash
curl -s -X POST "$BASE_URL/extract-page-text" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/jobs"}'
```

Expected result shape:

```json
{
  "url": "https://example.com/jobs",
  "final_url": "https://example.com/jobs",
  "title": "Jobs",
  "text": "...",
  "links": [{"text":"...","href":"..."}],
  "pages_scraped": 1
}
```

## `POST /extract-links`

Returns links likely related to jobs/careers plus total links discovered.

```bash
curl -s -X POST "$BASE_URL/extract-links" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}'
```

Expected result shape:

```json
{
  "url": "https://example.com",
  "likely_job_links": [{"text":"Careers","href":"https://example.com/careers"}],
  "total_links": 2
}
```

## `POST /extract-jobs-ai`

Main AI extraction endpoint (v1). Returns jobs and may include `network_fallback_spec` when no visible jobs are found.

```bash
curl -s -X POST "$BASE_URL/extract-jobs-ai" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/jobs"}'
```

Expected result shape:

```json
{
  "source_url": "https://example.com/jobs",
  "page_title": "Jobs",
  "company_name": "Example",
  "jobs": [
    {
      "title": "Software Engineer",
      "location": "Remote",
      "job_url": "https://example.com/jobs/123"
    }
  ],
  "notes": "...",
  "network_fallback_spec": {
    "data_delivery_type": "json_api"
  }
}
```

## `POST /analyze-network-fallback`

Inspects captured network traffic and returns a reusable scraping spec.

```bash
curl -s -X POST "$BASE_URL/analyze-network-fallback" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/jobs"}'
```

Expected result shape:

```json
{
  "data_delivery_type": "json_api",
  "requires_browser": false,
  "browser_target_url": null,
  "api_target_url": "https://api.example.com/jobs",
  "method": "GET",
  "required_headers": {
    "accept": null,
    "content_type": null,
    "authorization": null,
    "user_agent": null,
    "referer": null
  },
  "payload": null,
  "json_path_to_listings": "jobs",
  "explanation": "..."
}
```

## `POST /v2/jobs` (recommended)

Pipeline endpoint (classify → acquire → extract → validate). This is the preferred endpoint for new integrations.

```bash
curl -s -X POST "$BASE_URL/v2/jobs" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/jobs"}'
```

Expected result shape:

```json
{
  "url": "https://example.com/jobs",
  "jobs": [],
  "validation": {
    "success": false,
    "job_count": 0,
    "notes": "No jobs extracted yet"
  },
  "classification": {
    "strategy": "BROWSER_HAR"
  }
}
```

---

## 4) Common status codes

- `200`: request succeeded
- `422`: AI refused request or invalid input
- `504`: AI request timed out
- `500`: internal error

---

## 5) Quick integration tips

- Start with `POST /v2/jobs` for production.
- Retry on temporary `504` errors.
- Save raw responses in logs while you tune scraping targets.
- If `jobs` is empty, call `/analyze-network-fallback` to discover API-backed sources.
