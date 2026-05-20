"""Stage 1: classify URL into an acquisition strategy."""

from scraper.ats.signal_scanner import scan_url


async def run(stage_input: dict) -> dict:
    """Return a basic classification used by later pipeline stages."""
    classification = scan_url(stage_input["url"])
    return {**stage_input, "classification": classification}
