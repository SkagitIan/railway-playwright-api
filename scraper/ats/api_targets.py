"""Direct JSON API target construction for known ATS platforms."""

from __future__ import annotations

from urllib.parse import urlparse


def _first_path_part(url: str) -> str | None:
    parts = [part for part in urlparse(url).path.split("/") if part]
    return parts[0] if parts else None


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

    return None
