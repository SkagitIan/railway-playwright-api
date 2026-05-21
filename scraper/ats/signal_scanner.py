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
    "rippling": (
        "ats.rippling.com",
        "ats.us1.rippling.com",
    ),
    "ultipro": (
        "recruiting.ultipro.com",
        "recruiting2.ultipro.com",
        "recruiting.ultipro.ca",
    ),
}

BROWSER_RENDERED_ATS = {"rippling"}


def scan_url(url: str) -> dict:
    domain = urlparse(url).netloc.lower()
    for ats, signals in ATS_RULES.items():
        if any(signal in domain for signal in signals):
            if ats in BROWSER_RENDERED_ATS:
                return {"ats": ats, "domain": domain, "strategy": "BROWSER_HAR"}
            return {"ats": ats, "domain": domain, "strategy": "DIRECT_JSON_API"}
    return {"ats": "unknown", "domain": domain, "strategy": "BROWSER_HAR"}
