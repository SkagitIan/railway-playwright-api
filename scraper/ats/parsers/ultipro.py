"""Deterministic parser for UltiPro/UKG recruiting JSON payloads."""

from __future__ import annotations


def _blank_compensation() -> dict:
    return {"raw": None, "currency": None, "min_amount": None, "max_amount": None, "period": None}


def _location(location: dict | None) -> dict:
    if not location:
        return {"raw": None, "city": None, "region": None, "country": None}
    address = location.get("Address") or {}
    city = address.get("City")
    state = address.get("State") or {}
    country = address.get("Country") or {}
    raw = location.get("LocalizedName") or ", ".join(part for part in [city, state.get("Code")] if part) or None
    return {
        "raw": raw,
        "city": city,
        "region": state.get("Code"),
        "country": country.get("Code"),
    }


def _workplace_type(value: int | None) -> str:
    return {1: "onsite", 2: "hybrid", 3: "remote"}.get(value, "unspecified")


def _detail_url(source_url: str | None, job_id: str | None) -> str | None:
    if not source_url or not job_id:
        return None
    base = source_url.split("?", 1)[0].rstrip("/")
    if base.endswith("/JobBoardView/LoadSearchResults"):
        base = base[: -len("/JobBoardView/LoadSearchResults")]
    return f"{base}/OpportunityDetail?opportunityId={job_id}"


def parse_jobs(payload: dict, source_url: str | None = None) -> list[dict]:
    jobs = []
    for item in payload.get("opportunities") or []:
        locations = item.get("Locations") or []
        primary_location = _location(locations[0] if locations else None)
        jobs.append(
            {
                "title": item.get("Title"),
                "company_name": None,
                "department": item.get("JobCategoryName"),
                "employment_type": "full_time" if item.get("FullTime") is True else None,
                "workplace_type": _workplace_type(item.get("JobLocationType")),
                "location": primary_location,
                "additional_locations": [_location(location) for location in locations[1:]],
                "job_url": _detail_url(source_url, item.get("Id")),
                "apply_url": None,
                "posted_date": item.get("PostedDate"),
                "closing_date": None,
                "compensation": _blank_compensation(),
                "experience_level": "unspecified",
                "description": item.get("BriefDescription"),
                "responsibilities": [],
                "qualifications": [],
                "benefits": [],
                "skills": [],
                "source_link_text": item.get("Title"),
                "evidence": item.get("BriefDescription"),
                "confidence": 95,
                "requisition_number": item.get("RequisitionNumber"),
            }
        )
    return jobs
