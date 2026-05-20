# Job Scraper — Architecture Redesign

**Status:** Design Proposal  
**Replaces:** `main.py` (monolithic)  
**Goal:** A self-learning, pipeline-based job scraper that gets smarter with every run and requires zero manual maintenance of ATS platform knowledge.

---

## The Problem With the Current System

The existing `main.py` has one fundamental flaw: **it is a single function that grew outward**. Every new requirement — pagination, HAR capture, network fallback, AI extraction — was bolted on as a nested conditional rather than a separate concern.

The result:

- A "fallback" that only fires *after* a failed extraction, meaning a wasted browser pass on every unknown SPA
- No memory between requests — the system re-discovers the same employer's ATS platform every single time
- AI called on every request, even for platforms like Greenhouse and Lever that have clean public JSON APIs
- Pagination, HAR recording, AI prompting, schema definitions, and HTTP routing all living in one file
- Adding support for a new ATS means editing core logic rather than adding a file

The goal of this redesign is not to rewrite for its own sake. It is to separate the four things the scraper actually does — **classify, acquire, extract, validate** — so each can evolve independently and the system can teach itself.

---

## Mental Model

Think of the scraper as a factory line, not a Swiss Army knife.

```
URL → [Classify] → [Acquire] → [Extract] → [Validate] → Structured Jobs
```

Each stage receives the output of the previous stage. Each stage has exactly one job. Failures cascade to the next strategy within that stage rather than bubbling up as unhandled exceptions through a monolith.

The other mental model that matters: **the system should be an expert that gets more experienced over time, not a tool that starts from zero on every run.** That expertise lives in the Spec Store.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          API Layer                              │
│   POST /jobs   (single unified endpoint — caller knows nothing  │
│                 about strategy, ATS, or fallback logic)         │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                      Pipeline Orchestrator                      │
│                                                                 │
│   classify() → acquire() → extract() → validate()              │
│                                                                 │
│   Handles cascade logic, retries, and spec promotion            │
└──────┬──────────────┬──────────────┬──────────────┬────────────┘
       │              │              │              │
  ┌────▼────┐   ┌─────▼─────┐  ┌────▼────┐   ┌────▼────┐
  │Classif- │   │ Acquirer  │  │Extract- │   │Validat- │
  │  ier    │   │           │  │  or     │   │  or     │
  │         │   │ • HTTP    │  │         │   │         │
  │ Signal  │   │ • Browser │  │ • Parse │   │ • Count │
  │  Scan   │   │ • HAR     │  │ • AI    │   │ • Conf. │
  │ AI Fing.│   │           │  │         │   │ • Retry │
  └────┬────┘   └───────────┘  └─────────┘   └─────────┘
       │
  ┌────▼─────────────────────────────┐
  │           Spec Store             │
  │  SQLite — domain pattern lookup  │
  │  Confidence tracking             │
  │  Auto-promotion                  │
  │  Self-healing on failure         │
  └──────────────────────────────────┘
```

---

## Folder Structure

```
scraper/
├── api.py                   # FastAPI routes — thin, no logic
├── pipeline.py              # Orchestrates the four stages
│
├── stages/
│   ├── classifier.py        # What kind of source is this?
│   ├── acquirer.py          # Get raw data the right way
│   ├── extractor.py         # Raw data → structured jobs
│   └── validator.py         # Cross-check, retry, confidence
│
├── ats/
│   ├── signal_scanner.py    # Fast DOM/URL/script fingerprinting
│   ├── fingerprinter.py     # AI-powered unknown ATS identification
│   ├── spec_store.py        # SQLite-backed spec cache
│   └── parsers/             # Deterministic parsers for known platforms
│       ├── greenhouse.py
│       ├── lever.py
│       ├── ashby.py
│       └── neogov.py
│
├── browser/
│   ├── context.py           # Playwright lifecycle (one place)
│   ├── paginator.py         # All pagination strategies
│   └── har.py               # HAR capture and filtering
│
├── ai/
│   ├── client.py            # OpenAI wrapper, timeout handling
│   └── prompts.py           # Every prompt string in one file
│
└── models.py                # Pydantic schemas — JobListing, ScrapeResult, etc.
```

**The rule:** if you're editing two files to add a feature, the boundary between them is probably wrong.

---

## Stage 1 — Classifier

**Job:** Decide the acquisition strategy before touching a browser.  
**Input:** URL + Spec Store lookup  
**Output:** A `Classification` object — strategy enum + any relevant spec/fingerprint

### Decision tree

```
                    ┌─ Is there a promoted spec in the store? ──► CACHED_SPEC (fastest)
                    │
URL + Store ───────►├─ Does a DOM signal match a known ATS? ────► DIRECT_JSON_API or BROWSER_HTML
                    │   (script tags, URL pattern, iframe src)       depending on whether that
                    │                                                 ATS has a public API
                    │
                    ├─ Is there an unconfident cached spec? ─────► CACHED_SPEC (with verify flag)
                    │
                    └─ None of the above ────────────────────────► BROWSER_HAR + needs_fingerprint
```

### Strategies

| Strategy | When used | Browser? | AI? |
|---|---|---|---|
| `CACHED_SPEC` | Store has a promoted spec for this domain | Depends on spec | No |
| `DIRECT_JSON_API` | Known ATS with public API (Greenhouse, Lever, Ashby) | No | No |
| `BROWSER_HTML` | Known ATS but no API (NEOGOV, Workday, iCIMS) | Yes | Yes |
| `BROWSER_HAR` | Completely unknown source | Yes | Yes (fingerprint only) |

### Why this ordering matters

The current system always opens a browser. This stage exists so that for known API-backed platforms, we never open a browser at all. Greenhouse has a fully public JSON API. Lever has one. Ashby has one. If we know we're looking at one of those, a direct HTTP fetch is sub-second, deterministic, and uses zero AI tokens.

---

## Stage 2 — Acquirer

**Job:** Get raw data in the format appropriate for the classified strategy.  
**Input:** URL + Classification  
**Output:** A normalized `RawPageData` object regardless of acquisition path

```python
# All paths return the same shape — the extractor doesn't know how data was acquired

class RawPageData:
    source_url:          str
    final_url:           str
    title:               str | None
    text:                str | None          # innerText for HTML paths
    container_html:      str | None          # Structured DOM for known card patterns
    links:               list[dict]
    json_body:           dict | None         # Populated for API paths
    har_entries:         list[dict] | None   # Populated for BROWSER_HAR path
    dom_signals:         dict | None         # Scripts, iframes, meta tags
    jobs_count_hint:     int | None          # "23 open positions" extracted from page
    discovered_spec:     dict | None         # AI fingerprint result, if run
    data_type:           str                 # "json", "html", "unknown"
    already_retried:     bool
    pages_scraped:       int
```

### The key change from current code

HAR capture is not a fallback triggered after a failed extraction. It is a **first-class acquisition path** selected at classification time for unknown sources. This means:

- Unknown source → browser renders once, HAR captured in the same pass
- No second browser launch
- The fingerprinter gets HAR data from the very first request

For known API platforms, the browser is never launched at all.

### DOM extraction improvement

The current code sends `innerText` to the AI. This strips all structure. The acquirer should also extract the outer HTML of repeating job card elements — this gives the AI dramatically better signal about which fields belong to which job.

```
innerText:  "Software Engineer  Seattle, WA  Full Time  Apply"
outerHTML:  <div class="job-card">
              <h3 class="title">Software Engineer</h3>
              <span class="location">Seattle, WA</span>
              <span class="type">Full Time</span>
              <a href="/jobs/123">Apply</a>
            </div>
```

The AI can make far fewer mistakes with the second format. Confidence scores improve significantly.

---

## Stage 3 — Extractor

**Job:** Turn `RawPageData` into a list of structured `JobListing` objects.  
**Input:** `RawPageData` + Classification  
**Output:** `list[JobListing]`

### Three extraction paths

**Path A — Deterministic parser (known ATS with JSON API)**

No AI. The JSON response from Greenhouse, Lever, Ashby etc. has a known schema. A small parser file per platform handles the mapping. Zero hallucination risk, zero token cost.

```
Greenhouse JSON → greenhouse.py parser → list[JobListing]
```

**Path B — AI extraction from JSON (discovered API)**

When the HAR reveals a JSON API we didn't previously know about. We pass the JSON body to the AI with a tighter prompt since we know it's structured data, not prose.

**Path C — AI extraction from HTML**

The general case. Pass `container_html` (primary) + `text` (fallback) + `links` to the AI with a prompt that includes:
- ATS name and platform hints (if known)
- Jobs count hint from the page
- Explicit null rules to reduce hallucination
- The final URL for `source_url` attribution

### Prompt quality matters more than model quality

The prompt should tell the AI:
1. What platform it is looking at and what fields that platform always has
2. How many jobs to expect (cross-validation)
3. What *not* to invent (explicit null rules for salary, dates, etc.)
4. Where to find URLs (from the links array, not constructed)

A focused, platform-aware prompt on a smaller model outperforms a generic prompt on the best available model. The prompts live in `ai/prompts.py` — one function per extraction context, not inline strings scattered through the codebase.

---

## Stage 4 — Validator

**Job:** Cross-check extraction results, trigger retry if weak, return final result.  
**Input:** `list[JobListing]` + `RawPageData` + Classification  
**Output:** `ValidationResult`

### Checks performed

```
1. Count check      — did we find ~as many jobs as the page claims?
                      if page says "47 open positions" and we have 8, something is wrong

2. Confidence check — average confidence across all extracted jobs
                      below 60 → retry with expanded context

3. URL check        — are job_url values real absolute URLs from the links array?
                      relative or constructed URLs → flag for review

4. Dedup check      — same title + same location appearing from multiple pages?
                      deduplicate before returning

5. Empty result     — zero jobs found?
                      if BROWSER_HTML strategy was used, escalate to BROWSER_HAR
                      and re-run the full pipeline (one escalation max)
```

### Retry logic

The retry prompt is different from the initial prompt. It tells the AI explicitly what was weak about the first pass:

```
"First extraction found 3 jobs, but the page indicates ~24 are listed.
 Re-examine the container HTML below with special attention to
 hidden sections, collapsed accordions, and paginated content."
```

This is more effective than simply running the same prompt again.

---

## The Spec Store — the system's memory

This is what makes the system self-improving. Every successful extraction stores knowledge that future requests can use. The store is a SQLite database with a simple schema.

### Schema

```sql
CREATE TABLE specs (
    id              INTEGER PRIMARY KEY,
    ats_name        TEXT,
    domain_pattern  TEXT UNIQUE,
    spec            JSON NOT NULL,
    confidence      REAL DEFAULT 50,
    use_count       INTEGER DEFAULT 0,
    fail_count      INTEGER DEFAULT 0,
    promoted        BOOLEAN DEFAULT 0,
    last_used       TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

### Domain patterns

The key insight: for multi-tenant ATS platforms, a single pattern covers every employer on that platform.

| First URL seen | Pattern stored | Future URLs covered |
|---|---|---|
| `acme.greenhouse.io` | `%.greenhouse.io` | Every Greenhouse customer |
| `lever.co/widgetco` | `%.lever.co` | Every Lever customer |
| `jobs.acmecorp.com` | `jobs.acmecorp.com` | That one employer only |

This means discovering Greenhouse once covers thousands of employers. The AI fingerprinting cost amortizes across every company using that ATS.

### Confidence lifecycle

```
New spec discovered       → confidence = 70, promoted = false
Each successful use       → confidence += 2  (capped at 99)
5 uses + confidence ≥ 80  → promoted = true  (skip verification)
Each failure              → confidence -= 15, promoted = false
confidence drops below 20 → spec deleted, next request re-fingerprints
```

### What "promoted" means in practice

A promoted spec means the pipeline skips signal scanning and goes directly to the acquisition strategy stored in the spec. For Greenhouse, after five successful extractions, every future Greenhouse URL hits the JSON API directly — no browser, no AI, no scanning.

---

## The Auto-Learning ATS System

This is how the registry stays hands-off.

### Signal Scanner (zero AI, ~10ms)

Checks the rendered page for known ATS indicators before any AI call:

- Script `src` attributes (most ATS platforms inject scripts from their own domain)
- Iframe `src` attributes (some embed via iframe)
- URL patterns (slug extraction)
- HTML snippet for class/id patterns

Known platforms in the initial signal list: Greenhouse, Lever, Ashby, Workday, NEOGOV/SchoolJobs, iCIMS, BambooHR, SmartRecruiters, Taleo, SuccessFactors, Jobvite, Jazz/ApplyToJob.

If any match is found, a slug is extracted from the URL and an API URL is constructed from the template. No AI involved.

### AI Fingerprinter (once per new platform)

When signal scanning finds nothing and the store is empty for this domain, the AI fingerprinter runs. This is a one-time cost.

The fingerprinter prompt asks the AI to think **generically**, not specifically. The goal is not "how do I scrape this one URL" but "what platform is this and how does that platform work in general." The resulting spec uses `{slug}` as a placeholder so it applies to any employer on the same platform.

The prompt provides:
- The source URL
- DOM signals (scripts, iframes, meta tags)
- Filtered HAR entries (XHR/fetch requests and their response bodies)

The AI returns a structured spec with: platform name (if recognized), API URL template, method, headers, payload pattern, pagination type, and confidence score.

### Self-healing

When a cached spec produces zero jobs or the validator detects a confidence collapse:

1. `record_failure()` demotes the spec (confidence -= 15, promoted = false)
2. If confidence drops below threshold, spec is deleted
3. Next request for that domain treats it as a fresh unknown
4. Re-fingerprinting runs and a new spec is stored

This handles ATS migrations (employer moves from Lever to Workday), API endpoint changes, and platform updates without any manual intervention.

---

## API Layer

The external interface is a single endpoint. The caller provides a URL and gets back jobs. All strategy decisions are internal.

```
POST /jobs          — primary endpoint, returns structured jobs
GET  /specs         — inspect what the store has learned (debug/admin)
GET  /specs/{domain}— inspect a specific domain's stored spec
DELETE /specs/{domain} — force re-fingerprint on next request
GET  /health        — ok
```

The `/specs` endpoints are for visibility and debugging, not for the caller to manage. The store manages itself.

---

## Data Flow — Full Example

### Known ATS (Greenhouse), first time seen

```
POST /jobs { url: "acme.greenhouse.io/careers" }
  │
  ├─ Classifier
  │    ├─ Store lookup: empty
  │    └─ Signal scan: script src contains "greenhouse.io"
  │         slug extracted: "acme"
  │         api_url built: "boards-api.greenhouse.io/v1/boards/acme/jobs"
  │         → Strategy: DIRECT_JSON_API
  │
  ├─ Acquirer
  │    └─ HTTP GET to Greenhouse API (no browser)
  │         → RawPageData { json_body: { jobs: [...] }, data_type: "json" }
  │
  ├─ Extractor
  │    └─ greenhouse.py deterministic parser
  │         → list[JobListing] (no AI)
  │
  ├─ Validator
  │    ├─ Count check: 12 jobs found, page hint N/A — ok
  │    └─ Confidence: N/A for deterministic parse — pass
  │
  ├─ Store: save spec for %.greenhouse.io, confidence=95
  │
  └─ Return: 12 jobs, strategy="direct_json_api", ats="greenhouse"
```

### Unknown source, first time seen

```
POST /jobs { url: "careers.obscurecompany.com" }
  │
  ├─ Classifier
  │    ├─ Store lookup: empty
  │    ├─ Signal scan: no matches
  │    └─ → Strategy: BROWSER_HAR + needs_fingerprint=true
  │
  ├─ Acquirer
  │    └─ Browser renders page, HAR captured in same pass
  │         Scroll, interact, collect paginated pages
  │         → RawPageData { text, container_html, links, har_entries, dom_signals }
  │
  ├─ AI Fingerprinter (runs once because needs_fingerprint=true)
  │    └─ Analyzes dom_signals + har_entries
  │         Identifies: custom iCIMS deployment
  │         Generates spec with {slug} template
  │         → discovered_spec saved to store, confidence=70
  │
  ├─ Extractor
  │    └─ AI extraction from container_html + text
  │         Platform hint in prompt: "iCIMS ATS"
  │         → list[JobListing]
  │
  ├─ Validator
  │    ├─ Count check: page says "8 openings", found 8 — pass
  │    └─ Avg confidence: 82 — pass
  │
  ├─ Store: record_success(), confidence bumped to 72
  │
  └─ Return: 8 jobs, strategy="browser_har", ats="icims"

--- Next request to any *.icims.com domain ---

  ├─ Classifier
  │    └─ Store lookup: %.icims.com match, confidence=84
  │         → Strategy: CACHED_SPEC (no browser, no fingerprinting)
  │
  └─ ... (faster, cheaper, no re-discovery)
```

---

## What Changes, What Stays

| Current | Redesigned | Reason |
|---|---|---|
| One `main.py` | Four stage modules + support packages | Each concern independently testable and replaceable |
| HAR captured after failed extraction (second browser pass) | HAR captured in same browser pass as page render | Eliminates wasted browser launches |
| No memory between requests | Spec Store with domain pattern matching | ATS discovered once, reused forever |
| AI on every request | AI skipped for known API platforms | Greenhouse/Lever/Ashby = zero AI tokens |
| Generic extraction prompt | Platform-aware prompt with count hint | Higher confidence scores, fewer hallucinations |
| Manual ATS knowledge | Signal scanner + AI fingerprinter + store | System teaches itself |
| Single endpoint doing everything | `classify → acquire → extract → validate` | Failures cascade within stages, not across the whole system |
| Pagination scattered through main flow | `browser/paginator.py` — one place | URL-param, click-based, and scroll strategies in one module |
| Schemas inline in file | `models.py` | Single source of truth for all data shapes |

---

## Implementation Priority

Not everything needs to be built at once. Ordered by impact:

**Phase 1 — The foundation (biggest immediate wins)**
1. Extract `models.py` — clean up the schema definitions first
2. Build `spec_store.py` — even a basic version immediately helps
3. Build `signal_scanner.py` — covers Greenhouse/Lever/Ashby with zero AI cost
4. Implement deterministic parsers for Greenhouse and Lever

After Phase 1: the most common job boards in tech hit a direct JSON API. AI never runs for them.

**Phase 2 — The pipeline**
5. Split into `classifier.py`, `acquirer.py`, `extractor.py`, `validator.py`
6. Move all prompts to `ai/prompts.py`
7. Move all Playwright code to `browser/`

After Phase 2: the codebase is navigable. New features go to the right file.

**Phase 3 — Self-learning**
8. Build the AI fingerprinter
9. Wire confidence tracking and auto-promotion
10. Add self-healing (demote on failure, re-fingerprint)

After Phase 3: the system is fully hands-off. New ATS platforms are discovered and stored automatically.

**Phase 4 — Visibility**
11. Add `/specs` admin endpoints
12. Add `extraction_meta` to every response (strategy used, ATS detected, confidence, retried)
13. Logging that shows the pipeline path taken for each request

---

## Guiding Principles

**Deterministic before AI.** If the data can be parsed without the AI, parse it without the AI. AI is for unstructured or unknown data, not for fields that are already in JSON.

**One browser pass maximum.** The browser is the most expensive part of the system. Every design decision should aim to reduce browser launches, not add them.

**Memory compounds.** The spec store is what makes the system more valuable over time. A scraper that starts from zero on every request is a tool. A scraper that learns is infrastructure.

**Caller knows nothing about strategy.** The single `/jobs` endpoint hides all complexity. Whether the result came from a direct API call or a full browser render with HAR analysis and AI fallback is an implementation detail the caller should never need to know about or control.

**Failures should teach, not just fail.** When extraction fails, `record_failure()` demotes the spec and triggers re-fingerprinting on the next request. The system corrects itself rather than requiring a developer to intervene.
