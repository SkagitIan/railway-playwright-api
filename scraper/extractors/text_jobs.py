"""Deterministic extraction from rendered tabular job-listing text."""

from __future__ import annotations

import re


STOP_PREFIXES = (" Prev", "Prev", "1", "2", "3", "4", "Next", "Showing items", "CAREER OPPORTUNITIES")


def _job_links(links: list[dict]) -> dict[str, str]:
    out = {}
    for link in links or []:
        text = (link.get("text") or "").strip()
        href = link.get("href")
        if text and href and "/jobs/" in href:
            out[text] = href
    return out


def _employment_type(raw: str | None) -> str | None:
    value = (raw or "").lower()
    if "temporary" in value:
        return "temporary"
    if "part" in value:
        return "part_time"
    if "faculty" in value or "exempt" in value or "classified" in value:
        return "full_time"
    return None


def _compensation(raw: str | None) -> dict:
    text = raw or None
    min_amount = None
    max_amount = None
    if raw:
        amounts = [float(match.replace(",", "")) for match in re.findall(r"\$([0-9,]+(?:\.\d+)?)", raw)]
        if amounts:
            min_amount = amounts[0]
            max_amount = amounts[-1]
    period = None
    lowered = (raw or "").lower()
    if "hour" in lowered:
        period = "hourly"
    elif "month" in lowered:
        period = "monthly"
    elif "annual" in lowered or "year" in lowered:
        period = "yearly"
    return {"raw": text, "currency": "$" if raw and "$" in raw else None, "min_amount": min_amount, "max_amount": max_amount, "period": period}


def _location(raw: str | None) -> dict:
    text = raw or None
    city = None
    region = None
    country = None
    if raw:
        match = re.search(r"([^,\n]+),\s*([A-Z]{2})\b", raw)
        if match:
            city = match.group(1).strip()
            region = match.group(2)
            country = "US"
    return {"raw": text, "city": city, "region": region, "country": country}


def extract_jobs_from_text(raw_data: dict) -> list[dict]:
    text = raw_data.get("text") or ""
    links_by_title = _job_links(raw_data.get("links") or [])
    jobs = []
    seen = set()
    in_table = False

    for line in text.splitlines():
        row = line.strip()
        normalized = row.replace(" ", "")
        if normalized.startswith("JobTitle\tJobType\tDepartment\tLocation\tSalary\tClosing"):
            in_table = True
            continue
        if not in_table or not row:
            continue
        if any(row.startswith(prefix) for prefix in STOP_PREFIXES):
            in_table = False
            continue
        columns = row.split("\t")
        if len(columns) < 5:
            continue
        title, job_type, department, location, salary = [col.strip() for col in columns[:5]]
        closing = columns[5].strip() if len(columns) > 5 and columns[5].strip() else None
        job_url = links_by_title.get(title)
        key = (title, location, job_url)
        if key in seen:
            continue
        seen.add(key)
        jobs.append(
            {
                "title": title.removesuffix(" New").strip(),
                "company_name": None,
                "department": department or None,
                "employment_type": _employment_type(job_type),
                "workplace_type": "unspecified",
                "location": _location(location),
                "additional_locations": [],
                "job_url": job_url,
                "apply_url": None,
                "posted_date": None,
                "closing_date": closing,
                "compensation": _compensation(salary),
                "experience_level": "unspecified",
                "description": None,
                "responsibilities": [],
                "qualifications": [],
                "benefits": [],
                "skills": [],
                "source_link_text": title if job_url else None,
                "evidence": row,
                "confidence": 92,
            }
        )

    return jobs
