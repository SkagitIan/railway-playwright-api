"""Deterministic extraction for rendered job-board pages."""

from __future__ import annotations

import re
from urllib.parse import urlparse


NAV_TEXT = {
    "home",
    "careers",
    "jobs",
    "job openings",
    "open positions",
    "apply",
    "view job",
    "view role",
    "learn more",
    "privacy policy",
    "cookie notice",
}


def _blank_location(raw: str | None = None) -> dict:
    return {"raw": raw, "city": None, "region": None, "country": None}


def _blank_compensation() -> dict:
    return {"raw": None, "currency": None, "min_amount": None, "max_amount": None, "period": None}


def _is_job_href(href: str) -> bool:
    parsed = urlparse(href)
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    if "rippling.com" in host and "/jobs" in path:
        return True
    return bool(re.search(r"/(?:job|jobs|positions|openings)(?:/|$)", path))


def _clean_title(text: str) -> str:
    title = re.sub(r"\s+", " ", text or "").strip()
    title = re.sub(r"\s+(apply|view job|view role)$", "", title, flags=re.I).strip()
    return title


def _looks_like_title(title: str) -> bool:
    if not title or len(title) < 3 or len(title) > 120:
        return False
    lowered = title.lower()
    if lowered in NAV_TEXT:
        return False
    if any(x in lowered for x in ["cookie", "privacy", "terms", "linkedin", "youtube"]):
        return False
    if not re.search(r"[A-Za-z]", title):
        return False
    return True


def _extract_location_from_evidence(evidence: str) -> str | None:
    lines = [line.strip() for line in evidence.splitlines() if line.strip()]
    for line in lines[1:5]:
        if re.search(r"\b(remote|hybrid|onsite)\b", line, re.I):
            return line
        if re.search(r"\b[A-Z][a-zA-Z .'-]+,\s*[A-Z]{2}\b", line):
            return line
    return None


def _evidence_for_title(text: str, title: str) -> str:
    if not text or title not in text:
        return title
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if title in line:
            return "\n".join(lines[idx : idx + 5]).strip()
    return title


def _job(title: str, href: str | None, evidence: str, confidence: int) -> dict:
    location = _extract_location_from_evidence(evidence)
    return {
        "title": title,
        "company_name": None,
        "department": None,
        "employment_type": None,
        "workplace_type": "unspecified",
        "location": _blank_location(location),
        "additional_locations": [],
        "job_url": href,
        "apply_url": None,
        "posted_date": None,
        "closing_date": None,
        "compensation": _blank_compensation(),
        "experience_level": "unspecified",
        "description": None,
        "responsibilities": [],
        "qualifications": [],
        "benefits": [],
        "skills": [],
        "source_link_text": title if href else None,
        "evidence": evidence,
        "confidence": confidence,
    }


def extract_jobs_from_rendered_board(raw_data: dict, classification: dict | None = None) -> list[dict]:
    """Extract likely jobs from rendered job-board text/links without AI."""
    text = raw_data.get("text") or ""
    jobs = []
    seen = set()

    for link in raw_data.get("links") or []:
        href = link.get("href")
        title = _clean_title(link.get("text") or "")
        if not href or not _is_job_href(href) or not _looks_like_title(title):
            continue
        key = (title.lower(), href)
        if key in seen:
            continue
        seen.add(key)
        evidence = _evidence_for_title(text, title)
        jobs.append(_job(title, href, evidence, 90))

    return jobs
