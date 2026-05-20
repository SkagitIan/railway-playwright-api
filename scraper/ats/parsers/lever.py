"""Deterministic parser for Lever JSON payloads."""


def parse_jobs(payload: list[dict]) -> list[dict]:
    out = []
    for job in payload or []:
        out.append(
            {
                "title": job.get("text"),
                "location": (job.get("categories") or {}).get("location"),
                "job_url": job.get("hostedUrl") or job.get("applyUrl"),
                "department": (job.get("categories") or {}).get("team"),
                "employment_type": (job.get("categories") or {}).get("commitment"),
            }
        )
    return out
