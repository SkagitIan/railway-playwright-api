"""Stage 4: validate extraction output."""


def _dedupe_jobs(jobs: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for job in jobs:
        key = (
            job.get("title"),
            str(job.get("location")),
            job.get("job_url"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


async def run(stage_input: dict) -> dict:
    """Validate extracted jobs with a lightweight, explicit result."""
    jobs = _dedupe_jobs(stage_input.get("jobs", []))
    success = len(jobs) > 0

    fallback_reason = stage_input.get("fallback_reason")
    if success:
        notes = "ok"
    else:
        notes = fallback_reason if fallback_reason and fallback_reason != "none" else "No jobs extracted yet"
    return {
        **stage_input,
        "jobs": jobs,
        "validation": {
            "success": success,
            "job_count": len(jobs),
            "notes": notes,
        },
        "debug": {
            "fallback_reason": notes if not success else stage_input.get("fallback_reason", "none"),
            "request_id": stage_input.get("request_id"),
            "token_usage": stage_input.get("token_usage", {}),
        },
    }
