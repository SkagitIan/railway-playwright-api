"""Stage 4: validate extraction output."""


async def run(stage_input: dict) -> dict:
    """Validate extracted jobs with a lightweight, explicit result."""
    jobs = stage_input.get("jobs", [])
    success = len(jobs) > 0

    return {
        **stage_input,
        "validation": {
            "success": success,
            "job_count": len(jobs),
            "notes": "No jobs extracted yet" if not success else "ok",
        },
    }
