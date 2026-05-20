"""Stage 1: classify URL into an acquisition strategy."""

from urllib.parse import urlparse


async def run(stage_input: dict) -> dict:
    """Return a basic classification used by later pipeline stages."""
    url = stage_input["url"]
    domain = urlparse(url).netloc.lower()

    if "greenhouse.io" in domain:
        strategy = "DIRECT_JSON_API"
        ats = "greenhouse"
    elif "lever.co" in domain:
        strategy = "DIRECT_JSON_API"
        ats = "lever"
    else:
        strategy = "BROWSER_HAR"
        ats = "unknown"

    return {
        **stage_input,
        "classification": {
            "strategy": strategy,
            "ats": ats,
            "domain": domain,
        },
    }
