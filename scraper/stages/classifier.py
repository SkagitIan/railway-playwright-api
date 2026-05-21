"""Stage 1: classify URL into an acquisition strategy."""

from urllib.parse import urlparse

from scraper.ats.signal_scanner import scan_url
from scraper.ats.spec_store import get_promoted_spec


async def run(stage_input: dict) -> dict:
    """Return a basic classification used by later pipeline stages."""
    url = stage_input["url"]
    domain = urlparse(url).netloc.lower()
    scanned = scan_url(url)
    if scanned.get("strategy") == "DIRECT_JSON_API":
        return {**stage_input, "domain": domain, "classification": scanned}

    promoted = get_promoted_spec(domain)
    if promoted:
        classification = {
            "strategy": "PROMOTED_SPEC",
            "ats": promoted.get("ats"),
            "source": "spec_store",
            "spec": promoted,
        }
    else:
        classification = scanned

    return {**stage_input, "domain": domain, "classification": classification}
