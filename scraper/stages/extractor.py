"""Stage 3: extract normalized job records from raw data."""


async def run(stage_input: dict) -> dict:
    """Extract jobs from raw data.

    Placeholder implementation for refactor task 3.
    """
    raw_data = stage_input["raw_data"]

    jobs: list[dict] = []
    if raw_data.get("json_body") and isinstance(raw_data["json_body"], dict):
        jobs = raw_data["json_body"].get("jobs", []) or []

    return {**stage_input, "jobs": jobs}
