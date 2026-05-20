"""Stage 3: extract normalized job records from raw data."""

from scraper.ats.parsers import parse_ashby_jobs, parse_greenhouse_jobs, parse_lever_jobs


async def run(stage_input: dict) -> dict:
    """Extract jobs from raw data."""
    raw_data = stage_input["raw_data"]
    classification = stage_input.get("classification", {})
    ats = classification.get("ats")

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

    return {**stage_input, "jobs": jobs}
