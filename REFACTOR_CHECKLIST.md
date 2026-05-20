# Refactor Checklist: Powerful Scraper Tool

This checklist is designed for a clean handoff to Codex and follows a simple principle:

> simple code is better than complex code.

## 0) Definition of Done

- [x] Existing endpoints still work (or are intentionally replaced with documented v2 endpoints).
- [ ] New architecture supports: classify → acquire → extract → validate.
- [ ] Known ATS sources run without AI when possible.
- [ ] Unknown sources fall back safely to browser + AI path.
- [x] Tests pass and README explains how to run locally.

## 1) Baseline & Safety

- [x] Create a branch: `refactor/pipeline-v2`.
- [x] Capture baseline behavior on 3–5 real URLs (save JSON outputs).
- [x] Add/confirm smoke tests for:
  - [x] `/extract-page-text`
  - [x] `/extract-links`
  - [x] `/extract-jobs-ai`
  - [x] `/analyze-network-fallback`
- [x] Add one regression fixture for a known ATS site and one unknown site.

**Rule:** Don’t refactor without a baseline snapshot.

## 2) File/Module Restructure (No Behavior Change First)

- [x] Create modules:
  - [x] `scraper/config.py`
  - [x] `scraper/models.py`
  - [x] `scraper/schemas.py`
  - [x] `scraper/api.py`
  - [x] `scraper/pipeline.py`
- [x] Move constants, schemas, and Pydantic models out of `main.py`.
- [ ] Keep route responses identical during this step.

**Rule:** Move first, improve second.

## 3) Implement 4-Stage Pipeline

- [x] Add stage modules:
  - [x] `scraper/stages/classifier.py`
  - [x] `scraper/stages/acquirer.py`
  - [x] `scraper/stages/extractor.py`
  - [x] `scraper/stages/validator.py`
- [x] Each stage exposes one plain async function: `run(input) -> output`.
- [x] No class hierarchy unless clearly necessary.

**Rule:** Prefer simple function composition over framework-heavy abstractions.

## 4) Browser Isolation

- [x] Extract Playwright code into:
  - [x] `scraper/browser/context.py`
  - [x] `scraper/browser/paginator.py`
  - [x] `scraper/browser/har.py`
- [x] Keep one place responsible for page interaction (scroll/click/pagination).
- [x] Add timeout defaults in one config file only.

## 5) AI Isolation

- [x] Add:
  - [x] `scraper/ai/client.py` (OpenAI calls + timeout/refusal handling)
  - [x] `scraper/ai/prompts.py` (all prompt templates)
  - [x] `scraper/ai/parsers.py` (JSON parsing/validation utilities)
- [x] Remove inline prompt strings from endpoints and business logic.

**Rule:** Prompt text belongs in one file, not scattered.

## 6) ATS Fast-Path (Deterministic Before AI)

- [x] Add scanner: `scraper/ats/signal_scanner.py`.
- [x] Implement parsers:
  - [x] `scraper/ats/parsers/greenhouse.py`
  - [x] `scraper/ats/parsers/lever.py`
  - [x] `scraper/ats/parsers/ashby.py` (optional phase 2)
- [x] If ATS API detected, skip AI extraction path.
- [x] Add unit tests for each parser with sample payloads.

## 7) Spec Store (Self-Learning, Simple SQLite)

- [x] Add `scraper/ats/spec_store.py` with:
  - [x] `get_promoted_spec(domain)`
  - [x] `save_observation(domain, spec, success, latency, error)`
  - [x] `promote_spec(...)`
  - [x] `demote_spec(...)`
- [x] Start with 2 tables only: `specs`, `observations`.
- [x] Add one migration/init script.

**Rule:** Minimal schema now; evolve later.

## 8) Retry & Fallback Policy

- [x] Implement clear order:
  1. ATS deterministic route
  2. promoted spec replay
  3. browser render + extraction
  4. HAR analysis + AI spec generation
- [x] Add max retry count (small, e.g., 2).
- [x] Return explicit reason for fallback in output/debug logs.

## 9) Observability (Must-Have)

- [x] Add structured logs with fields:
  - [x] `url`
  - [x] `domain`
  - [x] `stage`
  - [x] `strategy`
  - [x] `duration_ms`
  - [x] `success`
- [x] Add request id/correlation id.
- [x] Log token usage on AI paths (if available).

## 10) Performance/Cost Guardrails

- [x] Hard cap page text length sent to AI.
- [x] Hard cap number of links included in AI prompt.
- [x] Add concurrency limits for Playwright contexts.
- [x] Cache successful specs per domain (short TTL).

## 11) API Compatibility & Versioning

- [ ] Keep existing endpoints stable OR introduce `/v2/*` equivalents.
- [ ] Document any response shape changes explicitly.
- [ ] Add deprecation timeline if v1 is retained temporarily.

## 12) Test Matrix (Industry-Style Minimum)

- [ ] Unit tests: classifier, ATS parser, validator.
- [ ] Integration tests: one full pipeline success path.
- [ ] Failure tests: timeout, blocked page, malformed JSON.
- [ ] Contract tests: schema compliance for job output + spec output.
- [ ] Load test (light): N concurrent URLs to verify no browser leak.

## 13) PR Requirements for Codex

- [ ] Small PRs (300–600 LOC net preferred).
- [ ] Each PR has:
  - [ ] What changed
  - [ ] Why
  - [ ] Risk
  - [ ] Rollback plan
  - [ ] Test evidence
- [ ] Feature-flag rollout:
  - [ ] `PIPELINE_V2=false` default first
  - [ ] enable in staging
  - [ ] then prod

## 14) Suggested Execution Order

1. Baseline tests + fixtures
2. Move models/config/schemas
3. Extract browser and AI modules
4. Wire pipeline skeleton
5. Add ATS deterministic parsers
6. Add spec store + fallback routing
7. Add logs/metrics + docs
8. Enable feature flag and validate parity

## Quick Do / Don’t Card

### Do

- Keep functions short and single-purpose.
- Prefer plain dict/dataclass over deep OOP.
- Add tests with each module split.
- Keep fallback behavior explicit and observable.

### Don’t

- Don’t rewrite everything in one PR.
- Don’t add new abstractions "just in case."
- Don’t couple FastAPI handlers to Playwright/OpenAI internals.
- Don’t make AI the first path when deterministic path exists.
