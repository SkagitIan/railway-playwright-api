"""Stage 3: extract normalized job records from raw data."""

from scraper.ats.parsers import parse_ashby_jobs, parse_greenhouse_jobs, parse_lever_jobs
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

    token_usage = {
        "input_chars": len(raw_data.get("text") or ""),
        "link_count": len(raw_data.get("links") or []),
    }
    return {**stage_input, "jobs": jobs, "token_usage": token_usage}
