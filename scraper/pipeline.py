"""Simple classify → acquire → extract → validate pipeline."""

import time
import uuid

from scraper.config import PIPELINE_MAX_RETRIES
from scraper.stages import acquirer, classifier, extractor, validator


def _log(stage: str, strategy: str, url: str, domain: str, started: float, success: bool, request_id: str, reason: str | None = None) -> None:
    duration_ms = int((time.perf_counter() - started) * 1000)
    payload = {
        "request_id": request_id,
        "url": url,
        "domain": domain,
        "stage": stage,
        "strategy": strategy,
        "duration_ms": duration_ms,
        "success": success,
    }
    if reason:
        payload["reason"] = reason
    print(payload)


async def run(stage_input: dict) -> dict:
    """Run all pipeline stages in sequence."""
    request_id = stage_input.get("request_id") or str(uuid.uuid4())
    url = stage_input["url"]
    domain = stage_input.get("domain", "")

    classify_start = time.perf_counter()
    classified = await classifier.run({**stage_input, "request_id": request_id})
    strategy = classified["classification"].get("strategy", "UNKNOWN")
    _log("classifier", strategy, url, domain, classify_start, True, request_id)

    last_result = classified
    for attempt in range(PIPELINE_MAX_RETRIES + 1):
        acquire_start = time.perf_counter()
        acquired = await acquirer.run({**last_result, "attempt": attempt})
        _log("acquirer", acquired.get("acquisition_strategy", strategy), url, domain, acquire_start, True, request_id)

        extract_start = time.perf_counter()
        extracted = await extractor.run(acquired)
        _log("extractor", acquired.get("acquisition_strategy", strategy), url, domain, extract_start, len(extracted.get("jobs", [])) > 0, request_id)

        validate_start = time.perf_counter()
        validated = await validator.run(extracted)
        success = validated.get("validation", {}).get("success", False)
        _log("validator", acquired.get("acquisition_strategy", strategy), url, domain, validate_start, success, request_id)
        if success:
            return validated
        last_result = {**validated, "fallback_reason": validated.get("validation", {}).get("notes", "retry")}

    return {**last_result, "request_id": request_id}
