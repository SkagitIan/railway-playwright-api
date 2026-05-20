"""Deterministic parser for Greenhouse JSON payloads."""


def parse_jobs(payload: dict) -> list[dict]:
    jobs = payload.get("jobs") or []
    out = []
    for job in jobs:
        out.append(
            {
                "title": job.get("title"),
                "location": (job.get("location") or {}).get("name"),
                "job_url": job.get("absolute_url"),
                "department": (job.get("departments") or [{}])[0].get("name"),
                "employment_type": None,
            }
        )
    return out
