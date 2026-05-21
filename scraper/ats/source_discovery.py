"""Discover reusable ATS/job-board sources from rendered links and HAR logs."""

from __future__ import annotations

from urllib.parse import urlparse

from scraper.ats.signal_scanner import scan_url


def _is_probable_job_board_url(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http") or not parsed.netloc:
        return False
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    if "rippling.com" in host and "/jobs" in path:
        return True
    return False


def _candidate_urls(raw_data: dict) -> list[str]:
    urls: list[str] = []
    for link in raw_data.get("links") or []:
        href = link.get("href")
        if href:
            urls.append(href)
    for entry in raw_data.get("har_entries") or []:
        url = entry.get("url")
        if url:
            urls.append(url)
    seen = set()
    out = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def discover_browser_target(raw_data: dict) -> dict | None:
    """Return an executable browser target spec from links/HAR, if one is obvious."""
    for url in _candidate_urls(raw_data):
        if not _is_probable_job_board_url(url):
            continue
        classification = scan_url(url)
        ats = classification.get("ats")
        if ats == "unknown":
            continue
        return {
            "ats": ats,
            "data_delivery_type": "html_page",
            "requires_browser": True,
            "browser_target_url": url,
            "api_target_url": None,
            "method": "NONE",
            "required_headers": {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "content_type": None,
                "authorization": None,
                "user_agent": None,
                "referer": raw_data.get("source_url"),
            },
            "payload": None,
            "json_path_to_listings": None,
            "explanation": f"Detected {ats} browser-rendered job board from page links or HAR.",
        }
    return None
