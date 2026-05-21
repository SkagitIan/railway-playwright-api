"""Simple classify → acquire → extract → validate pipeline."""

import time
import uuid

from scraper.config import PIPELINE_MAX_RETRIES
from scraper.ats.spec_store import save_observation
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


def _observation_spec(result: dict) -> dict | None:
    if result.get("network_fallback_spec"):
        return result["network_fallback_spec"]

    raw_data = result.get("raw_data", {})
    api_target_url = raw_data.get("api_target_url")
    if api_target_url:
        return {
            "ats": result.get("classification", {}).get("ats"),
            "data_delivery_type": "json_api",
            "requires_browser": False,
            "api_target_url": api_target_url,
            "browser_target_url": None,
            "method": "GET",
            "required_headers": {
                "accept": "application/json",
                "content_type": None,
                "authorization": None,
                "user_agent": None,
                "referer": None,
            },
            "payload": None,
            "json_path_to_listings": "jobs",
            "explanation": "Direct ATS JSON API",
        }
    return None


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
        spec = _observation_spec(validated)
        if spec:
            save_observation(validated.get("domain", domain), spec, success=success, latency=None, error=None if success else validated.get("validation", {}).get("notes"))
        if success:
            return validated
        last_result = {**validated, "fallback_reason": validated.get("validation", {}).get("notes", "retry")}

    return {**last_result, "request_id": request_id}
