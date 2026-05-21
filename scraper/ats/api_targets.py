"""Direct JSON API target construction for known ATS platforms."""

from __future__ import annotations

import json
from urllib.parse import urlparse


def _first_path_part(url: str) -> str | None:
    parts = [part for part in urlparse(url).path.split("/") if part]
    return parts[0] if parts else None


def _path_parts(url: str) -> list[str]:
    return [part for part in urlparse(url).path.split("/") if part]


def _ultipro_payload(skip: int = 0, top: int = 100) -> str:
    return json.dumps(
        {
            "opportunitySearch": {
                "Top": top,
                "Skip": skip,
                "QueryString": "",
                "OrderBy": [
                    {
                        "Value": "postedDateDesc",
                        "PropertyName": "PostedDate",
                        "Ascending": False,
                    }
                ],
                "Filters": [
                    {"t": "TermsSearchFilterDto", "fieldName": 4, "extra": None, "values": []},
                    {"t": "TermsSearchFilterDto", "fieldName": 5, "extra": None, "values": []},
                    {"t": "TermsSearchFilterDto", "fieldName": 6, "extra": None, "values": []},
                    {"t": "TermsSearchFilterDto", "fieldName": 37, "extra": None, "values": []},
                ],
            },
            "matchCriteria": {
                "PreferredJobs": [],
                "Educations": [],
                "LicenseAndCertifications": [],
                "Skills": [],
                "hasNoLicenses": False,
                "SkippedSkills": [],
            },
        }
    )


def build_api_target(url: str, ats: str) -> dict | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    slug = _first_path_part(url)

    if ats == "greenhouse":
        board = None
        if host == "boards.greenhouse.io":
            board = slug
        elif host.endswith(".greenhouse.io"):
            board = host.split(".")[0]
        if board:
            return {
                "api_target_url": f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                "method": "GET",
                "headers": {"Accept": "application/json"},
                "payload": None,
            }

    if ats == "lever":
        company = None
        if host == "jobs.lever.co":
            company = slug
        elif host.endswith(".lever.co"):
            company = host.split(".")[0]
        if company:
            return {
                "api_target_url": f"https://api.lever.co/v0/postings/{company}?mode=json",
                "method": "GET",
                "headers": {"Accept": "application/json"},
                "payload": None,
            }

    if ats == "ashby":
        board = None
        if host == "jobs.ashbyhq.com":
            board = slug
        elif host.endswith(".ashbyhq.com"):
            board = host.split(".")[0]
        if board:
            return {
                "api_target_url": f"https://api.ashbyhq.com/posting-api/job-board/{board}",
                "method": "GET",
                "headers": {"Accept": "application/json"},
                "payload": None,
            }

    if ats == "ultipro":
        parts = _path_parts(url)
        if len(parts) >= 3 and parts[1].lower() == "jobboard":
            company_code = parts[0]
            board_id = parts[2]
            base_url = f"{parsed.scheme}://{host}"
            referer = f"{base_url}/{company_code}/JobBoard/{board_id}/"
            return {
                "api_target_url": f"{referer}JobBoardView/LoadSearchResults",
                "method": "POST",
                "headers": {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": referer,
                },
                "payload": _ultipro_payload(),
                "pagination": {
                    "type": "ultipro_skip_top",
                    "page_size": 100,
                    "max_pages": 10,
                },
            }

    return None
