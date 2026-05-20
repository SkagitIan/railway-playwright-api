"""Stage 2: acquire raw data for downstream extraction."""

import asyncio
import time

from scraper.config import BROWSER_MAX_CONCURRENCY, SPEC_CACHE_TTL_SECONDS

_BROWSER_SEMAPHORE = asyncio.Semaphore(BROWSER_MAX_CONCURRENCY)
_SPEC_CACHE: dict[str, tuple[float, dict]] = {}


async def run(stage_input: dict) -> dict:
    """Normalize raw acquisition output shape.

    This is intentionally simple while the pipeline modules are being split out.
    """
    classification = stage_input["classification"]
    domain = stage_input.get("domain", "")
    now = time.time()
    cached = _SPEC_CACHE.get(domain)
    if cached and (now - cached[0]) < SPEC_CACHE_TTL_SECONDS:
        return {**stage_input, "raw_data": cached[1], "acquisition_strategy": "spec_cache_ttl", "fallback_reason": "none"}

    strategy = classification.get("strategy", "BROWSER_RENDER")
    fallback_reason = stage_input.get("fallback_reason", "none")
    if strategy == "DIRECT_JSON_API":
        acquisition_strategy = "ats_deterministic"
    elif strategy == "PROMOTED_SPEC":
        acquisition_strategy = "promoted_spec_replay"
    elif strategy == "BROWSER_HAR":
        acquisition_strategy = "har_analysis_and_ai_spec"
    else:
        acquisition_strategy = "browser_render_and_extract"

    async with _BROWSER_SEMAPHORE:
        raw_data = {
            "source_url": stage_input["url"],
            "data_type": "json" if strategy == "DIRECT_JSON_API" else "html",
            "text": None,
            "container_html": None,
            "links": [],
            "json_body": None,
            "har_entries": [],
            "pages_scraped": 0,
            "fallback_reason": fallback_reason,
        }

    _SPEC_CACHE[domain] = (now, raw_data)
    return {**stage_input, "raw_data": raw_data, "acquisition_strategy": acquisition_strategy}
