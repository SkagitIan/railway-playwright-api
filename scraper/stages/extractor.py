"""Stage 3: extract normalized job records from raw data."""

from scraper.ats.parsers import parse_ashby_jobs, parse_greenhouse_jobs, parse_lever_jobs
from scraper.ai.extraction import build_fallback_spec_from_logs, default_scraper_spec, extract_jobs_from_page_data
from scraper.config import AI_MAX_LINKS, AI_MAX_TEXT_CHARS


async def run(stage_input: dict) -> dict:
    """Extract jobs from raw data."""
    raw_data = stage_input["raw_data"]
    classification = stage_input.get("classification", {})
    ats = classification.get("ats")

    raw_data["text"] = (raw_data.get("text") or "")[:AI_MAX_TEXT_CHARS]
    raw_data["links"] = (raw_data.get("links") or [])[:AI_MAX_LINKS]

    jobs: list[dict] = []
    json_body = raw_data.get("json_body")

    if ats == "greenhouse" and isinstance(json_body, dict):
        jobs = parse_greenhouse_jobs(json_body)
    elif ats == "lever" and isinstance(json_body, list):
        jobs = parse_lever_jobs(json_body)
    elif ats == "ashby" and isinstance(json_body, dict):
        jobs = parse_ashby_jobs(json_body)
    elif isinstance(json_body, dict):
        jobs = json_body.get("jobs", []) or []

    ai_result = None
    fallback_spec = None
    if not jobs and raw_data.get("data_type") == "html":
        page_data = {
            "final_url": raw_data.get("final_url") or raw_data.get("source_url"),
            "title": raw_data.get("title"),
            "text": raw_data.get("text") or "",
            "links": raw_data.get("links") or [],
        }
        ai_result = await extract_jobs_from_page_data(page_data)
        jobs = ai_result.get("jobs") or []
        if not jobs:
            har_entries = raw_data.get("har_entries") or []
            if har_entries:
                fallback_spec = await build_fallback_spec_from_logs(raw_data.get("source_url"), har_entries)
            else:
                fallback_spec = default_scraper_spec("No HAR logs captured during v2 extraction.")

    token_usage = {
        "input_chars": len(raw_data.get("text") or ""),
        "link_count": len(raw_data.get("links") or []),
    }
    result = {**stage_input, "jobs": jobs, "token_usage": token_usage}
    if ai_result:
        result["ai_result"] = ai_result
    if fallback_spec:
        result["network_fallback_spec"] = fallback_spec
    return result
