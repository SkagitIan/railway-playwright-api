"""Deterministic parser for Ashby JSON payloads (phase-2 optional)."""


def parse_jobs(payload: dict) -> list[dict]:
    postings = payload.get("jobs") or payload.get("jobPostings") or []
    out = []
    for job in postings:
        out.append(
            {
                "title": job.get("title"),
                "location": (job.get("location") or {}).get("name") if isinstance(job.get("location"), dict) else job.get("location"),
                "job_url": job.get("jobUrl") or job.get("url"),
                "department": job.get("departmentName") or (job.get("department") or {}).get("name") if isinstance(job.get("department"), dict) else job.get("department"),
                "employment_type": job.get("employmentType"),
            }
        )
    return out
