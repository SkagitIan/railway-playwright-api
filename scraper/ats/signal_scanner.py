"""Quick deterministic scanner for known ATS signals."""

from urllib.parse import urlparse


ATS_RULES = {
    "greenhouse": (
        "greenhouse.io",
        "boards.greenhouse.io",
    ),
    "lever": (
        "lever.co",
        "jobs.lever.co",
    ),
    "ashby": (
        "ashbyhq.com",
        "jobs.ashbyhq.com",
    ),
}


def scan_url(url: str) -> dict:
    domain = urlparse(url).netloc.lower()
    for ats, signals in ATS_RULES.items():
        if any(signal in domain for signal in signals):
            return {"ats": ats, "domain": domain, "strategy": "DIRECT_JSON_API"}
    return {"ats": "unknown", "domain": domain, "strategy": "BROWSER_HAR"}
